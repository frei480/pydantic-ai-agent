"""Список моделей провайдера: GET …/models через OpenAI SDK и маршрут POST /api/settings/models."""
import asyncio
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import asynccontextmanager, contextmanager
from http.server import HTTPServer
from unittest.mock import patch

import openai
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mock_llm_server  # noqa: E402
from app import agent, auth, config, main  # noqa: E402
from app.db import Database  # noqa: E402

STORED_KEY = "sk-stored-test-key"


def closed_port() -> int:
    """Порт, который только что был свободен: на нём никто не слушает."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def mock_server():
    """Мок-сервер в потоке этого же процесса: (base_url, закрытый порт)."""
    server = HTTPServer(("127.0.0.1", 0), mock_llm_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", closed_port()
    finally:
        server.shutdown()
        server.server_close()


def custom_settings(base_url: str) -> agent.ModelSettings:
    return agent.ModelSettings(
        provider="custom", model="mock-model", api_key="", base_url=base_url
    )


def api_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


async def user_cookie(login: str) -> str:
    secret = await auth.session_secret(main.dbase)
    return auth.sign_user_session(login, int(time.time()) + 3600, secret)


@asynccontextmanager
async def stored_connection(base_url: str, stored_base_url: str | None = None):
    """Сохранённые настройки «custom + адрес + ключ STORED_KEY» во временной базе."""
    original_dbase = main.dbase
    original_settings = agent.current_model_settings()
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "models.db"))
        await database.connect()
        main.dbase = database
        await database.save_model_settings(
            "custom", "mock-model", STORED_KEY, stored_base_url or base_url, 120000
        )
        agent.configure_model(agent.ModelSettings(**await database.get_model_settings()))
        try:
            yield
        finally:
            agent.configure_model(original_settings)
            main.dbase = original_dbase
            await database.close()


async def check_list_models_sorted_unique_pages():
    # «Zeta» стоит после «mock-model»: регистр не влияет на порядок
    env = {"MOCK_MODELS": "Zeta, mock-model, Alpha,mock-model", "MOCK_MODELS_PAGE_SIZE": "2"}
    with mock_server() as (base_url, _), patch.dict(os.environ, env):
        models = await agent.list_models(custom_settings(base_url))
    assert models == ["Alpha", "mock-model", "Zeta"], models


async def check_list_models_skips_broken_items():
    # пустой список и записи без id — пустой или неполный результат, а не ошибка
    with mock_server() as (base_url, _):
        with patch.dict(os.environ, {"MOCK_MODELS": ""}):
            assert await agent.list_models(custom_settings(base_url)) == []
        with patch.dict(os.environ, {"MOCK_MODELS": "a,,b"}):
            assert await agent.list_models(custom_settings(base_url)) == ["a", "b"]


async def check_list_models_stops_on_broken_pagination():
    # провайдер игнорирует курсор и всегда отвечает has_more — запрос кончается по лимиту страниц
    env = {"MOCK_MODELS": "a,b", "MOCK_MODELS_PAGE_SIZE": "1", "MOCK_MODELS_IGNORE_AFTER": "1"}
    mock_llm_server.state["models_requests"] = 0
    with mock_server() as (base_url, _):
        with patch.dict(os.environ, env):
            with patch.object(agent, "MODELS_LIST_MAX_PAGES", 3):
                models = await agent.list_models(custom_settings(base_url))
    assert models == ["a"], models
    assert mock_llm_server.state["models_requests"] == 3


async def check_list_models_failures():
    with mock_server() as (base_url, closed):
        # сбойный статус — одно обращение, без повторов
        mock_llm_server.state["models_requests"] = 0
        with patch.dict(os.environ, {"MOCK_MODELS_STATUS": "503"}):
            try:
                await agent.list_models(custom_settings(base_url))
            except openai.APIStatusError as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("HTTP 503 не поднял APIStatusError")
        assert mock_llm_server.state["models_requests"] == 1

        # таймаут
        with patch.dict(os.environ, {"MOCK_MODELS_DELAY": "0.4"}):
            with patch.object(agent, "MODELS_LIST_TIMEOUT_SECONDS", 0.1):
                try:
                    await agent.list_models(custom_settings(base_url))
                except openai.APITimeoutError:
                    pass
                else:
                    raise AssertionError("таймаут не поднял APITimeoutError")

        # по адресу никто не слушает
        try:
            await agent.list_models(custom_settings(f"http://127.0.0.1:{closed}/v1"))
        except openai.APIConnectionError:
            pass
        else:
            raise AssertionError("закрытый порт не поднял APIConnectionError")


async def check_models_route_returns_sorted_ids():
    with mock_server() as (base_url, _):
        with patch.dict(os.environ, {"MOCK_MODELS": "zeta,Alpha,alpha"}):
            async with stored_connection(base_url):
                body = {"provider": "custom", "base_url": base_url, "api_key": "sk-typed"}
                async with api_client() as client:
                    response = await client.post("/api/settings/models", json=body)
                assert response.status_code == 200, response.text
                assert response.json() == {"models": ["Alpha", "alpha", "zeta"]}
                assert STORED_KEY not in response.text
                assert "sk-typed" not in response.text


async def check_models_route_stored_key_rule():
    with mock_server() as (base_url, _):
        with patch.dict(os.environ, {"MOCK_MODELS": "a"}):
            async with stored_connection(base_url):
                async with api_client() as client:

                    async def auth_sent(payload: dict) -> str | None:
                        """Заголовок Authorization, который получил мок."""
                        mock_llm_server.state["models_auth"] = None
                        response = await client.post("/api/settings/models", json=payload)
                        assert response.status_code == 200, response.text
                        return mock_llm_server.state["models_auth"]

                    same = {"provider": "custom", "base_url": base_url}
                    # тот же адрес, косая черта в конце не мешает
                    sent = await auth_sent({**same, "base_url": base_url + "/"})
                    assert sent == f"Bearer {STORED_KEY}"
                    # введённый ключ важнее сохранённого
                    sent = await auth_sent({**same, "api_key": "sk-typed"})
                    assert sent == "Bearer sk-typed"
                    # другой адрес — сохранённый ключ не уходит
                    sent = await auth_sent({**same, "base_url": f"{base_url}/v1"})
                    assert STORED_KEY not in sent
                    # другой провайдер с тем же адресом
                    sent = await auth_sent({**same, "provider": "ollama"})
                    assert STORED_KEY not in sent
                    # ключ удалён
                    sent = await auth_sent({**same, "clear_api_key": True})
                    assert STORED_KEY not in sent
                    # заменить и удалить одновременно — как в PUT /api/settings
                    response = await client.post(
                        "/api/settings/models",
                        json={**same, "api_key": "sk-typed", "clear_api_key": True},
                    )
                    assert response.status_code == 400, response.text

            # сохранённый адрес был с косой чертой, в форме — без неё
            async with stored_connection(base_url, stored_base_url=base_url + "/"):
                async with api_client() as client:
                    response = await client.post("/api/settings/models", json=same)
                    assert response.status_code == 200, response.text
                assert mock_llm_server.state["models_auth"] == f"Bearer {STORED_KEY}"


async def check_models_route_provider_errors():
    with mock_server() as (base_url, closed):
        async with stored_connection(base_url):
            async with api_client() as client:

                async def detail(env: dict, payload: dict) -> str:
                    with patch.dict(os.environ, env):
                        response = await client.post("/api/settings/models", json=payload)
                    assert response.status_code == 502, response.text
                    return response.json()["detail"]

                own = {"provider": "custom", "base_url": base_url, "api_key": "sk-wrong-secret"}
                # сбои попадают в журнал сервера — без ключей
                with unittest.TestCase().assertLogs("app.main", level="WARNING") as logs:
                    text = await detail({"MOCK_MODELS_STATUS": "401"}, own)
                    assert "API-ключ" in text and "HTTP 401" in text, text
                    assert "sk-wrong-secret" not in text and STORED_KEY not in text
                    text = await detail({"MOCK_MODELS_STATUS": "404"}, own)
                    assert "вручную" in text, text
                    text = await detail({"MOCK_MODELS_RAW_HTML": "1"}, own)
                    assert "не список моделей" in text and "API-адрес" in text, text
                    text = await detail({"MOCK_MODELS_STATUS": "429"}, own)
                    assert "HTTP 429" in text, text
                    text = await detail(
                        {}, {"provider": "custom", "base_url": f"http://127.0.0.1:{closed}/v1"}
                    )
                    assert "подключиться" in text, text
                log_text = "\n".join(logs.output)
                assert "sk-wrong-secret" not in log_text
                assert STORED_KEY not in log_text


async def check_models_route_validation():
    with mock_server() as (base_url, _):
        # даже если проверка сломается, запрос уйдёт в мок, а не наружу
        with patch.dict(os.environ, {"OPENAI_BASE_URL": base_url}):
            mock_llm_server.state["models_requests"] = 0
            async with stored_connection(base_url):
                async with api_client() as client:
                    for address in (
                        "ftp://example.com/v1",
                        "https://user:password@example.com/v1",
                        "https://example.com/v1?token=secret",
                    ):
                        body = {
                            "provider": "custom",
                            "base_url": address,
                            "api_key": "sk-key-must-not-be-echoed",
                        }
                        response = await client.post("/api/settings/models", json=body)
                        assert response.status_code == 422, response.text
                        assert "sk-key-must-not-be-echoed" not in response.text
                    # пользовательский провайдер без адреса — то же, что и с пустым адресом
                    response = await client.post(
                        "/api/settings/models", json={"provider": "custom"}
                    )
                    assert response.status_code == 422, response.text
                    # ни один недопустимый запрос не дошёл до провайдера
                    assert mock_llm_server.state["models_requests"] == 0


async def check_models_route_requires_admin():
    original_mode, original_admins = auth.AUTH_MODE, config.ADMIN_USERS
    with mock_server() as (base_url, _):
        with patch.dict(os.environ, {"MOCK_MODELS": "a"}):
            async with stored_connection(base_url):
                body = {"provider": "custom", "base_url": base_url}
                mock_llm_server.state["models_requests"] = 0
                try:
                    auth.AUTH_MODE = "kerberos"
                    config.ADMIN_USERS = {"admin"}
                    async with api_client() as client:
                        response = await client.post("/api/settings/models", json=body)
                        assert response.status_code == 401, response.text
                        client.cookies.set("docs_ai_session", await user_cookie("worker"))
                        response = await client.post("/api/settings/models", json=body)
                        assert response.status_code == 403, response.text
                        # без прав запроса к провайдеру не было
                        assert mock_llm_server.state["models_requests"] == 0
                        client.cookies.set("docs_ai_session", await user_cookie("admin"))
                        response = await client.post("/api/settings/models", json=body)
                        assert response.status_code == 200, response.text
                        assert mock_llm_server.state["models_requests"] == 1
                    # режим off — без входа
                    auth.AUTH_MODE = "off"
                    async with api_client() as client:
                        response = await client.post("/api/settings/models", json=body)
                        assert response.status_code == 200, response.text
                finally:
                    config.ADMIN_USERS = original_admins
                    auth.AUTH_MODE = original_mode


asyncio.run(check_list_models_sorted_unique_pages())
asyncio.run(check_list_models_skips_broken_items())
asyncio.run(check_list_models_stops_on_broken_pagination())
asyncio.run(check_list_models_failures())
asyncio.run(check_models_route_returns_sorted_ids())
asyncio.run(check_models_route_stored_key_rule())
asyncio.run(check_models_route_provider_errors())
asyncio.run(check_models_route_validation())
asyncio.run(check_models_route_requires_admin())
print("MODEL-LIST-OK")
