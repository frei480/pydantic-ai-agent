"""Аутентификация: режимы входа, сессии пользователей и зависимости доступа.

Режимы (config.AUTH_MODE_SETTING):
- ``kerberos`` — прод: вход по доменному билету (SPNEGO), keytab обязателен;
- ``off`` — дев/тесты: псевдопользователь ``dev`` с правами админа;
- ``auto`` — kerberos при доступном keytab, иначе off.

Импорты spnego/gssapi — только лениво, внутри kerberos-кода: на Windows-машине
разработки gssapi не устанавливается.
"""
import hashlib
import hmac
import logging
import os
import secrets
import time

from fastapi import Header, HTTPException, Request, Response

from . import config

logger = logging.getLogger(__name__)

# Итоговый режим ("kerberos" | "off"); выставляется init_auth() при старте.
AUTH_MODE = "off"

ADMIN_SESSION_MAX_AGE = 8 * 60 * 60
ADMIN_COOKIE_NAME = "docs_ai_admin"


def _admin_password() -> str:
    # Лениво из main: тесты патчат main.ADMIN_PASSWORD.
    from . import main

    return main.ADMIN_PASSWORD


def is_admin_login(login: str) -> bool:
    return login.lower() in config.ADMIN_USERS


# ---- ключ подписи пользовательских сессий (app_meta) ----


async def session_secret(dbase) -> str:
    """Get-or-create секрет подписи сессий; переживает рестарты в БД."""
    value = await dbase.get_meta("session_secret")
    if value:
        return value
    value = secrets.token_hex(32)
    await dbase.set_meta("session_secret", value)
    return value


def _user_session_signature(login: str, expires_at: int, secret: str) -> str:
    message = f"user-session-v1:{login}:{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sign_user_session(login: str, expires_at: int, secret: str) -> str:
    return f"{login}.{expires_at}.{_user_session_signature(login, expires_at, secret)}"


def read_user_session(token: str, secret: str) -> str | None:
    """Логин валидной сессии или None (просрочена, подделана, мусор)."""
    try:
        login, expires_text, signature = token.rsplit(".", 2)
        expires_at = int(expires_text)
    except (AttributeError, ValueError):
        return None
    if not login or expires_at <= int(time.time()):
        return None
    expected = _user_session_signature(login, expires_at, secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return login


async def init_auth(dbase) -> None:
    """Вычислить режим аутентификации и подготовить секрет сессий.

    Вызывается из lifespan после dbase.connect(). В режиме kerberos
    недоступный keytab — ошибка запуска (fail-fast), а не тихое отключение.
    """
    global AUTH_MODE
    keytab = config.KRB5_KEYTAB
    keytab_ok = bool(keytab) and os.path.isfile(keytab) and os.access(keytab, os.R_OK)
    if config.AUTH_MODE_SETTING == "kerberos":
        if not keytab_ok:
            raise RuntimeError(
                "AUTH_MODE=kerberos: keytab недоступен или нечитаем: "
                f"{keytab or 'KRB5_KTNAME не задан'}"
            )
        AUTH_MODE = "kerberos"
    elif config.AUTH_MODE_SETTING == "auto":
        AUTH_MODE = "kerberos" if keytab_ok else "off"
    else:
        AUTH_MODE = "off"
    await session_secret(dbase)
    if AUTH_MODE == "kerberos":
        logger.info(
            "Аутентификация: Kerberos SSO; keytab=%s; principal=%s",
            keytab,
            config.KRB5_PRINCIPAL or "(первый из keytab)",
        )
    else:
        logger.warning(
            "Аутентификация ВЫКЛЮЧЕНА (режим off): приложение открыто без входа"
        )


# ---- SPNEGO-акцептор (только kerberos-режим) ----


class NegotiateError(Exception):
    """Билет не принят; детали — в reason и логе, клиенту — краткость."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def accept_negotiate_token(header_value: str) -> tuple[str, str]:
    """Проверить Negotiate-токен из Authorization; вернуть (login, upn)."""
    import base64
    import spnego  # лениво: только kerberos-режим, в образе/проде

    scheme, _, token_text = header_value.strip().partition(" ")
    if scheme.lower() != "negotiate" or not token_text:
        raise NegotiateError("ожидался заголовок Authorization: Negotiate")
    try:
        in_token = base64.b64decode(token_text)
    except ValueError as exc:
        raise NegotiateError("токен не является base64") from exc
    try:
        # Акцептор: ключ из keytab (env KRB5_KTNAME), principal при
        # KRB5_PRINCIPAL передаётся как spn, иначе берётся из keytab.
        options = []
        kwargs = {}
        if config.KRB5_PRINCIPAL:
            kwargs["spn"] = config.KRB5_PRINCIPAL
        ctx = spnego.server(options=options, **kwargs)
        ctx.step(in_token)
        if not ctx.complete:
            raise NegotiateError("потребовалось продолжение SPNEGO (не поддерживается)")
        upn = ctx.username  # 'IVANOV@CORP.LOCAL'
    except NegotiateError:
        raise
    except Exception as exc:  # спека: детали в лог, клиенту — краткость
        logger.warning("Negotiate отклонён: %s", exc)
        raise NegotiateError("билет не принят") from exc
    login = upn.split("@", 1)[0].lower()
    return login, upn


# ---- зависимости доступа ----


async def require_user(request: Request, response: Response) -> str:
    """Логин вошедшего пользователя; в off-режиме — псевдопользователь dev."""
    response.headers["Cache-Control"] = "no-store"
    if AUTH_MODE != "kerberos":
        return "dev"
    from . import main

    token = request.cookies.get(config.USER_COOKIE_NAME)
    if token:
        secret = await session_secret(main.dbase)
        login = read_user_session(token, secret)
        if login is not None:
            return login
    raise HTTPException(status_code=401, detail="Требуется вход")


async def require_admin_user(request: Request, response: Response) -> str:
    """Гейт настроек модели: вошедший администратор из ADMIN_USERS."""
    login = await require_user(request, response)
    if AUTH_MODE != "kerberos" or is_admin_login(login):
        # off-режим: псевдопользователь dev — всегда админ
        return login
    raise HTTPException(status_code=403, detail="Требуются права администратора")


# ---- админская парольная сессия (перенос из main.py) + SSO-ветка ----


def _admin_session_token(expires_at: int) -> str:
    message = f"admin-session-v1:{expires_at}".encode()
    signature = hmac.new(
        _admin_password().encode(), message, hashlib.sha256
    ).hexdigest()
    return f"{expires_at}.{signature}"


def _valid_admin_session(token: str | None) -> bool:
    password = _admin_password()
    if not password or len(password) < 16 or not token:
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


async def require_admin(
    request: Request,
    response: Response,
    x_admin_request: str | None = Header(default=None),
) -> None:
    """Гейт /api/admin/**: парольная cookie, либо SSO-сессия админа (kerberos).

    При незаданном ADMIN_PASSWORD — 401 (503 остаётся только в POST /api/admin/login).
    """
    response.headers["Cache-Control"] = "no-store"
    authorized = _valid_admin_session(request.cookies.get(ADMIN_COOKIE_NAME))
    if not authorized and AUTH_MODE == "kerberos":
        token = request.cookies.get(config.USER_COOKIE_NAME)
        login = None
        if token:
            from . import main

            secret = await session_secret(main.dbase)
            login = read_user_session(token, secret)
        authorized = login is not None and is_admin_login(login)
    if not authorized:
        raise HTTPException(status_code=401, detail="Требуется вход администратора")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and x_admin_request != "1":
        raise HTTPException(status_code=403, detail="Недопустимый запрос администратора")
