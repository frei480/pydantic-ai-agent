"""Проверки сохранения и безопасной выдачи настроек модели."""
import asyncio
import os
import sqlite3
import sys
import tempfile

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import agent, main  # noqa: E402
from app.config import DEFAULT_CONTEXT_WINDOW_TOKENS  # noqa: E402
from app.db import Database  # noqa: E402
from app.doc_tools import estimate_tokens  # noqa: E402


async def check_model_settings_storage():
    original_database = main.dbase
    original_settings = agent.current_model_settings()
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "settings.db")
        database = Database(db_path)
        await database.connect()
        main.dbase = database
        try:
            await database.save_model_settings(
                "openai", "gpt-4o-mini", "", None, 120000
            )
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.put(
                    "/api/settings",
                    json={
                        "provider": "openrouter",
                        "model": "openai/gpt-4o-mini",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-private-test-key",
                        "context_window_tokens": 8192,
                    },
                )
                assert response.status_code == 200, response.text
                saved = response.json()
                assert saved == {
                    "provider": "openrouter",
                    "model": "openai/gpt-4o-mini",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_configured": True,
                    "context_window_tokens": 8192,
                }
                assert "sk-private-test-key" not in response.text

                response = await client.get("/api/settings")
                assert response.status_code == 200
                assert "sk-private-test-key" not in response.text
                assert response.json()["api_key_configured"] is True

                stored = await database.get_model_settings()
                assert stored is not None
                assert stored["api_key"] == "sk-private-test-key"
                assert stored["context_window_tokens"] == 8192

                response = await client.put(
                    "/api/settings",
                    json={
                        "provider": "ollama",
                        "model": "qwen2.5:7b",
                        "base_url": "http://host.docker.internal:11434/v1",
                        "context_window_tokens": 16384,
                    },
                )
                assert response.status_code == 200, response.text
                stored = await database.get_model_settings()
                assert stored is not None
                assert stored["api_key"] == "sk-private-test-key"
                assert agent.current_model_settings().model == "qwen2.5:7b"
                assert agent.current_model_settings().provider == "ollama"
                assert agent.current_model_settings().context_window_tokens == 16384
                assert agent.current_model_settings().api_key == "sk-private-test-key"
                assert (
                    agent.current_model_settings().base_url
                    == "http://host.docker.internal:11434/v1"
                )

                response = await client.put(
                    "/api/settings",
                    json={
                        "provider": "ollama",
                        "model": "qwen2.5:7b",
                        "base_url": "http://host.docker.internal:11434/v1",
                        "clear_api_key": True,
                        "context_window_tokens": 16384,
                    },
                )
                assert response.status_code == 200, response.text
                stored = await database.get_model_settings()
                assert stored is not None
                assert stored["api_key"] == ""
                assert stored["context_window_tokens"] == 16384
                assert response.json()["api_key_configured"] is False

                response = await client.put(
                    "/api/settings",
                    json={
                        "provider": "custom",
                        "model": "model",
                        "base_url": "https://user:password@example.com/v1",
                        "api_key": "sk-key-must-not-be-echoed",
                        "context_window_tokens": 16384,
                    },
                )
                assert response.status_code == 422, response.text
                assert "sk-key-must-not-be-echoed" not in response.text

                for invalid_limit in (4095, 2_000_001):
                    response = await client.put(
                        "/api/settings",
                        json={
                            "provider": "openai",
                            "model": "gpt-4o-mini",
                            "context_window_tokens": invalid_limit,
                        },
                    )
                    assert response.status_code == 422, response.text

            stored = await database.get_model_settings()
            assert stored is not None
            assert stored["api_key"] == ""
            assert agent.current_model_settings().model == "qwen2.5:7b"
            assert agent.current_model_settings().context_window_tokens == 16384

            await database.close()
            database = Database(db_path)
            await database.connect()
            main.dbase = database
            persisted = await database.get_model_settings()
            assert persisted is not None
            agent.configure_model(agent.ModelSettings(**persisted))
            assert agent.current_model_settings().model == "qwen2.5:7b"
            assert agent.current_model_settings().api_key == ""
            assert agent.current_model_settings().context_window_tokens == 16384
        finally:
            agent.configure_model(original_settings)
            main.dbase = original_database
            await database.close()


def check_settings_validation():
    for address in (
        "ftp://example.com/v1",
        "https://user:password@example.com/v1",
        "https://example.com/v1?token=secret",
    ):
        try:
            main.ModelSettingsIn(provider="custom", model="model", base_url=address)
        except ValueError:
            continue
        raise AssertionError(f"invalid provider URL was accepted: {address}")

    valid = main.ModelSettingsIn(
        provider="custom", model=" custom-model ", base_url="http://localhost:8000/v1/"
    )
    assert valid.model == "custom-model"
    assert valid.base_url == "http://localhost:8000/v1"
    assert (
        main.ModelSettingsIn(
            provider="ollama", model="qwen2.5:7b", base_url=""
        ).base_url
        == "http://host.docker.internal:11434/v1"
    )
    assert (
        main.ModelSettingsIn(provider="lmstudio", model="local-model", base_url="")
        .base_url
        == "http://host.docker.internal:1234/v1"
    )


def check_context_prompt_trimming():
    limit = 100
    _, prompt, dropped_history, truncated = agent._fit_context(
        None, "x" * 10000, "system instructions", limit
    )
    assert not dropped_history
    assert truncated
    assert prompt.endswith("[Текст сокращён по лимиту контекста.]")
    assert estimate_tokens(prompt + "system instructions") <= limit


def check_phase_response_token_limits():
    assert agent._response_token_limit(128_000, agent.MAX_AGENT_RESPONSE_TOKENS) == 4096
    assert agent._response_token_limit(128_000, agent.MAX_CRITIC_RESPONSE_TOKENS) == 1024
    assert agent._response_token_limit(4_096, agent.MAX_AGENT_RESPONSE_TOKENS) == 819
    schema = agent.Critique.model_json_schema()["properties"]
    assert schema["missing_info"]["maxItems"] == 5
    assert schema["missing_info"]["items"]["maxLength"] == 240
    assert schema["search_queries"]["maxItems"] == 3
    assert schema["search_queries"]["items"]["maxLength"] == 240
    assert schema["comments"]["maxLength"] == 500


async def check_existing_database_migration():
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "legacy.db")
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE model_settings (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO model_settings (id, provider, model) VALUES (1, 'openai', 'old-model')"
        )
        connection.commit()
        connection.close()

        database = Database(db_path)
        await database.connect()
        try:
            settings = await database.get_model_settings()
            assert settings is not None
            assert settings["model"] == "old-model"
            assert settings["context_window_tokens"] == DEFAULT_CONTEXT_WINDOW_TOKENS
        finally:
            await database.close()


check_settings_validation()
check_context_prompt_trimming()
check_phase_response_token_limits()
asyncio.run(check_model_settings_storage())
asyncio.run(check_existing_database_migration())
print("MODEL-SETTINGS-OK")
