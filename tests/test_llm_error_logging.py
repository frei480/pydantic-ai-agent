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

print("LLM-ERRORS-OK")
