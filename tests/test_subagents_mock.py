"""Verify that the researcher delegates a DOCs task to its domain specialist."""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, "backend")
sys.path.insert(0, "tests")
os.environ["DOCS_ROOT"] = r"D:\work\prog\py\pydantic-ai-agent\docs"
os.environ["OPENAI_API_KEY"] = "sk-dummy"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:3999/v1"
os.environ["AI_MODEL"] = "mock-model"
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
os.environ["MOCK_DELEGATION"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mock_llm_server import serve  # noqa: E402

threading.Thread(target=serve, daemon=True).start()
time.sleep(0.3)

from app.agent import run_pipeline  # noqa: E402


async def main():
    events = [
        event
        async for event in run_pipeline("Как написать макрос для T-FLEX DOCs?", "")
    ]
    assert any(
        event["type"] == "tool" and "delegate_task" in event["detail"]
        for event in events
    ), "researcher did not invoke its domain specialist"
    final = next(event for event in events if event["type"] == "final")
    assert final["text"] == "Ответ подготовлен на основании фактов субагента."
    print("SUBAGENT-E2E-OK")


asyncio.run(main())
