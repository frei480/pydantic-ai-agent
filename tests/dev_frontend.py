"""Мини-сервер разработки фронтенда: статика + прокси /api -> backend:8000."""
import os
import sys
import urllib.request
from http.server import SimpleHTTPRequestHandler, HTTPServer

FRONT = os.path.join(os.path.dirname(__file__), "..", "frontend")
BACK = os.environ.get("BACKEND", "http://127.0.0.1:8000")


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONT, **kw)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
        else:
            self.send_error(405)

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(BACK + self.path, data=body, method=method)
        for h in ("Content-Type",):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "text/plain"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_error(e.code)


if __name__ == "__main__":
    port = int(sys.env or 8090) if False else int(os.environ.get("PORT", "8090"))
    HTTPServer(("127.0.0.1", port), DevHandler).serve_forever()
