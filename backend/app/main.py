import asyncio
import json
import logging
import time

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel

from . import agent, db
from .config import CONTEXT_TOKEN_LIMIT, DB_PATH, DOCS_ROOT, MODEL_NAME

dbase = db.Database(DB_PATH)
logger = logging.getLogger(__name__)
MODEL_HEALTH_CACHE_TTL = 60 * 60
_model_health_cache: dict[str, Any] | None = None
_model_health_checked_at = 0.0
_model_health_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await dbase.connect()
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


def _chat_out(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
    }


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _provider_error_message(exc: Exception) -> str:
    if getattr(exc, "status_code", None) == 429:
        return (
            "Провайдер ограничил запросы (HTTP 429). Если исчерпана дневная квота "
            "OpenRouter Free, смените AI_MODEL в .env на модель с доступной квотой "
            "или пополните баланс OpenRouter, затем перезапустите backend."
        )
    return str(exc)[:500]


# -------------------------------------------------------------------
# Маршруты
# -------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "docs_root": DOCS_ROOT.name + "/",
        "context_token_limit": CONTEXT_TOKEN_LIMIT,
    }


@app.get("/api/health/model")
async def model_health() -> dict[str, Any]:
    global _model_health_cache, _model_health_checked_at
    async with _model_health_lock:
        if (
            _model_health_cache is not None
            and time.monotonic() - _model_health_checked_at < MODEL_HEALTH_CACHE_TTL
        ):
            return _model_health_cache

        try:
            responds = await agent.probe_model()
        except APIError as exc:
            logger.warning("Model health probe failed: %s", exc)
            result = {
                "status": "error",
                "model": MODEL_NAME,
                "detail": _provider_error_message(exc),
            }
        else:
            result = (
                {"status": "ok", "model": MODEL_NAME, "detail": "Модель отвечает"}
                if responds
                else {
                    "status": "error",
                    "model": MODEL_NAME,
                    "detail": "Модель вернула пустой ответ",
                }
            )
        _model_health_cache = result
        _model_health_checked_at = time.monotonic()
        return result


@app.get("/api/chats")
async def list_chats():
    return [_chat_out(c) for c in await dbase.list_chats()]


@app.post("/api/chats")
async def create_chat(body: ChatIn):
    chat_id = await dbase.create_chat(title=body.title.strip() or "Новый чат")
    chat = await dbase.get_chat(chat_id)
    return _chat_out(chat)


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int):
    await dbase.delete_chat(chat_id)
    return {"ok": True}


@app.get("/api/chats/{chat_id}/messages")
async def get_messages(chat_id: int):
    chat = await dbase.get_chat(chat_id)
    if not chat:
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
    if not chat:
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
                    final_text = event["text"]
                    history_json = event["history_json"]
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
