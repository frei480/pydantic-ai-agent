import asyncio
import hmac
import json
import logging
import threading
import time

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import StreamingResponse
from openai import APIError

from . import agent, auth, db, llm_errors, runs
from .admin_content import AdminContentStore, skill_metadata
from .auth import (
    ADMIN_COOKIE_NAME,
    ADMIN_SESSION_MAX_AGE,
    _admin_session_token,
    require_admin,
)
from .config import (
    ADMIN_PASSWORD,
    DB_PATH,
    DOCS_ROOT,
    USER_COOKIE_NAME,
    USER_SESSION_MAX_AGE,
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
    RunStartedOut,
    SkillContentIn,
    SkillOut,
    SkillSummaryOut,
    SettingsOut,
    WhoamiOut,
)

dbase = db.Database(str(DB_PATH))
runs_registry = runs.RunRegistry()
admin_content = AdminContentStore(DB_PATH.parent)
logger = logging.getLogger(__name__)
MODEL_HEALTH_CACHE_TTL = 60 * 60
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
    await auth.init_auth(dbase)
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


app = FastAPI(
    title="Docs AI Agent",
    lifespan=lifespan,
    # Документация работает в изолированной сети: HTML отдают кастомные
    # маршруты ниже, статику Swagger UI/ReDoc раздаёт nginx фронтенда
    # (frontend/public/static/docs-assets). Встроенные маршруты отключены:
    # они регистрируются раньше кастомных и тянут ассеты с CDN.
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
)


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,  # type: ignore[arg-type]
        title=app.title + " - Swagger UI",
        oauth2_redirect_url="/docs/oauth2-redirect",
        swagger_js_url="/static/docs-assets/js/swagger-ui-bundle.js",
        swagger_css_url="/static/docs-assets/css/swagger-ui.css",
        swagger_favicon_url="/static/docs-assets/favicon-32x32.png",
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,  # type: ignore[arg-type]
        title=app.title + " - ReDoc",
        redoc_js_url="/static/docs-assets/js/redoc.standalone.js",
        redoc_favicon_url="/static/docs-assets/favicon-32x32.png",
        with_google_fonts=False,
    )


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
        "active_run": runs_registry.active_run_id(chat["id"]),
    }


async def _current_user_id(login: str) -> int | None:
    """user_id текущего пользователя; в off-режиме — None (псевдопользователь)."""
    if auth.AUTH_MODE != "kerberos":
        return None
    return await dbase.get_or_create_user(login)


async def chat_for(owner_login: str, chat_id: int) -> Chat:
    """Чат для владельца или админа (наследие); иначе 404 без раскрытия."""
    chat = await dbase.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if auth.AUTH_MODE != "kerberos":
        return chat
    user_id = await dbase.get_or_create_user(owner_login)
    is_admin = auth.is_admin_login(owner_login)
    if chat["user_id"] == user_id or (chat["user_id"] is None and is_admin):
        return chat
    raise HTTPException(status_code=404, detail="chat not found")


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


@app.get("/api/auth/whoami", response_model=WhoamiOut)
async def whoami(request: Request, response: Response) -> WhoamiOut:
    """Личность вошедшего; вход — SPNEGO-билет домена в Authorization."""
    if auth.AUTH_MODE != "kerberos":
        return WhoamiOut(login="dev", is_admin=True)

    token = request.cookies.get(USER_COOKIE_NAME)
    if token:
        secret = await auth.session_secret(dbase)
        login = auth.read_user_session(token, secret)
        if login is not None:
            return WhoamiOut(login=login, is_admin=auth.is_admin_login(login))

    authorization = request.headers.get("authorization")
    if authorization:
        try:
            login, upn = auth.accept_negotiate_token(authorization)
        except auth.NegotiateError:
            raise HTTPException(status_code=401, detail="Билет не принят")
        user_id = await dbase.get_or_create_user(login, upn)
        await dbase.touch_user(user_id)
        secret = await auth.session_secret(dbase)
        expires_at = int(time.time()) + USER_SESSION_MAX_AGE
        response.set_cookie(
            USER_COOKIE_NAME,
            auth.sign_user_session(login, expires_at, secret),
            max_age=USER_SESSION_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/api",
        )
        return WhoamiOut(login=login, is_admin=auth.is_admin_login(login))

    # Заголовок именно в исключении: FastAPI отбрасывает заголовки
    # инжектированного response при HTTPException.
    raise HTTPException(
        status_code=401,
        detail="Требуется вход",
        headers={"WWW-Authenticate": "Negotiate"},
    )


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    """Удалить cookie сессии; перевход произойдёт молча при следующем whoami."""
    response.delete_cookie(
        USER_COOKIE_NAME,
        path="/api",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"ok": True}


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
    _: str = Depends(auth.require_user),
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
async def get_settings(_: str = Depends(auth.require_user)) -> SettingsOut:
    return _settings_out(agent.current_model_settings())


@app.put("/api/settings")
async def update_settings(
    body: ModelSettingsIn, _: str = Depends(auth.require_admin_user)
) -> SettingsOut:
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
async def model_health(_: str = Depends(auth.require_user)) -> ModelHealthOut:
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
            llm_errors.log_llm_failure(exc, context={"endpoint": "/api/health/model"})
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
async def list_chats(_: str = Depends(auth.require_user)) -> list[ChatOut]:
    user_id = await _current_user_id(_)
    include_legacy = auth.AUTH_MODE != "kerberos" or auth.is_admin_login(_)
    return [
        _chat_out(c)
        for c in await dbase.list_chats(
            user_id=user_id, include_legacy=include_legacy
        )
    ]


@app.post("/api/chats")
async def create_chat(
    body: ChatIn, login: str = Depends(auth.require_user)
) -> ChatOut:
    user_id = await _current_user_id(login)
    chat_id = await dbase.create_chat(
        title=body.title.strip() or "Новый чат", user_id=user_id
    )
    chat = await dbase.get_chat(chat_id)
    if chat is None:
        raise RuntimeError(f"created chat {chat_id} could not be loaded")
    return _chat_out(chat)


@app.delete("/api/chats/{chat_id}")
async def delete_chat(
    chat_id: int, login: str = Depends(auth.require_user)
) -> dict[str, bool]:
    await chat_for(login, chat_id)
    await dbase.delete_chat(chat_id)
    return {"ok": True}


@app.get("/api/chats/{chat_id}/messages")
async def get_messages(
    chat_id: int, login: str = Depends(auth.require_user)
) -> ChatMessagesOut:
    chat = await chat_for(login, chat_id)
    return {
        "chat": _chat_out(chat),
        "messages": await dbase.get_messages(chat_id),
    }


async def _execute_run(
    run: runs.Run, chat_id: int, content: str, history_json: str
) -> None:
    """Фоновая задача запуска: пайплайн пишет события в run, ответ — в базу.

    Живёт независимо от соединений: обрыв подписки её не отменяет.
    """
    final_text = ""
    partial_text = ""
    # последняя фаза пайплайна — попадает в контекст записи об ошибке LLM
    current_phase = ""
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
            if event["type"] == "phase":
                current_phase = str(event.get("phase", ""))
            if event["type"] == "text":
                partial_text += str(event.get("text", ""))
            run.publish(event)
    except asyncio.CancelledError:
        if run.finishing:
            # отмена пришла из остановки сервера в окне записи — не спасаем
            raise
        run.finish("cancelled")
        return
    except Exception as exc:  # noqa: BLE001 — наружу клиенту только краткость
        # полный дамп ошибки и последнего запроса — в файл лога, клиенту — краткость
        llm_errors.log_llm_failure(
            exc, context={"chat_id": chat_id, "phase": current_phase}
        )
        brief = _provider_error_message(exc)
        saved = (
            f"{partial_text}\n\n**Ошибка:** {brief}"
            if partial_text
            else f"**Ошибка:** {brief}"
        )
        await dbase.add_message(chat_id, "assistant", saved)
        run.finish("error", message=brief)
        return
    # окно записи: отмена больше не действует (см. Run.begin_finish)
    run.begin_finish()
    if final_text:
        await dbase.add_message(chat_id, "assistant", final_text)
        await dbase.set_history(chat_id, json.loads(history_json))
    run.finish("done")


@app.post("/api/chats/{chat_id}/messages", status_code=202)
async def post_message(
    chat_id: int, body: MessageIn, login: str = Depends(auth.require_user)
) -> RunStartedOut:
    """Запустить обработку сообщения; события — догоняющим потоком GET runs."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    chat = await chat_for(login, chat_id)

    runs_registry.reap()
    try:
        run = runs_registry.register(chat_id)
    except runs.ChatBusyError:
        raise HTTPException(
            status_code=409, detail="Агент ещё обрабатывает предыдущее сообщение"
        ) from None

    # Сохраняем сообщение пользователя и задаём заголовок чата по первому сообщению.
    await dbase.add_message(chat_id, "user", content)
    if chat["title"] == "Новый чат":
        await dbase.rename_chat(chat_id, content[:60])
        chat["title"] = content[:60]

    run.task = asyncio.create_task(
        _execute_run(run, chat_id, content, chat.get("history_json", ""))
    )
    return RunStartedOut(run_id=run.id, chat=_chat_out(chat))


async def _run_sse(run: runs.Run, from_seq: int) -> AsyncIterator[str]:
    async for event in runs_registry.stream_events(run, from_seq):
        if event["type"] == "heartbeat":
            # комментарий-«сердцебиение»: nginx не закрывает соединение на паузе
            yield ": keep-alive\n\n"
        else:
            yield _sse(event)


@app.get("/api/chats/{chat_id}/runs/{run_id}/events")
async def get_run_events(
    chat_id: int,
    run_id: str,
    from_: int = Query(0, alias="from"),
    login: str = Depends(auth.require_user),
) -> StreamingResponse:
    """SSE-поток событий запуска после номера from: накопленные, потом новые."""
    await chat_for(login, chat_id)
    runs_registry.reap()
    run = runs_registry.get(run_id)
    if run is None or run.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="run not found")
    return StreamingResponse(
        _run_sse(run, max(from_, 0)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
