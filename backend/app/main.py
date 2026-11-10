import asyncio
import json
import logging
import time

from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal, TypedDict
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from . import agent, db, models
from .config import (
    DB_PATH,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DOCS_ROOT,
)

dbase = db.Database(DB_PATH)
logger = logging.getLogger(__name__)
MODEL_HEALTH_CACHE_TTL = 60 * 60


class SettingsOut(TypedDict):
    provider: str
    model: str
    base_url: str
    api_key_configured: bool
    context_window_tokens: int


class ChatOut(TypedDict):
    id: int
    title: str
    created_at: str
    updated_at: str


class HealthOut(TypedDict):
    status: Literal["ok"]
    model: str
    provider: str
    docs_root: str
    context_token_limit: int


class ModelHealthOut(TypedDict):
    status: Literal["ok", "error"]
    model: str
    detail: str


class ChatMessagesOut(TypedDict):
    chat: ChatOut
    messages: list[models.Message]


_model_health_cache: ModelHealthOut | None = None
_model_health_checked_at = 0.0
_model_health_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await dbase.connect()
    settings = await dbase.get_model_settings()
    if settings is None:
        defaults = agent.current_model_settings()
        await dbase.save_model_settings(
            defaults.provider,
            defaults.model,
            defaults.api_key,
            defaults.base_url,
            defaults.context_window_tokens,
        )
    else:
        agent.configure_model(agent.ModelSettings(**settings))
    yield
    await dbase.close()


app = FastAPI(title="Docs AI Agent", lifespan=lifespan)


# -------------------------------------------------------------------
# Модели запросов
# -------------------------------------------------------------------


class ChatIn(BaseModel):
    title: str = "Новый чат"


class MessageIn(BaseModel):
    content: str


class ModelSettingsIn(BaseModel):
    provider: Literal["openai", "openrouter", "ollama", "lmstudio", "custom"]
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    context_window_tokens: int = Field(
        default=DEFAULT_CONTEXT_WINDOW_TOKENS, ge=4096, le=2_000_000
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите название модели")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        value = (value or "").strip()
        if not value:
            provider = info.data.get("provider")
            if provider == "openrouter":
                return "https://openrouter.ai/api/v1"
            if provider == "ollama":
                return "http://host.docker.internal:11434/v1"
            if provider == "lmstudio":
                return "http://host.docker.internal:1234/v1"
            if provider == "custom":
                raise ValueError("Для пользовательского провайдера укажите API-адрес")
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Адрес должен начинаться с http:// или https://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Адрес не должен содержать логин, пароль, параметры или фрагмент")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Порт в API-адресе указан некорректно") from exc
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def trim_api_key(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

def _settings_out(settings: agent.ModelSettings) -> SettingsOut:
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url or "",
        "api_key_configured": bool(settings.api_key),
        "context_window_tokens": settings.context_window_tokens,
    }


def _chat_out(chat: models.ChatSummary) -> ChatOut:
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
    }


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _provider_error_message(exc: Exception) -> str:
    if getattr(exc, "status_code", None) == 429:
        return (
            "Провайдер ограничил запросы (HTTP 429). Проверьте квоту, баланс "
            "и доступность выбранной модели."
        )
    return str(exc)[:500]


# -------------------------------------------------------------------
# Маршруты
# -------------------------------------------------------------------


@app.get("/api/health")
async def health() -> HealthOut:
    settings = agent.current_model_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "provider": settings.provider,
        "docs_root": DOCS_ROOT.name + "/",
        "context_token_limit": settings.context_window_tokens,
    }


@app.get("/api/settings")
async def get_settings() -> SettingsOut:
    return _settings_out(agent.current_model_settings())


@app.put("/api/settings")
async def update_settings(body: ModelSettingsIn) -> SettingsOut:
    global _model_health_cache, _model_health_checked_at
    current = agent.current_model_settings()
    if body.clear_api_key and body.api_key:
        raise HTTPException(
            status_code=400, detail="Нельзя одновременно заменить и удалить API-ключ"
        )
    api_key = (
        ""
        if body.clear_api_key
        else body.api_key
        if body.api_key
        else current.api_key
    )
    settings = agent.ModelSettings(
        provider=body.provider,
        model=body.model,
        api_key=api_key,
        base_url=body.base_url,
        context_window_tokens=body.context_window_tokens,
    )
    async with _model_health_lock:
        await dbase.save_model_settings(
            settings.provider,
            settings.model,
            settings.api_key,
            settings.base_url,
            settings.context_window_tokens,
        )
        agent.configure_model(settings)
        _model_health_cache = None
        _model_health_checked_at = 0.0
    return _settings_out(settings)


@app.get("/api/health/model")
async def model_health() -> ModelHealthOut:
    global _model_health_cache, _model_health_checked_at
    async with _model_health_lock:
        settings = agent.current_model_settings()
        if (
            _model_health_cache is not None
            and time.monotonic() - _model_health_checked_at < MODEL_HEALTH_CACHE_TTL
        ):
            return _model_health_cache

        try:
            responds = await agent.probe_model()
        except APIError as exc:
            logger.warning("Model health probe failed: %s", exc)
            result: ModelHealthOut = {
                "status": "error",
                "model": settings.model,
                "detail": _provider_error_message(exc),
            }
        else:
            result = (
                {"status": "ok", "model": settings.model, "detail": "Модель отвечает"}
                if responds
                else {
                    "status": "error",
                    "model": settings.model,
                    "detail": "Модель вернула пустой ответ",
                }
            )
        _model_health_cache = result
        _model_health_checked_at = time.monotonic()
        return result


@app.get("/api/chats")
async def list_chats() -> list[ChatOut]:
    return [_chat_out(c) for c in await dbase.list_chats()]


@app.post("/api/chats")
async def create_chat(body: ChatIn) -> ChatOut:
    chat_id = await dbase.create_chat(title=body.title.strip() or "Новый чат")
    chat = await dbase.get_chat(chat_id)
    if chat is None:
        raise RuntimeError(f"created chat {chat_id} could not be loaded")
    return _chat_out(chat)


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int) -> dict[str, bool]:
    await dbase.delete_chat(chat_id)
    return {"ok": True}


@app.get("/api/chats/{chat_id}/messages")
async def get_messages(chat_id: int) -> ChatMessagesOut:
    chat = await dbase.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return {
        "chat": _chat_out(chat),
        "messages": await dbase.get_messages(chat_id),
    }


@app.post("/api/chats/{chat_id}/messages")
async def post_message(chat_id: int, body: MessageIn) -> StreamingResponse:
    """Отправить сообщение пользователя в чат; ответ агента приходит потоком SSE."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    chat = await dbase.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    # Сохраняем сообщение пользователя и задаём заголовок чата по первому сообщению.
    await dbase.add_message(chat_id, "user", content)
    if chat["title"] == "Новый чат":
        await dbase.rename_chat(chat_id, content[:60])
        chat["title"] = content[:60]

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start", "chat": _chat_out(chat)})
        final_text = ""
        history_json = chat.get("history_json", "")
        try:
            async for event in agent.run_pipeline(content, history_json):
                if event["type"] == "final":
                    text = event.get("text")
                    history = event.get("history_json")
                    if not isinstance(text, str) or not isinstance(history, str):
                        raise RuntimeError("pipeline returned an invalid final event")
                    final_text = text
                    history_json = history
                    continue
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 — наружу клиенту только краткость
            yield _sse({"type": "error", "message": _provider_error_message(exc)})
            return
        if final_text:
            await dbase.add_message(chat_id, "assistant", final_text)
            await dbase.set_history(chat_id, json.loads(history_json))
        yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
