"""Проверки политики повторов провайдера и понятного ответа для HTTP 429."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "backend")

from app.agent import _RetryTransientErrorsAsyncOpenAI  # noqa: E402
from app import agent  # noqa: E402
from app import main  # noqa: E402

client = _RetryTransientErrorsAsyncOpenAI(api_key="test-key", max_retries=5)
assert isinstance(client.with_options(max_retries=2), _RetryTransientErrorsAsyncOpenAI)
assert not client._should_retry(SimpleNamespace(status_code=429, headers={}))
assert client._should_retry(SimpleNamespace(status_code=502, headers={}))
assert client._should_retry(
    SimpleNamespace(status_code=429, headers={"x-should-retry": "true"})
)

message = main._provider_error_message(
    SimpleNamespace(status_code=429, body={"error": "free-models-per-day"})
)
assert "HTTP 429" in message
assert "квоту" in message
assert "выбранной модели" in message


async def check_model_probe_accepts_reasoning_content():
    provider = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content="",
                                        reasoning_content="The model generated a response.",
                                    )
                                )
                            ]
                        )
                    )
                )
            ),
            close=AsyncMock(),
        )
    )
    with patch.object(agent, "_build_provider", return_value=provider):
        assert await agent.probe_model()
    provider.client.close.assert_awaited_once()


async def check_health_cache():
    main._model_health_cache = None
    main._model_health_checked_at = 0
    with patch.object(main.agent, "probe_model", new=AsyncMock(return_value=True)) as probe:
        first = await main.model_health()
        second = await main.model_health()
    assert first == second
    assert probe.await_count == 1


asyncio.run(check_model_probe_accepts_reasoning_content())
asyncio.run(check_health_cache())
print("PROVIDER-RETRY-OK")
