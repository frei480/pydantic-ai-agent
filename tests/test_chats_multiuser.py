"""Проверки многопользовательского гейтинга чатов и настроек."""
import asyncio
import os
import sys
import tempfile
import time

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import agent, auth, config, main  # noqa: E402
from app.db import Database  # noqa: E402


async def user_cookie(login: str) -> str:
    secret = await auth.session_secret(main.dbase)
    return auth.sign_user_session(login, int(time.time()) + 3600, secret)


SETTINGS_BODY = {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "context_window_tokens": 8192,
}


async def check_chat_isolation():
    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    original_admins = config.ADMIN_USERS
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "isolation.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        config.ADMIN_USERS = {"admin"}
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                # без сессии чаты недоступны
                response = await client.get("/api/chats")
                assert response.status_code == 401, response.text

                # alice создаёт чат
                client.cookies.set("docs_ai_session", await user_cookie("alice"))
                response = await client.post(
                    "/api/chats", json={"title": "чат alice"}
                )
                assert response.status_code == 200, response.text
                chat_id = response.json()["id"]

                response = await client.get("/api/chats")
                assert response.status_code == 200
                assert [chat["id"] for chat in response.json()] == [chat_id]

                # bob не видит чужой чат и не может его трогать
                client.cookies.set("docs_ai_session", await user_cookie("bob"))
                response = await client.get("/api/chats")
                assert response.status_code == 200
                assert response.json() == []

                response = await client.get(f"/api/chats/{chat_id}/messages")
                assert response.status_code == 404, response.text
                response = await client.post(
                    f"/api/chats/{chat_id}/messages", json={"content": "привет"}
                )
                assert response.status_code == 404, response.text
                response = await client.delete(f"/api/chats/{chat_id}")
                assert response.status_code == 404, response.text

                # bob создаёт свой чат и открывает его
                response = await client.post(
                    "/api/chats", json={"title": "чат bob"}
                )
                assert response.status_code == 200, response.text
                bob_chat = response.json()["id"]
                response = await client.get(f"/api/chats/{bob_chat}/messages")
                assert response.status_code == 200, response.text

                # чат alice не удалён (bob получал 404)
                response = await client.get(f"/api/chats/{chat_id}/messages")
                assert response.status_code == 404, response.text
                alice_still_there = await database.get_chat(chat_id)
                assert alice_still_there is not None
        finally:
            config.ADMIN_USERS = original_admins
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_admin_sees_legacy():
    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    original_admins = config.ADMIN_USERS
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "legacy.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        config.ADMIN_USERS = {"admin"}
        try:
            legacy_id = await database.create_chat("наследие")  # user_id IS NULL
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                # обычный пользователь наследие не видит
                client.cookies.set("docs_ai_session", await user_cookie("worker"))
                response = await client.get("/api/chats")
                assert response.status_code == 200
                assert response.json() == []
                response = await client.get(f"/api/chats/{legacy_id}/messages")
                assert response.status_code == 404, response.text

                # админ из ADMIN_USERS видит и открывает наследие
                client.cookies.set("docs_ai_session", await user_cookie("admin"))
                response = await client.get("/api/chats")
                assert response.status_code == 200
                assert [chat["id"] for chat in response.json()] == [legacy_id]
                response = await client.get(f"/api/chats/{legacy_id}/messages")
                assert response.status_code == 200, response.text
        finally:
            config.ADMIN_USERS = original_admins
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_settings_put_requires_admin():
    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    original_admins = config.ADMIN_USERS
    original_settings = agent.current_model_settings()
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "settings.db"))
        await database.connect()
        main.dbase = database
        try:
            auth.AUTH_MODE = "kerberos"
            config.ADMIN_USERS = {"admin"}
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.put("/api/settings", json=SETTINGS_BODY)
                assert response.status_code == 401, response.text

                client.cookies.set("docs_ai_session", await user_cookie("worker"))
                response = await client.put("/api/settings", json=SETTINGS_BODY)
                assert response.status_code == 403, response.text

                client.cookies.set("docs_ai_session", await user_cookie("admin"))
                response = await client.put("/api/settings", json=SETTINGS_BODY)
                assert response.status_code == 200, response.text

            # off-режим: без cookie поведение прежнее
            auth.AUTH_MODE = "off"
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.put("/api/settings", json=SETTINGS_BODY)
                assert response.status_code == 200, response.text
        finally:
            agent.configure_model(original_settings)
            config.ADMIN_USERS = original_admins
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_messages_require_session():
    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "session.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.get("/api/chats")
                assert response.status_code == 401, response.text
                # healthcheck Docker ходит без cookie — остаётся открытым
                response = await client.get("/api/health")
                assert response.status_code == 200, response.text
                # чтение настроек — только вошедшим (спека, «Права на маршрутах»)
                response = await client.get("/api/settings")
                assert response.status_code == 401, response.text
        finally:
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


async def check_search_tool_requires_user():
    original_dbase = main.dbase
    original_mode = auth.AUTH_MODE
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "search.db"))
        await database.connect()
        main.dbase = database
        auth.AUTH_MODE = "kerberos"
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/tools/search-indexed-pages", json={"query": "тест"}
                )
                assert response.status_code == 401, response.text
        finally:
            auth.AUTH_MODE = original_mode
            main.dbase = original_dbase
            await database.close()


asyncio.run(check_chat_isolation())
asyncio.run(check_admin_sees_legacy())
asyncio.run(check_settings_put_requires_admin())
asyncio.run(check_messages_require_session())
asyncio.run(check_search_tool_requires_user())
print("MULTIUSER-OK")
