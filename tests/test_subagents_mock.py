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
os.environ["MOCK_SKILL_LOADING"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mock_llm_server import serve, state  # noqa: E402

threading.Thread(target=serve, daemon=True).start()
time.sleep(0.3)

from app.agent import run_pipeline  # noqa: E402


async def main():
    scenarios = (
        ("Как написать макрос для T-FLEX DOCs?", "tflex_docs_researcher"),
        ("Как открыть и сохранить документ T-FLEX CAD?", "tflex_cad_document_researcher"),
        ("Как создать 2D узел T-FLEX CAD?", "tflex_cad_2d_researcher"),
        ("Как создать операцию выталкивания T-FLEX CAD?", "tflex_cad_3d_researcher"),
    )
    for prompt, specialist in scenarios:
        state["turn"] = 0
        os.environ["MOCK_DELEGATION_AGENT"] = specialist
        events = [event async for event in run_pipeline(prompt, "")]
        assert any(
            event["type"] == "tool"
            and specialist in event["detail"]
            for event in events
        ) or any(
            event["type"] == "agent" and event.get("agent_name") == specialist
            for event in events
        ), f"researcher did not delegate to {specialist}"
        assert any(
            event["type"] == "skill"
            and event.get("skill_name") == "tflex-cad-3d-modeling"
            and event.get("agent_name") == specialist
            for event in events
        ), f"sub-agent skill load was not reported for {specialist}"
        assert any(
            event["type"] == "skill"
            and event.get("skill_name") == "tflex-cad-3d-modeling"
            and event.get("phase") == "write"
            for event in events
        ), "writer skill load was not reported"
        final = next(event for event in events if event["type"] == "final")
        assert final["text"] == "Ответ подготовлен на основании фактов субагента."
    print("SUBAGENT-E2E-OK")


asyncio.run(main())
