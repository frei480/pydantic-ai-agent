"""E2E-тест полного логирования ошибок LLM: uvicorn + SSE поверх мок-LLM,
у которого каждый вызов модели падает с 502 (MOCK_FAIL_ALL=1).

Проверяет, что при сбое провайдера клиенту уходит краткое SSE-событие error,
а полный дамп (исключение + последний запрос к модели) оказывается в файле
LLM_ERROR_LOG_PATH.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_bg(script, env, *args):
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", script, *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


mock_port = free_port()
server_port = free_port()
temp_dir = tempfile.TemporaryDirectory()
log_path = os.path.join(temp_dir.name, "llm-errors.log")
env = dict(os.environ)
env.update(
    {
        "DOCS_ROOT": os.path.join(ROOT, "docs"),
        "OPENAI_API_KEY": "sk-dummy",
        "OPENAI_BASE_URL": f"http://127.0.0.1:{mock_port}/v1",
        "AI_MODEL": "mock-model",
        "MOCK_FAIL_ALL": "1",
        "OPENAI_MAX_RETRIES": "1",
        "LLM_ERROR_LOG_PATH": log_path,
        "DB_PATH": os.path.join(temp_dir.name, "chats.db"),
        "PYDANTIC_AI_NO_BANNER": "1",
    }
)

mock = start_bg("tests/mock_llm_server.py", env, str(mock_port))
time.sleep(0.5)
env["PORT"] = str(server_port)
server = start_bg("backend/run_server.py", env)
base_url = f"http://127.0.0.1:{server_port}"
try:
    for _ in range(75):
        try:
            h = urllib.request.urlopen(f"{base_url}/api/health", timeout=2)
            print("health:", h.read().decode())
            break
        except Exception:
            time.sleep(0.2)
            if server.poll() is not None:
                out = server.stdout.read().decode(errors="replace") if server.stdout else ""
                raise RuntimeError(f"server died:\n{out}")
    else:
        raise RuntimeError(
            f"server did not start (poll={server.poll()})\n"
            + (server.stdout.read().decode(errors="replace") if server.stdout else "")
        )

    req = urllib.request.Request(
        f"{base_url}/api/chats",
        data=json.dumps({"title": "тест ошибок"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chat = json.loads(urllib.request.urlopen(req).read())
    chat_id = str(chat["id"])
    print("chat created:", chat_id)

    body = json.dumps({"content": "Как создать сплайн?"}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/chats/{chat_id}/messages",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        ct = resp.headers.get("Content-Type")
        assert "event-stream" in ct
        events = []
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    types = [e["type"] for e in events]
    print("event types:", types)
    # при сбое провайдера клиент получает краткое событие error без done
    assert "error" in types, events
    assert "done" not in types, events
    error_event = next(e for e in events if e["type"] == "error")
    assert "MOCK-FAIL-ALL-MARKER" in error_event["message"], error_event

    log_content = open(log_path, encoding="utf-8").read()
    assert "MOCK-FAIL-ALL-MARKER" in log_content, log_content[:2000]
    assert "[ПОСЛЕДНИЙ ЗАПРОС К МОДЕЛИ]" in log_content, log_content[:2000]
    assert "mock-model" in log_content, log_content[:2000]
    assert f"chat_id={chat_id}" in log_content, log_content[:2000]
    print("LLM-ERROR-E2E-OK")
finally:
    for proc in (server, mock):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    temp_dir.cleanup()
