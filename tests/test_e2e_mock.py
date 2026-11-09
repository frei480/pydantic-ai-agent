"""E2E-тест пайплайна без реального LLM: мок-сервер OpeinAI через tests/mock_llm_server.py."""
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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mock_llm_server import serve  # noqa: E402

threading.Thread(target=serve, daemon=True).start()
time.sleep(0.3)

from app.agent import run_pipeline  # noqa: E402


async def main():
    final = None
    async for ev in run_pipeline("Как создать сплайн через API?", ""):
        t = ev["type"]
        if t in ("draft", "text"):
            print(f"[{t}] {ev['text'][:80]!r}")
        elif t == "critique":
            print(f"[critique] sufficient={ev['sufficient']} comments={ev['comments'][:60]!r}")
        elif t == "tool":
            print(f"[tool] {ev['detail'][:80]!r}")
        elif t == "phase":
            print(f"[phase] {ev['phase']} round={ev['round']}")
        else:
            if t == "final":
                final = ev
    print("final text:", final["text"][:200])
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    msgs = ModelMessagesTypeAdapter.validate_json(final["history_json"])
    print("history messages:", len(msgs))


asyncio.run(main())
print("E2E-OK")
