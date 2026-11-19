"""Проверки режимов аутентификации, сессий пользователей и зависимостей."""
import asyncio
import os
import sys
import tempfile
import time

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


check_session_token_roundtrip()
asyncio.run(check_init_auth_modes())
asyncio.run(check_require_user_off())
print("AUTH-OK")
