"""Полное логирование ошибок LLM.

Хранит снимок последнего вызова модели (kwargs чата), при сбое провайдера
собирает диагностическую запись (контекст + исключение целиком + снимок
запроса) и пишет её в ротируемый файл. Никакие ключи API не попадают в
запись: снимок строится из kwargs вызова `chat.completions.create`,
заголовки не логируются.
"""
from __future__ import annotations

import functools
import json
import logging
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from typing import Any, Mapping

from .config import LLM_ERROR_LOG_PATH

__all__ = [
    "LLM_ERROR_LOG_PATH",
    "capture_llm_requests",
    "record_llm_request",
    "last_request_snapshot",
    "format_exception_full",
    "render_failure_record",
    "log_llm_failure",
]

# Лимит дампа запроса в байтах (utf-8) и текст маркера обрезки.
_DUMP_LIMIT_BYTES = 1_000_000
_TRUNCATION_MARKER = "…[ОБРЕЗАНО: показано {shown} из {total} байт]"
# Лимит для отдельных строк ответа в описании исключения.
_ATTR_TEXT_LIMIT = 4000
# Ротация файла лога: 10 МБ, 5 резервных копий.
_ROTATE_MAX_BYTES = 10 * 1024 * 1024
_ROTATE_BACKUP_COUNT = 5

# Снимок последнего вызова: пишется из event-loop-потока и из asyncio.to_thread,
# поэтому доступ — под блокировкой.
_snapshot_lock = threading.Lock()
_last_request: dict[str, Any] | None = None

# Состояние файлового хендлера: создаётся один раз на путь; при ошибке открытия
# путь запоминается, чтобы не пытаться снова, пока путь не сменят.
_file_handler: RotatingFileHandler | None = None
_file_handler_path: str | None = None
_unavailable_path: str | None = None

# Логгер записей (не дублирует много-МБ записи в консоль); отдельный
# propagating-логгер для warning'ов и fallback'а, когда файл недоступен.
_logger = logging.getLogger("app.llm_errors")
_logger.propagate = False
_fallback_logger = logging.getLogger("app.llm_errors.file")


def capture_llm_requests(client: Any) -> None:
    """Обернуть `client.chat.completions.create`, чтобы запоминать kwargs вызова."""

    inner = client.chat.completions.create

    @functools.wraps(inner)
    async def _create(**kwargs: Any) -> Any:
        record_llm_request(kwargs)
        return await inner(**kwargs)

    client.chat.completions.create = _create


def record_llm_request(kwargs: Mapping[str, Any]) -> None:
    """Запомнить снимок последнего вызова модели (время + копия kwargs)."""
    global _last_request
    snapshot = {"captured_at": time.time(), "kwargs": dict(kwargs)}
    with _snapshot_lock:
        _last_request = snapshot


def last_request_snapshot(max_age_seconds: float = 600.0) -> dict[str, Any] | None:
    """Вернуть `{"captured_at", "kwargs"}` или None, если записи нет или она старше лимита."""
    with _snapshot_lock:
        if _last_request is None:
            return None
        if time.time() - _last_request["captured_at"] > max_age_seconds:
            return None
        return {
            "captured_at": _last_request["captured_at"],
            "kwargs": dict(_last_request["kwargs"]),
        }


def format_exception_full(exc: BaseException) -> str:
    """Трейсбек целиком плюс доступные атрибуты исключения openai.

    `status_code`, `request_id`, `body` и `response.text` (последние два
    обрезаются до 4000 символов) добавляются, только если есть у исключения.
    """
    if exc.__traceback__ is None:
        # исключение ещё не было выброшено — синтезируем трейсбек от текущей точки,
        # чтобы запись всегда начиналась с полного Traceback
        try:
            raise exc
        except BaseException:
            pass
    parts = ["".join(traceback.format_exception(type(exc), exc, exc.__traceback__))]
    for name in ("status_code", "request_id"):
        try:
            value = getattr(exc, name, None)
        except Exception:
            value = None
        if value is not None:
            parts.append(f"{name}: {value!r}\n")
    for name in ("body", "response.text"):
        try:
            value = getattr(exc, name, None) if name == "body" else getattr(getattr(exc, "response", None), "text", None)
        except Exception:
            value = None
        if value:
            parts.append(f"{name} (первые {_ATTR_TEXT_LIMIT} символов): {str(value)[:_ATTR_TEXT_LIMIT]}\n")
    return "".join(parts)


def _truncate_bytes(text: str, limit: int = _DUMP_LIMIT_BYTES) -> str:
    """Обрезать текст до `limit` байт utf-8, не разрывая многобайтовый символ."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    cut = data[:limit]
    while cut:
        try:
            shown = cut.decode("utf-8")
            break
        except UnicodeDecodeError:
            cut = cut[:-1]
    else:
        shown = ""
    return shown + _TRUNCATION_MARKER.format(shown=len(cut), total=len(data))


def render_failure_record(
    exc: BaseException,
    context: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> str:
    """Собрать диагностическую запись: контекст, исключение целиком, снимок запроса."""
    lines = []
    if context:
        lines.append("[КОНТЕКСТ] " + ", ".join(f"{key}={value}" for key, value in context.items()))
    lines.append("[ИСКЛЮЧЕНИЕ - ПОЛНОСТЬЮ]")
    lines.append(format_exception_full(exc))
    lines.append("[ПОСЛЕДНИЙ ЗАПРОС К МОДЕЛИ]")
    if snapshot is None:
        lines.append("снимок запроса отсутствует (нет вызова за последние 10 мин)")
    else:
        dump = json.dumps(snapshot, ensure_ascii=False, indent=1, default=repr)
        lines.append(_truncate_bytes(dump))
    return "\n".join(lines) + "\n"


def _ensure_file_handler() -> RotatingFileHandler | None:
    """Создать RotatingFileHandler для текущего LLM_ERROR_LOG_PATH один раз на путь.

    Если файл не открывается (OSError) — warning в обычный лог и отказ от
    попыток, пока путь не изменится. Никогда не бросает исключение наружу.
    """
    global _file_handler, _file_handler_path, _unavailable_path
    path = LLM_ERROR_LOG_PATH
    path_str = str(path)
    if _file_handler is not None and _file_handler_path == path_str:
        return _file_handler
    if _unavailable_path == path_str:
        return None
    try:
        handler = RotatingFileHandler(
            path,
            maxBytes=_ROTATE_MAX_BYTES,
            backupCount=_ROTATE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as error:
        _unavailable_path = path_str
        _fallback_logger.warning(
            "Не удалось открыть файл лога ошибок LLM %s: %s; запись в файл отключена до смены пути",
            path,
            error,
        )
        return None
    _logger.addHandler(handler)
    _file_handler = handler
    _file_handler_path = path_str
    return handler


def log_llm_failure(exc: BaseException, *, context: dict[str, Any] | None = None) -> None:
    """Записать полную ошибку LLM в ротируемый файл и в обычный лог.

    Берёт снимок последнего запроса сама; сбой открытия файла не мешает
    вызывающему коду — запись уходит в обычный лог (в обрезанном виде).
    """
    record = render_failure_record(exc, context, last_request_snapshot())
    if _ensure_file_handler() is not None:
        _logger.error("%s", record)
    else:
        _fallback_logger.error("%s", _truncate_bytes(record, _ATTR_TEXT_LIMIT))
