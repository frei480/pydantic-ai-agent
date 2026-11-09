"""E2E-тест HTTP-слоя: uvicorn + SSE поверх мок-LLM (tests/mock_llm_server.py)."""
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
env = dict(os.environ)
env.update(
    {
        "DOCS_ROOT": os.path.join(ROOT, "docs"),
        "OPENAI_API_KEY": "sk-dummy",
        "OPENAI_BASE_URL": f"http://127.0.0.1:{mock_port}/v1",
        "AI_MODEL": "mock-model",
        "MOCK_502_FAILURES": "2",
        "OPENAI_MAX_RETRIES": "3",
        "DB_PATH": os.path.join(temp_dir.name, "chats_http.db"),
        "PYDANTIC_AI_NO_BANNER": "1",
    }
)

mock = start_bg("tests/mock_llm_server.py", env, str(mock_port))
time.sleep(0.5)

env["DB_PATH"] = os.path.join(temp_dir.name, "chats_http2.db")
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

    model_health = json.loads(
        urllib.request.urlopen(f"{base_url}/api/health/model", timeout=15).read()
    )
    assert model_health["status"] == "ok", model_health
    assert model_health["model"] == "mock-model"
    print("model health:", model_health)

    req = urllib.request.Request(
        f"{base_url}/api/chats",
        data=json.dumps({"title": "тест"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chat = json.loads(urllib.request.urlopen(req).read())
    print("chat created:", chat["id"])

    body = json.dumps({"content": "Как создать сплайн?"}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/chats/{chat['id']}/messages",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        ct = resp.headers.get("Content-Type")
        print("content-type:", ct)
        assert "event-stream" in ct
        events = []
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    types = [e["type"] for e in events]
    print("event types:", types[:10], "…total", len(types))
    # финальный текст стримится как text; final в SSE не отсылается, он сохраняется в БД
    assert "done" in types and "text" in types, events

    msgs = json.loads(
        urllib.request.urlopen(
            f"{base_url}/api/chats/{chat['id']}/messages"
        ).read()
    )
    print("saved messages:", [(m["role"], m["content"][:50]) for m in msgs["messages"]])
    assert msgs["messages"][-1]["role"] == "assistant"
    print("HTTP-E2E-OK")
finally:
    for proc in (server, mock):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    temp_dir.cleanup()
