"""Список моделей провайдера: GET …/models через OpenAI SDK и маршрут POST /api/settings/models."""
import asyncio
import os
import socket
import sys
import threading
from contextlib import contextmanager
from http.server import HTTPServer
from unittest.mock import patch

import openai

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mock_llm_server  # noqa: E402
from app import agent  # noqa: E402


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


asyncio.run(check_list_models_sorted_unique_pages())
asyncio.run(check_list_models_skips_broken_items())
asyncio.run(check_list_models_stops_on_broken_pagination())
asyncio.run(check_list_models_failures())
print("MODEL-LIST-OK")
