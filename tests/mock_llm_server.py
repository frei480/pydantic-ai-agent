"""Мок-сервер OpenAI API (Chat Completions, стриминг и не-стриминг) для тестов.

Сценарий по числу запросов:
  1 — вызов инструмента search_docs,
  2 — текстовый черновик,
  3 — structured-вердикт критика (final_result),
  4+ — финальный текст.
"""
import json
import os
import sys

from http.server import BaseHTTPRequestHandler, HTTPServer

state = {"turn": 0, "failures_remaining": int(os.getenv("MOCK_502_FAILURES", "0"))}


def _tool_chunk(name, args, tool_id="t1"):
    return {
        "delta": {
            "tool_calls": [
                {
                    "index": 0,
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            ]
        }
    }


def _text_chunk(text):
    return {"delta": {"content": text}}


def _sse_response(chunks, finish):
    for chunk in chunks:
        obj = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "model": "mock-model",
            "choices": [{"index": 0, "finish_reason": None, **chunk}],
        }
        yield b"data: " + json.dumps(obj).encode() + b"\n\n"
    obj = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "model": "mock-model",
        "choices": [{"index": 0, "finish_reason": finish, "delta": {}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    yield b"data: " + json.dumps(obj).encode() + b"\n\n"
    yield b"data: [DONE]\n\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json_completion(self, chunks, finish):
        content = ""
        tool_calls = []
        for c in chunks:
            delta = c.get("delta") or {}
            if delta.get("content"):
                content += delta["content"]
            for tc in delta.get("tool_calls") or []:
                tool_calls.append(
                    {
                        "id": tc.get("id", "t1"),
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                )
        message = {"role": "assistant", "content": content}
        fm = "tool_calls" if tool_calls else finish
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": "mock-model",
            "choices": [{"index": 0, "finish_reason": fm, "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length)
        try:
            body = json.loads(body_raw)
        except Exception:
            body = {}
        streaming = bool(body.get("stream")) or "text/event-stream" in self.headers.get(
            "Accept", ""
        )
        if self.path.endswith("/chat/completions") and any(
            message.get("content") == "Reply with exactly: HEALTH_OK"
            for message in body.get("messages", [])
        ):
            if state["failures_remaining"] > 0:
                state["failures_remaining"] -= 1
                payload = json.dumps(
                    {
                        "error": {
                            "message": "Upstream error from Nvidia: Internal server error",
                            "type": "provider_unavailable",
                            "code": 502,
                        }
                    }
                ).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After-Ms", "1")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            payload = json.dumps(
                self._json_completion([_text_chunk("HEALTH_OK")], "stop")
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        tools = body.get("tools") or []
        final_tool = next(
            (
                t["function"]["name"]
                for t in tools
                if isinstance(t, dict) and "final" in (t.get("function", {}).get("name") or "")
            ),
            "final_result",
        )
        if self.path.endswith("/chat/completions"):
            state["turn"] += 1
            turn = state["turn"]
            print(
                f"MOCK: turn={turn} streaming={streaming}",
                flush=True,
            )
            if turn == 1:
                args = json.dumps({"pattern": "SplineConstruction", "literal": True})
                chunks = [_tool_chunk("search_docs", args)]
            elif turn == 2:
                chunks = [_text_chunk(
                    "ФАКТЫ:\n- SplineConstruction подтверждён (000f2ea4…)\nПРОБЕЛЫ: нет"
                )]
            elif turn == 3:
                args = json.dumps(
                    {
                        "is_sufficient": True,
                        "missing_info": [],
                        "search_queries": [],
                        "comments": "фактов достаточно",
                    }
                )
                chunks = [_tool_chunk(final_tool, args, tool_id="t2")]
            else:
                chunks = [_text_chunk("Ответ готов. ```csharp\nvar doc = TFlex.Application.ActiveDocument;\n```")]
            finish = (
                "tool_calls"
                if any("tool_calls" in (c.get("delta") or {}) for c in chunks)
                else "stop"
            )
            if streaming:
                payload = b"".join(_sse_response(chunks, finish))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                obj = self._json_completion(chunks, finish)
                payload = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)


def serve(port=3999):
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3999
    serve(port)
