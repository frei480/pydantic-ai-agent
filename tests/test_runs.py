"""Фоновые запуски: реестр, буфер событий, подписка, отмена, HTTP-слой."""
import asyncio
import contextlib
import json
import os
import sys
import tempfile
import time

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import runs  # noqa: E402

# env лога ошибок — до импорта app.main (config читает его при импорте)
os.environ.setdefault(
    "LLM_ERROR_LOG_PATH",
    os.path.join(tempfile.gettempdir(), "test_runs_llm.log"),
)

from app import agent, auth, config, main  # noqa: E402
from app.db import Database  # noqa: E402


async def collect(stream):
    return [event async for event in stream]


FINAL = {"type": "final", "text": "готовый ответ", "history_json": "[]"}


def install_pipeline(script):
    """Подменить agent.run_pipeline управляемым генератором.

    script: список ('event', dict) | ('wait', asyncio.Event) | ('raise', Exception).
    Возвращает restore-функцию.
    """
    original = agent.run_pipeline

    async def fake_pipeline(user_text, history_json):
        for kind, payload in script:
            if kind == "wait":
                await payload.wait()
            elif kind == "raise":
                raise payload
            else:
                yield payload

    agent.run_pipeline = fake_pipeline

    def restore():
        agent.run_pipeline = original

    return restore


@contextlib.asynccontextmanager
async def app_env(kerberos=False, admins=None):
    """Временная база + свежий реестр запусков; восстановление в finally."""
    original_dbase = main.dbase
    original_registry = main.runs_registry
    original_mode = auth.AUTH_MODE
    original_admins = config.ADMIN_USERS
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "runs.db"))
        await database.connect()
        main.dbase = database
        main.runs_registry = runs.RunRegistry()
        if kerberos:
            auth.AUTH_MODE = "kerberos"
            config.ADMIN_USERS = admins if admins is not None else set()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                yield database, client
        finally:
            config.ADMIN_USERS = original_admins
            auth.AUTH_MODE = original_mode
            main.runs_registry = original_registry
            main.dbase = original_dbase
            await database.close()


async def make_chat(client) -> int:
    # без заголовка: POST сообщения сам называет чат по первому вопросу
    response = await client.post("/api/chats", json={})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def wait_for_answer(database, chat_id, timeout=5.0):
    """Ждать конца запуска: ответ сохранён И active_run снят.

    Ответ пишется в БД до завершающего события, поэтому одного наличия
    сообщения мало — иначе гонка с finish().
    """
    deadline = time.monotonic() + timeout
    messages = []
    while time.monotonic() < deadline:
        messages = await database.get_messages(chat_id)
        answered = any(m["role"] == "assistant" for m in messages)
        if answered and main.runs_registry.active_run_id(chat_id) is None:
            return messages
        await asyncio.sleep(0.02)
    raise AssertionError(f"запуск не завершился за {timeout} с: {messages}")


def parse_sse(text):
    events = []
    for line in text.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:]))
    return events


async def user_cookie(login: str) -> str:
    secret = await auth.session_secret(main.dbase)
    return auth.sign_user_session(login, int(time.time()) + 3600, secret)



async def check_publish_subscribe_order():
    registry = runs.RunRegistry()
    run = registry.register(7)
    run.publish({"type": "phase", "phase": "research"})
    run.publish({"type": "text", "text": "часть"})
    run.finish("done")
    events = await collect(registry.stream_events(run, 0))
    assert [e["seq"] for e in events] == [1, 2, 3], events
    assert events[-1] == {"type": "done", "seq": 3}, events
    assert events[0] == {"type": "phase", "phase": "research", "seq": 1}, events


async def check_resume_from_seq():
    registry = runs.RunRegistry()
    run = registry.register(7)
    run.publish({"type": "text", "text": "a"})
    run.publish({"type": "text", "text": "b"})
    run.finish("done")
    from1 = await collect(registry.stream_events(run, 1))
    assert [e["seq"] for e in from1] == [2, 3], from1
    from3 = await collect(registry.stream_events(run, 3))
    assert from3 == [], from3


async def check_busy_chat():
    registry = runs.RunRegistry()
    registry.register(7)
    try:
        registry.register(7)
    except runs.ChatBusyError:
        pass
    else:
        raise AssertionError("второй register в занятый чат должен поднять ChatBusyError")
    other = registry.register(8)
    assert other.chat_id == 8
    run7 = registry.get(other.id)  # промежуточная проверка get
    assert run7 is other
    done = runs.RunRegistry()
    first = done.register(7)
    first.finish("done")
    second = done.register(7)
    assert second.id != first.id


async def check_cancel_semantics():
    registry = runs.RunRegistry()
    run = registry.register(1)
    run.task = asyncio.create_task(asyncio.sleep(60))
    assert run.cancel() is True
    with_npc = registry.register(2)
    with_npc.begin_finish()
    assert with_npc.cancel() is False
    with_npc.finish("cancelled")
    assert with_npc.cancel() is False
    await asyncio.sleep(0)  # отмена доставляется, когда луп даст задаче ход
    assert run.task.cancelled() or run.task.done()


async def check_heartbeat_not_buffered():
    original = runs.HEARTBEAT_SECONDS
    runs.HEARTBEAT_SECONDS = 0.05
    try:
        registry = runs.RunRegistry()
        run = registry.register(1)
        received = []

        async def consumer():
            async for event in registry.stream_events(run, 0):
                received.append(event)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.2)
        assert any(e == {"type": "heartbeat"} for e in received), received
        run.publish({"type": "text", "text": "x"})
        run.finish("done")
        await asyncio.wait_for(task, timeout=5)
        assert len(run.events) == 2, run.events
        assert run.events[-1]["seq"] == 2, run.events
        assert received[-1] == {"type": "done", "seq": 2}, received
    finally:
        runs.HEARTBEAT_SECONDS = original


async def check_reap_old_finished():
    original = runs.TERMINAL_KEEP_SECONDS
    runs.TERMINAL_KEEP_SECONDS = 0.0
    try:
        registry = runs.RunRegistry()
        finished = registry.register(1)
        finished.publish({"type": "text", "text": "x"})
        finished.finish("done")
        alive = registry.register(2)
        registry.reap()
        assert registry.get(finished.id) is None
        assert registry.get(alive.id) is alive
    finally:
        runs.TERMINAL_KEEP_SECONDS = original


async def check_post_returns_202_and_runs():
    gate = asyncio.Event()
    restore = install_pipeline(
        [
            ("event", {"type": "phase", "phase": "research"}),
            ("wait", gate),
            ("event", FINAL),
        ]
    )
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            response = await client.post(
                f"/api/chats/{chat_id}/messages", json={"content": "вопрос про сплайны"}
            )
            assert response.status_code == 202, response.text
            body = response.json()
            assert body["run_id"], body
            assert body["chat"]["title"] == "вопрос про сплайны", body
            run_id = body["run_id"]

            state = await client.get(f"/api/chats/{chat_id}/messages")
            assert state.json()["chat"]["active_run"] == run_id, state.text
            assert not [
                m for m in state.json()["messages"] if m["role"] == "assistant"
            ], state.text

            gate.set()
            messages = await wait_for_answer(database, chat_id)
            assert messages[-1]["content"] == "готовый ответ", messages
            state = await client.get(f"/api/chats/{chat_id}/messages")
            assert state.json()["chat"]["active_run"] is None, state.text
    finally:
        restore()


async def raw_disconnect_get(path: str) -> None:
    """Прямой вызов ASGI-приложения: GET, чьё соединение рвётся сразу.

    httpx.ASGITransport не propagирует раннее закрытие потока как disconnect,
    поэтому обрыв имитируем сырым вызовом: второй receive возвращает
    http.disconnect, Starlette отменяет SSE-генератор.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path.split("?")[0],
        "query_string": path.split("?", 1)[1].encode() if "?" in path else b"",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        pass  # тело не читаем — интересует только факт обрыва

    await asyncio.wait_for(main.app(scope, receive, send), timeout=5)


async def check_survives_subscriber_close():
    gate = asyncio.Event()
    restore = install_pipeline(
        [
            ("event", {"type": "phase", "phase": "research"}),
            ("wait", gate),
            ("event", FINAL),
        ]
    )
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            run_id = (
                await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "вопрос"}
                )
            ).json()["run_id"]

            # подписчик оборвал соединение в начале — запуск продолжает жить
            await raw_disconnect_get(f"/api/chats/{chat_id}/runs/{run_id}/events")
            run = main.runs_registry.get(run_id)
            assert run is not None and run.is_running

            gate.set()
            messages = await wait_for_answer(database, chat_id)
            assert messages[-1]["content"] == "готовый ответ", messages
            replay = await client.get(
                f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
            )
            types = [e["type"] for e in parse_sse(replay.text)]
            assert "done" in types, types
    finally:
        gate.set()
        restore()


async def check_replay_finished_run():
    restore = install_pipeline(
        [
            ("event", {"type": "phase", "phase": "research"}),
            ("event", {"type": "text", "text": "часть"}),
            ("event", FINAL),
        ]
    )
    original_keep = runs.TERMINAL_KEEP_SECONDS
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            run_id = (
                await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "вопрос"}
                )
            ).json()["run_id"]
            await wait_for_answer(database, chat_id)

            full = await client.get(
                f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
            )
            events = parse_sse(full.text)
            assert [e["type"] for e in events] == ["phase", "text", "done"], events
            assert [e["seq"] for e in events] == [1, 2, 3], events

            from2 = parse_sse(
                (
                    await client.get(
                        f"/api/chats/{chat_id}/runs/{run_id}/events?from=2"
                    )
                ).text
            )
            assert [e["seq"] for e in from2] == [3], from2

            from3 = parse_sse(
                (
                    await client.get(
                        f"/api/chats/{chat_id}/runs/{run_id}/events?from=3"
                    )
                ).text
            )
            assert from3 == [], from3

            runs.TERMINAL_KEEP_SECONDS = 0.0
            await asyncio.sleep(0.01)
            gone = await client.get(
                f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
            )
            assert gone.status_code == 404, gone.text
    finally:
        runs.TERMINAL_KEEP_SECONDS = original_keep
        restore()


async def check_active_run_in_list():
    gate = asyncio.Event()
    restore = install_pipeline([("wait", gate), ("event", FINAL)])
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            run_id = (
                await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "вопрос"}
                )
            ).json()["run_id"]
            chats = (await client.get("/api/chats")).json()
            assert [c["active_run"] for c in chats] == [run_id], chats
            gate.set()
            await wait_for_answer(database, chat_id)
            chats = (await client.get("/api/chats")).json()
            assert [c["active_run"] for c in chats] == [None], chats
    finally:
        restore()


async def check_post_conflict():
    gate = asyncio.Event()
    restore = install_pipeline([("wait", gate), ("event", FINAL)])
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            first = await client.post(
                f"/api/chats/{chat_id}/messages", json={"content": "первый"}
            )
            assert first.status_code == 202, first.text
            second = await client.post(
                f"/api/chats/{chat_id}/messages", json={"content": "второй"}
            )
            assert second.status_code == 409, second.text
            assert second.json()["detail"] == (
                "Агент ещё обрабатывает предыдущее сообщение"
            ), second.text
            messages = await database.get_messages(chat_id)
            assert [m["content"] for m in messages] == ["первый"], messages

            gate.set()
            await wait_for_answer(database, chat_id)
            third = await client.post(
                f"/api/chats/{chat_id}/messages", json={"content": "снова"}
            )
            assert third.status_code == 202, third.text
            await wait_for_answer(database, chat_id)  # не оставлять задачу-зомби
    finally:
        gate.set()
        restore()


async def check_concurrent_post_single_run():
    gate = asyncio.Event()
    restore = install_pipeline([("wait", gate), ("event", FINAL)])
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            first, second = await asyncio.gather(
                client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "клик 1"}
                ),
                client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "клик 2"}
                ),
            )
            assert sorted([first.status_code, second.status_code]) == [202, 409], (
                first.status_code,
                second.status_code,
            )
            gate.set()
            messages = await wait_for_answer(database, chat_id)
            assert [m["role"] for m in messages] == ["user", "assistant"], messages
            assert len([m for m in messages if m["role"] == "user"]) == 1, messages
    finally:
        gate.set()
        restore()


async def check_error_saves_partial():
    restore = install_pipeline(
        [
            ("event", {"type": "text", "text": "Часть "}),
            ("event", {"type": "text", "text": "ответа"}),
            ("raise", RuntimeError("провал провайдера")),
        ]
    )
    try:
        async with app_env() as (database, client):
            chat_id = await make_chat(client)
            run_id = (
                await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "вопрос"}
                )
            ).json()["run_id"]
            messages = await wait_for_answer(database, chat_id)
            assert messages[-1]["content"] == (
                "Часть ответа\n\n**Ошибка:** провал провайдера"
            ), messages[-1]["content"]

            events = parse_sse(
                (
                    await client.get(
                        f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
                    )
                ).text
            )
            types = [e["type"] for e in events]
            assert "error" in types and "done" not in types, types
            error_event = next(e for e in events if e["type"] == "error")
            assert error_event["message"] == "провал провайдера", error_event

            log_content = open(
                os.environ["LLM_ERROR_LOG_PATH"], encoding="utf-8"
            ).read()
            assert "провал провайдера" in log_content
    finally:
        restore()


async def check_rights_runs_routes():
    gate = asyncio.Event()
    restore = install_pipeline([("wait", gate), ("event", FINAL)])
    try:
        async with app_env(kerberos=True, admins={"admin"}) as (database, client):
            client.cookies.set("docs_ai_session", await user_cookie("alice"))
            chat_id = await make_chat(client)
            run_id = (
                await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "вопрос"}
                )
            ).json()["run_id"]

            client.cookies.delete("docs_ai_session")
            anonymous = await client.get(
                f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
            )
            assert anonymous.status_code == 401, anonymous.text

            client.cookies.set("docs_ai_session", await user_cookie("bob"))
            foreign_post = await client.post(
                f"/api/chats/{chat_id}/messages", json={"content": "чужой"}
            )
            assert foreign_post.status_code == 404, foreign_post.text
            foreign_events = await client.get(
                f"/api/chats/{chat_id}/runs/{run_id}/events?from=0"
            )
            assert foreign_events.status_code == 404, foreign_events.text

            gate.set()
            run = main.runs_registry.get(run_id)
            if run and run.task:
                await asyncio.wait_for(asyncio.shield(run.task), timeout=5)
    finally:
        gate.set()
        restore()


asyncio.run(check_publish_subscribe_order())
asyncio.run(check_resume_from_seq())
asyncio.run(check_busy_chat())
asyncio.run(check_cancel_semantics())
asyncio.run(check_heartbeat_not_buffered())
asyncio.run(check_reap_old_finished())
print("RUNS-REGISTRY-OK")
asyncio.run(check_post_returns_202_and_runs())
asyncio.run(check_survives_subscriber_close())
asyncio.run(check_replay_finished_run())
asyncio.run(check_active_run_in_list())
asyncio.run(check_post_conflict())
asyncio.run(check_concurrent_post_single_run())
asyncio.run(check_error_saves_partial())
asyncio.run(check_rights_runs_routes())
print("RUNS-API-OK")
