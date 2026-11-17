"""Проверки модуля полного логирования ошибок LLM (снимок запроса + запись в файл)."""
import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "backend")

from httpx2 import Request, Response  # noqa: E402
from openai import APIStatusError  # noqa: E402

from app import llm_errors  # noqa: E402

# 1) снимок: record -> last_request_snapshot(); без записи -> None; устаревший -> None
assert llm_errors.last_request_snapshot() is None

llm_errors.record_llm_request({"model": "m-0", "messages": []})
snap = llm_errors.last_request_snapshot()
assert snap is not None and snap["kwargs"]["model"] == "m-0"
assert isinstance(snap["captured_at"], float)

# смещаем captured_at на 601 секунду назад — снимок устарел для max_age 600
with llm_errors._snapshot_lock:
    llm_errors._last_request["captured_at"] = time.time() - 601
assert llm_errors.last_request_snapshot(max_age_seconds=600.0) is None
assert llm_errors.last_request_snapshot(max_age_seconds=700.0) is not None

# свежая запись перекрывает устаревшую
llm_errors.record_llm_request({"model": "m-1", "messages": [{"role": "user", "content": "привет"}]})
assert llm_errors.last_request_snapshot()["kwargs"]["model"] == "m-1"


# 2) capture_llm_requests на стаб-клиенте
async def check_capture():
    sentinel = {"id": "resp-1"}

    async def _orig_async_create(**kwargs):
        return sentinel

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_orig_async_create)))
    llm_errors.capture_llm_requests(fake)
    result = await fake.chat.completions.create(
        model="m-1", messages=[{"role": "user", "content": "привет"}]
    )
    assert result is sentinel  # результат вызова проходит насквозь
    assert last_request_snapshot()["kwargs"]["model"] == "m-1"


last_request_snapshot = llm_errors.last_request_snapshot
asyncio.run(check_capture())
assert llm_errors.last_request_snapshot()["kwargs"]["messages"][0]["content"] == "привет"


# 3) format_exception_full на реальном исключении openai
def make_429() -> APIStatusError:
    resp = Response(
        429,
        request=Request("POST", "http://t/v1/chat/completions"),
        text='{"error":{"message":"quota"}}',
    )
    return APIStatusError("Error code: 429 - quota", response=resp, body={"error": {"message": "quota"}})


exc = make_429()
text = llm_errors.format_exception_full(exc)
assert "Traceback" in text and "429" in text and "quota" in text

# 4) render_failure_record
snap = llm_errors.last_request_snapshot()
record = llm_errors.render_failure_record(exc, {"chat_id": 5}, snap)
assert "[КОНТЕКСТ] chat_id=5" in record
assert "[ИСКЛЮЧЕНИЕ - ПОЛНОСТЬЮ]" in record
assert "[ПОСЛЕДНИЙ ЗАПРОС К МОДЕЛИ]" in record
assert "m-1" in record and "привет" in record

record_no_snapshot = llm_errors.render_failure_record(exc, None, None)
assert "снимок запроса отсутствует" in record_no_snapshot

record_big = llm_errors.render_failure_record(
    exc,
    None,
    {"captured_at": time.time(), "kwargs": {"messages": [{"role": "user", "content": "a" * 2_000_000}]}},
)
assert "ОБРЕЗАНО: показано 1000000 из" in record_big

# 5) log_llm_failure во временный файл
tmp_dir = tempfile.mkdtemp()
log_path = Path(tmp_dir) / "llm-errors.log"
orig_path = llm_errors.LLM_ERROR_LOG_PATH
try:
    llm_errors.LLM_ERROR_LOG_PATH = log_path
    llm_errors.log_llm_failure(exc, context={"chat_id": 5})
    llm_errors.log_llm_failure(exc, context={"chat_id": 5})
    assert len(logging.getLogger("app.llm_errors").handlers) == 1
    written = log_path.read_text(encoding="utf-8")
    assert "429" in written

    # 6) недоступный путь (несуществующий диск): не бросает исключение
    llm_errors.LLM_ERROR_LOG_PATH = Path("Z:/no/x.log")
    llm_errors.log_llm_failure(exc)
    llm_errors.log_llm_failure(exc)  # повтор — тоже без исключений, без повторной попытки
    assert len(logging.getLogger("app.llm_errors").handlers) == 1
finally:
    llm_errors.LLM_ERROR_LOG_PATH = orig_path

# 7) перехват запросов реального клиента _RetryTransientErrorsAsyncOpenAI
async def check_client_capture():
    from openai import APIConnectionError

    from app.agent import _RetryTransientErrorsAsyncOpenAI

    client = _RetryTransientErrorsAsyncOpenAI(
        api_key="k", base_url="http://127.0.0.1:1/v1", max_retries=0
    )
    try:
        try:
            await client.chat.completions.create(
                model="probe-m", messages=[{"role": "user", "content": "x"}], max_tokens=1
            )
        except APIConnectionError:
            pass  # порт 1 закрыт — ожидаемый отказ
        else:
            raise AssertionError("ожидался APIConnectionError")
        snap = llm_errors.last_request_snapshot()
        assert snap is not None, "запрос основного клиента не зафиксирован"
        assert snap["kwargs"]["model"] == "probe-m", (
            f"клиент не зафиксировал свой запрос, в снапшоте model={snap['kwargs'].get('model')!r}"
        )

        # клон через with_options тоже фиксирует запросы
        clone = client.with_options(max_retries=0)
        try:
            await clone.chat.completions.create(
                model="probe-clone", messages=[{"role": "user", "content": "y"}], max_tokens=1
            )
        except APIConnectionError:
            pass
        else:
            raise AssertionError("ожидался APIConnectionError от клона")
        snap_clone = llm_errors.last_request_snapshot()
        assert snap_clone is not None, "запрос клона не зафиксирован"
        assert snap_clone["kwargs"]["model"] == "probe-clone", (
            f"клон не зафиксировал свой запрос, в снапшоте model={snap_clone['kwargs'].get('model')!r}"
        )

        await clone.close()
    finally:
        await client.close()


asyncio.run(check_client_capture())


# 8) зависший (in-flight) запрос: снимок доступен, пока вызов ещё не завершился
async def check_inflight():
    seen = {}

    async def _hanging_create(**kwargs):
        # мы внутри вызова: снимок должен вернуться даже с крошечным лимитом
        # возраста — in-flight запись не проверяется по возрасту
        seen["small_age"] = llm_errors.last_request_snapshot(max_age_seconds=0.001)
        seen["zero_age"] = llm_errors.last_request_snapshot(max_age_seconds=0.0)
        raise RuntimeError("имитация зависшего вызова")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_hanging_create)))
    llm_errors.capture_llm_requests(fake)
    # предыстория: устаревшая завершённая запись (старше 600 c) не должна
    # маскировать in-flight — именно она и была бы отброшена проверкой возраста
    with llm_errors._snapshot_lock:
        llm_errors._last_request = {"captured_at": time.time() - 601, "kwargs": {"model": "m-old"}}
    try:
        await fake.chat.completions.create(model="m-hang", messages=[{"role": "user", "content": "x"}])
    except RuntimeError:
        pass
    else:
        raise AssertionError("ожидался RuntimeError от стаба")
    for key in ("small_age", "zero_age"):
        snap = seen[key]
        assert snap is not None, f"in-flight снимок не вернулся ({key})"
        assert snap["kwargs"]["model"] == "m-hang", f"неожиданный снимок ({key}): {snap['kwargs']}"
    # после завершения (успех или сбой) слот in-flight очищен: устареваем
    # завершённую запись и проверяем, что с крошечным лимитом снимка нет —
    # неочищенный in-flight вернул бы запись независимо от возраста
    with llm_errors._snapshot_lock:
        llm_errors._last_request["captured_at"] = time.time() - 601
    assert llm_errors.last_request_snapshot(max_age_seconds=0.001) is None
    # а с обычным лимитом завершённая запись по-прежнему доступна
    assert llm_errors.last_request_snapshot(max_age_seconds=700.0)["kwargs"]["model"] == "m-hang"


asyncio.run(check_inflight())


# 9) внешний предохранитель log_llm_failure: сбой рендеринга не рвёт вызывающий код
class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


capture = _CaptureHandler()
fallback_logger = logging.getLogger("app.llm_errors.file")
orig_render = llm_errors.render_failure_record
orig_fallback_level = fallback_logger.level


def _boom(*args, **kwargs):
    raise RuntimeError("поломанный рендер")


llm_errors.render_failure_record = _boom
fallback_logger.addHandler(capture)
fallback_logger.setLevel(logging.ERROR)
try:
    llm_errors.log_llm_failure(exc, context={"chat_id": 1})  # не должно бросить
finally:
    llm_errors.render_failure_record = orig_render
    fallback_logger.removeHandler(capture)
    fallback_logger.setLevel(orig_fallback_level)

assert any("сбой записи полной ошибки" in message for message in capture.messages), capture.messages
# в последней надежде указан тип исходного исключения и оно само
assert "APIStatusError" in " ".join(capture.messages) and "quota" in " ".join(capture.messages)


# 10) «завис и упал» после 600+ c: при выходе с исключением метка завершённой
# записи обновляется — снимок упавшего запроса не отбрасывается возрастом
async def check_hang_then_fail():
    async def _failing_create(**kwargs):
        raise RuntimeError("падение после долгого зависания")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_failing_create)))
    llm_errors.capture_llm_requests(fake)
    # предыстория: заведомо устаревшая запись — без обновления метки на выходе
    # с исключением снимок упавшего запроса был бы отброшен проверкой возраста
    with llm_errors._snapshot_lock:
        llm_errors._last_request = {"captured_at": time.time() - 9999, "kwargs": {"model": "stale"}}
    try:
        await fake.chat.completions.create(model="m-fail", messages=[{"role": "user", "content": "y"}])
    except RuntimeError:
        pass
    else:
        raise AssertionError("ожидался RuntimeError")
    snap = llm_errors.last_request_snapshot()  # обычный лимит 600 c
    assert snap is not None, "снимок упавшего запроса отброшен проверкой возраста"
    assert snap["kwargs"]["model"] == "m-fail", f"вернулся не тот снимок: {snap['kwargs']}"
    # in-flight слот после завершения очищен (иначе снимок вернулся бы и без обновления)
    with llm_errors._snapshot_lock:
        assert llm_errors._in_flight is None


asyncio.run(check_hang_then_fail())

print("LLM-CAPTURE-OK")

print("LLM-ERRORS-OK")
