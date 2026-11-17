"""Проверки склейки system-сообщений в одно ведущее system-сообщение.

Строгие chat-шаблоны (Qwen 3.x) падают с `System message must be at the
beginning`, если в запросе несколько system-сообщений или system идёт не
первым; pydantic-ai формирует их несколько. Модуль `app.llm_messages`
нормализует тело запроса до отправки провайдеру.
"""
import asyncio
import sys
from types import SimpleNamespace

sys.path.insert(0, "backend")

from app.llm_errors import capture_llm_requests, last_request_snapshot  # noqa: E402
from app.llm_messages import (  # noqa: E402
    merge_system_messages,
    merge_system_messages_in_requests,
)

# 1) три system-сообщения перед user склеиваются в одно ведущее
messages = [
    {"role": "system", "content": "инструкции исследователя"},
    {"role": "system", "content": "подсказка о подагентах"},
    {"role": "system", "content": '<pyai:context id="capability:deferred_capabilities">'},
    {"role": "user", "content": "3D точки по спирали, диаметр 20, высота 30"},
]
merged = merge_system_messages(messages)
assert merged == [
    {
        "role": "system",
        "content": (
            "инструкции исследователя\n\n"
            "подсказка о подагентах\n\n"
            '<pyai:context id="capability:deferred_capabilities">'
        ),
    },
    {"role": "user", "content": "3D точки по спирали, диаметр 20, высота 30"},
], merged
# исходные сообщения не изменяются: история pydantic-ai переиспользует их
assert len(messages) == 4
assert messages[0]["content"] == "инструкции исследователя"
assert messages[1]["role"] == "system"

# 2) повторная склейка ничего не меняет (ретрай того же запроса на 500/429)
assert merge_system_messages(merged) is None

# 3) менять нечего
assert merge_system_messages([]) is None
assert merge_system_messages([{"role": "user", "content": "x"}]) is None
assert merge_system_messages([{"role": "system", "content": "x"}]) is None
assert (
    merge_system_messages(
        [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    )
    is None
)

# 4) system не первым — переезжает в начало, порядок остальных сохраняется
reordered = merge_system_messages(
    [
        {"role": "user", "content": "вопрос"},
        {"role": "assistant", "content": "ответ"},
        {"role": "system", "content": "напоминание"},
        {"role": "user", "content": "ещё вопрос"},
    ]
)
assert reordered is not None
assert [m["role"] for m in reordered] == ["system", "user", "assistant", "user"], reordered
assert reordered[0]["content"] == "напоминание"

# 5) developer-роль склеивается в system: строгий шаблон не знает такой роли
assert merge_system_messages(
    [
        {"role": "developer", "content": "dev-инструкция"},
        {"role": "system", "content": "sys-инструкция"},
        {"role": "user", "content": "x"},
    ]
) == [
    {"role": "system", "content": "dev-инструкция\n\nsys-инструкция"},
    {"role": "user", "content": "x"},
]
assert merge_system_messages(
    [{"role": "developer", "content": "dev"}, {"role": "user", "content": "x"}]
) == [{"role": "system", "content": "dev"}, {"role": "user", "content": "x"}]

# 6) content-parts: текстовые части переносятся, нетекстовые отбрасываются
parts_merged = merge_system_messages(
    [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "часть 1"},
                {"type": "image_url", "image_url": {"url": "http://example/x.png"}},
            ],
        },
        {"role": "system", "content": [{"type": "text", "text": "часть 2"}]},
        {"role": "user", "content": "x"},
    ]
)
assert parts_merged is not None
assert parts_merged[0]["content"] == "часть 1\n\nчасть 2"

# 7) пустые system-сообщения не создают пустой блок
assert (
    merge_system_messages(
        [{"role": "system", "content": None}, {"role": "system", "content": "   "}]
    )
    is None
)
only_non_empty = merge_system_messages(
    [
        {"role": "system", "content": None},
        {"role": "system", "content": "x"},
        {"role": "user", "content": "y"},
    ]
)
assert only_non_empty is not None
assert only_non_empty[0]["content"] == "x"


# 8) обёртка create: провайдеру уходит склеенное тело, ответ и kwargs — как есть
async def check_wrapper() -> None:
    seen: dict[str, object] = {}
    sentinel = {"id": "resp-1"}

    async def _orig_create(**kwargs: object) -> object:
        seen.update(kwargs)
        return sentinel

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_orig_create))
    )
    merge_system_messages_in_requests(client)
    result = await client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        stream=True,
        messages=[
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "c"},
        ],
    )
    assert result is sentinel
    assert seen["model"] == "qwen/qwen3.8-27b" and seen["stream"] is True
    assert seen["messages"] == [
        {"role": "system", "content": "a\n\nb"},
        {"role": "user", "content": "c"},
    ], seen["messages"]

    # запрос без messages (например, служебный) не ломается и не дополняется
    seen.clear()
    await client.chat.completions.create(model="m")
    assert seen == {"model": "m"}

    # неожиданная форма messages: запрос не трогаем, а не портим
    seen.clear()
    await client.chat.completions.create(model="m", messages=None)
    assert seen == {"model": "m", "messages": None}, seen
    seen.clear()
    await client.chat.completions.create(model="m", messages=[])
    assert seen == {"model": "m", "messages": []}, seen
    seen.clear()
    await client.chat.completions.create(model="m", messages=["строка вместо сообщения"])
    assert seen == {"model": "m", "messages": ["строка вместо сообщения"]}, seen


asyncio.run(check_wrapper())


# 9) порядок перехватов как в _RetryTransientErrorsAsyncOpenAI: склейка стоит
#    снаружи логирования, поэтому в снимке последнего запроса — отправленное тело
async def check_capture_sees_merged() -> None:
    seen: dict[str, object] = {}

    async def _orig_create(**kwargs: object) -> object:
        seen.update(kwargs)
        return {"id": "resp-2"}

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_orig_create))
    )
    capture_llm_requests(client)
    merge_system_messages_in_requests(client)
    await client.chat.completions.create(
        model="m",
        messages=[
            {"role": "system", "content": "s1"},
            {"role": "system", "content": "s2"},
            {"role": "user", "content": "q"},
        ],
    )
    snapshot = last_request_snapshot()
    assert snapshot is not None
    expected = [{"role": "system", "content": "s1\n\ns2"}, {"role": "user", "content": "q"}]
    assert snapshot["kwargs"]["messages"] == expected, snapshot["kwargs"]["messages"]
    assert seen["messages"] == expected


asyncio.run(check_capture_sees_merged())

print("SYSTEM-MERGE-OK")
