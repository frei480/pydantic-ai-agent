import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from openai import APIError

from . import agent, db
from .admin_content import AdminContentStore, skill_metadata
from .config import (
    ADMIN_PASSWORD,
    DB_PATH,
    DOCS_ROOT,
)
from .doc_catalog import preload_doc_catalogs, search_indexed_pages
from .model import (
    AdminLoginIn,
    AdminSessionOut,
    AgentAdminConfig,
    ChatIn,
    ChatMessagesOut,
    ChatOut,
    ChatSummary,
    HealthOut,
    IndexedPageSearchIn,
    IndexedPageSearchOut,
    IndexedPageSearchResultOut,
    MessageIn,
    ModelHealthOut,
    ModelSettingsIn,
    SkillContentIn,
    SkillOut,
    SkillSummaryOut,
    SettingsOut,
)

dbase = db.Database(str(DB_PATH))
admin_content = AdminContentStore(DB_PATH.parent)
logger = logging.getLogger(__name__)
MODEL_HEALTH_CACHE_TTL = 60 * 60
ADMIN_SESSION_MAX_AGE = 8 * 60 * 60
ADMIN_COOKIE_NAME = "docs_ai_admin"
_admin_config_lock = asyncio.Lock()
_admin_login_lock = threading.Lock()
_admin_login_failures: dict[str, tuple[int, float]] = {}


_model_health_cache: ModelHealthOut | None = None
_model_health_checked_at = 0.0
_model_health_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog_counts = await asyncio.to_thread(preload_doc_catalogs, DOCS_ROOT)
    logger.info("Preloaded documentation catalogs: %s", catalog_counts)
    admin_config = await asyncio.to_thread(
        admin_content.initialize,
        agent.default_agent_admin_config(),
        Path(__file__).parent / "skills",
    )
    agent.configure_agent_admin_content(admin_config, admin_content.skills_root)
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
            defaults.max_agent_response_tokens,
            defaults.max_critic_response_tokens,
        )
    else:
        agent.configure_model(agent.ModelSettings(**settings))
    yield
    await dbase.close()


app = FastAPI(title="Docs AI Agent", lifespan=lifespan)


def _admin_session_token(expires_at: int) -> str:
    message = f"admin-session-v1:{expires_at}".encode()
    signature = hmac.new(
        ADMIN_PASSWORD.encode(), message, hashlib.sha256
    ).hexdigest()
    return f"{expires_at}.{signature}"


def _valid_admin_session(token: str | None) -> bool:
    if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 16 or not token:
        return False
    try:
        expires_text, signature = token.split(".", 1)
        expires_at = int(expires_text)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if expires_at <= now or expires_at > now + ADMIN_SESSION_MAX_AGE:
        return False
    expected = _admin_session_token(expires_at).split(".", 1)[1]
    return hmac.compare_digest(signature, expected)


def require_admin(
    request: Request,
    response: Response,
    x_admin_request: str | None = Header(default=None),
) -> None:
    response.headers["Cache-Control"] = "no-store"
    if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 16:
        raise HTTPException(
            status_code=503,
            detail="Задайте ADMIN_PASSWORD длиной не менее 16 символов на сервере",
        )
    if not _valid_admin_session(request.cookies.get(ADMIN_COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="Требуется вход администратора")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and x_admin_request != "1":
        raise HTTPException(status_code=403, detail="Недопустимый запрос администратора")


def _skill_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def _settings_out(settings: agent.ModelSettings) -> SettingsOut:
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url or "",
        "api_key_configured": bool(settings.api_key),
        "context_window_tokens": settings.context_window_tokens,
        "max_agent_response_tokens": settings.max_agent_response_tokens,
        "max_critic_response_tokens": settings.max_critic_response_tokens,
    }


def _chat_out(chat: ChatSummary) -> ChatOut:
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


@app.post("/api/admin/login", response_model=AdminSessionOut)
async def admin_login(
    body: AdminLoginIn,
    request: Request,
    response: Response,
) -> AdminSessionOut:
    if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 16:
        raise HTTPException(
            status_code=503,
            detail="Задайте ADMIN_PASSWORD длиной не менее 16 символов на сервере",
        )
    client_id = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _admin_login_lock:
        failures, blocked_until = _admin_login_failures.get(client_id, (0, 0.0))
        if blocked_until > now:
            raise HTTPException(
                status_code=429,
                detail="Слишком много попыток входа. Попробуйте позже.",
            )
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        with _admin_login_lock:
            failures, _ = _admin_login_failures.get(client_id, (0, 0.0))
            failures += 1
            blocked_until = now + 300 if failures >= 5 else 0.0
            _admin_login_failures[client_id] = (failures, blocked_until)
        raise HTTPException(status_code=401, detail="Неверный пароль")
    with _admin_login_lock:
        _admin_login_failures.pop(client_id, None)

    expires_at = int(time.time()) + ADMIN_SESSION_MAX_AGE
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        _admin_session_token(expires_at),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/admin",
    )
    response.headers["Cache-Control"] = "no-store"
    return AdminSessionOut()


@app.get("/api/admin/session", response_model=AdminSessionOut)
async def admin_session(
    _: None = Depends(require_admin),
) -> AdminSessionOut:
    return AdminSessionOut()


@app.post("/api/admin/logout", response_model=AdminSessionOut)
async def admin_logout(
    request: Request,
    response: Response,
    _: None = Depends(require_admin),
) -> AdminSessionOut:
    response.delete_cookie(
        ADMIN_COOKIE_NAME,
        path="/api/admin",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return AdminSessionOut()


@app.get("/api/admin/config", response_model=AgentAdminConfig)
async def get_admin_config(
    _: None = Depends(require_admin),
) -> AgentAdminConfig:
    return agent.current_agent_admin_config()


@app.put("/api/admin/config", response_model=AgentAdminConfig)
async def update_admin_config(
    body: AgentAdminConfig,
    _: None = Depends(require_admin),
) -> AgentAdminConfig:
    async with _admin_config_lock:
        await asyncio.to_thread(admin_content.save_config, body)
        agent.configure_agent_admin_content(body, admin_content.skills_root)
    return body


@app.get("/api/admin/skills", response_model=list[SkillSummaryOut])
async def list_admin_skills(
    _: None = Depends(require_admin),
) -> list[SkillSummaryOut]:
    skills = await asyncio.to_thread(admin_content.list_skills)
    return [SkillSummaryOut(**skill) for skill in skills]


@app.get("/api/admin/skills/{skill_id}", response_model=SkillOut)
async def get_admin_skill(
    skill_id: str,
    _: None = Depends(require_admin),
) -> SkillOut:
    try:
        content = await asyncio.to_thread(admin_content.get_skill, skill_id)
        name, description = skill_metadata(content)
        return SkillOut(name=name, description=description, content=content)
    except (FileNotFoundError, ValueError) as exc:
        raise _skill_error(exc) from exc


@app.post(
    "/api/admin/skills/{skill_id}",
    response_model=SkillOut,
    status_code=201,
)
async def create_admin_skill(
    skill_id: str,
    body: SkillContentIn,
    _: None = Depends(require_admin),
) -> SkillOut:
    try:
        await asyncio.to_thread(admin_content.create_skill, skill_id, body.content)
        name, description = skill_metadata(body.content)
        return SkillOut(name=name, description=description, content=body.content)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise _skill_error(exc) from exc


@app.put("/api/admin/skills/{skill_id}", response_model=SkillOut)
async def update_admin_skill(
    skill_id: str,
    body: SkillContentIn,
    _: None = Depends(require_admin),
) -> SkillOut:
    try:
        await asyncio.to_thread(admin_content.update_skill, skill_id, body.content)
        name, description = skill_metadata(body.content)
        return SkillOut(name=name, description=description, content=body.content)
    except (FileNotFoundError, ValueError) as exc:
        raise _skill_error(exc) from exc


@app.delete("/api/admin/skills/{skill_id}", response_model=AdminSessionOut)
async def delete_admin_skill(
    skill_id: str,
    _: None = Depends(require_admin),
) -> AdminSessionOut:
    try:
        await asyncio.to_thread(admin_content.delete_skill, skill_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _skill_error(exc) from exc
    return AdminSessionOut()


@app.post(
    "/api/tools/search-indexed-pages",
    response_model=IndexedPageSearchOut,
)
async def search_indexed_pages_endpoint(
    body: IndexedPageSearchIn,
) -> IndexedPageSearchOut:
    """Run the same indexed-page search used by the agent, without an LLM call."""
    started_at = time.perf_counter()
    results, indexed_pages = await asyncio.to_thread(
        search_indexed_pages,
        body.query,
        body.product,
        DOCS_ROOT,
        body.limit,
    )
    return IndexedPageSearchOut(
        query=body.query,
        product=body.product,
        indexed_pages=indexed_pages,
        result_count=len(results),
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        results=[
            IndexedPageSearchResultOut(
                title=result.page.title,
                path=result.page.path,
                breadcrumb=result.page.breadcrumb,
                section=result.section,
                keywords=list(result.page.keywords),
                intro=result.page.intro,
                excerpt=result.excerpt,
                excerpt_start_line=result.excerpt_start_line,
                excerpt_end_line=result.excerpt_end_line,
            )
            for result in results
        ],
    )


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
        max_agent_response_tokens=body.max_agent_response_tokens,
        max_critic_response_tokens=body.max_critic_response_tokens,
    )
    async with _model_health_lock:
        await dbase.save_model_settings(
            settings.provider,
            settings.model,
            settings.api_key,
            settings.base_url,
            settings.context_window_tokens,
            settings.max_agent_response_tokens,
            settings.max_critic_response_tokens,
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
