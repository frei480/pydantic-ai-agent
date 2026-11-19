"""Проверки режимов аутентификации, сессий пользователей и зависимостей."""
import asyncio
import os
import sys
import tempfile
import time

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import config  # noqa: E402
from app.db import Database  # noqa: E402


def check_session_token_roundtrip():
    from app import auth

    secret = "s" * 64
    token = auth.sign_user_session("ivanov", int(time.time()) + 3600, secret)
    assert auth.read_user_session(token, secret) == "ivanov"

    # просроченная сессия
    expired = auth.sign_user_session("ivanov", int(time.time()) - 1, secret)
    assert auth.read_user_session(expired, secret) is None

    # изменённая подпись (подмена последнего символа подписи)
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert auth.read_user_session(tampered, secret) is None

    # подпись чужим секретом
    assert auth.read_user_session(token, "x" * 64) is None

    # мусорный токен
    assert auth.read_user_session("garbage", secret) is None
    assert auth.read_user_session("a.b.c.d", secret) is None


async def check_init_auth_modes():
    from app import auth

    original_setting = config.AUTH_MODE_SETTING
    original_keytab = config.KRB5_KEYTAB
    original_mode = auth.AUTH_MODE
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "auth.db"))
        await database.connect()
        try:
            # kerberos + несуществующий keytab: отказ запуска (fail-fast)
            config.AUTH_MODE_SETTING = "kerberos"
            config.KRB5_KEYTAB = os.path.join(directory, "missing.keytab")
            try:
                await auth.init_auth(database)
            except RuntimeError:
                pass
            else:
                raise AssertionError("ожидался RuntimeError при недоступном keytab")

            # явное выключение
            config.AUTH_MODE_SETTING = "off"
            config.KRB5_KEYTAB = ""
            await auth.init_auth(database)
            assert auth.AUTH_MODE == "off"

            # auto без keytab: тихо off
            config.AUTH_MODE_SETTING = "auto"
            await auth.init_auth(database)
            assert auth.AUTH_MODE == "off"

            # auto с существующим keytab: kerberos
            keytab = os.path.join(directory, "docs.keytab")
            with open(keytab, "wb") as handle:
                handle.write(b"keytab-bytes")
            config.KRB5_KEYTAB = keytab
            await auth.init_auth(database)
            assert auth.AUTH_MODE == "kerberos"

            # секрет сессии: создаётся при отсутствии и стабилен
            first = await auth.session_secret(database)
            assert first, "секрет не создан"
            assert len(first) >= 32
            assert await auth.session_secret(database) == first
            assert await database.get_meta("session_secret") == first
        finally:
            config.AUTH_MODE_SETTING = original_setting
            config.KRB5_KEYTAB = original_keytab
            auth.AUTH_MODE = original_mode
            await database.close()


class _StubResponse:
    def __init__(self):
        self.headers: dict[str, str] = {}


async def check_require_user_off():
    from app import auth

    original_mode = auth.AUTH_MODE
    try:
        auth.AUTH_MODE = "off"
        response = _StubResponse()
        login = await auth.require_user(request=None, response=response)
        assert login == "dev"
        assert response.headers["Cache-Control"] == "no-store"

        # off-режим: псевдопользователь проходит и админский гейт
        assert await auth.require_admin_user(request=None, response=_StubResponse())
    finally:
        auth.AUTH_MODE = original_mode


async def check_whoami_flow():
    from app import auth, main

    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    original_accept = auth.accept_negotiate_token
    original_admins = config.ADMIN_USERS

    def fake_accept(header_value: str):
        assert "Negotiate" in header_value
        return "ivanov", "IVANOV@CORP.LOCAL"

    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "whoami.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        auth.accept_negotiate_token = fake_accept
        config.ADMIN_USERS = set()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                # без cookie и без Authorization: 401 с предложением Negotiate
                response = await client.get("/api/auth/whoami")
                assert response.status_code == 401, response.text
                assert (
                    response.headers.get("www-authenticate", "").lower() == "negotiate"
                ), response.headers

                # вход с Negotiate-заголовком → сессия в cookie
                response = await client.get(
                    "/api/auth/whoami",
                    headers={"Authorization": "Negotiate dGVzdA=="},
                )
                assert response.status_code == 200, response.text
                assert response.json() == {"login": "ivanov", "is_admin": False}
                set_cookie = response.headers.get("set-cookie", "")
                assert "docs_ai_session=" in set_cookie
                assert "Path=/api" in set_cookie
                assert "httponly" in set_cookie.lower()
                assert "samesite=strict" in set_cookie.lower()

                # повторный запрос с cookie, уже без Authorization
                token = response.cookies.get("docs_ai_session")
                assert token
                client.cookies.set("docs_ai_session", token)
                response = await client.get("/api/auth/whoami")
                assert response.status_code == 200, response.text
                assert response.json()["login"] == "ivanov"

                # пользователь создан в БД с UPN из билета
                user_id = await database.get_or_create_user("ivanov")
                cur = await database.conn.execute(
                    "SELECT login, upn FROM users WHERE id = ?", (user_id,)
                )
                row = await cur.fetchone()
                assert row["login"] == "ivanov"
                assert row["upn"] == "IVANOV@CORP.LOCAL"
        finally:
            config.ADMIN_USERS = original_admins
            auth.accept_negotiate_token = original_accept
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_whoami_bad_token():
    from app import auth, main

    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    original_accept = auth.accept_negotiate_token

    def bad_accept(header_value: str):
        raise auth.NegotiateError("билет не принят")

    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "bad-token.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        auth.accept_negotiate_token = bad_accept
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/auth/whoami",
                    headers={"Authorization": "Negotiate bWFndWtB"},
                )
                assert response.status_code == 401, response.text
                # процесс жив: следующий запрос тоже обрабатывается
                response = await client.get("/api/auth/whoami")
                assert response.status_code == 401, response.text
        finally:
            auth.accept_negotiate_token = original_accept
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_logout():
    from app import auth, main

    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE

    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "logout.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                client.cookies.set("docs_ai_session", "some-session-value")
                response = await client.post("/api/auth/logout")
                assert response.status_code == 200, response.text
                assert response.json() == {"ok": True}
                set_cookie = response.headers.get("set-cookie", "").lower()
                assert "docs_ai_session=" in set_cookie
                assert '""' in set_cookie or "max-age=0" in set_cookie
        finally:
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


check_session_token_roundtrip()
asyncio.run(check_init_auth_modes())
asyncio.run(check_require_user_off())
asyncio.run(check_whoami_flow())
asyncio.run(check_whoami_bad_token())
asyncio.run(check_logout())
print("AUTH-OK")
