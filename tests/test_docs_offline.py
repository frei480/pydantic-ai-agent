"""Проверка офлайн-документации: Swagger UI и ReDoc без внешних CDN."""

import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app.main import app  # noqa: E402

EXTERNAL_HOSTS = ("cdn.jsdelivr", "googleapis", "fastapi.tiangolo")
ASSETS = (
    Path("frontend/public/static/docs-assets/js/swagger-ui-bundle.js"),
    Path("frontend/public/static/docs-assets/js/redoc.standalone.js"),
    Path("frontend/public/static/docs-assets/css/swagger-ui.css"),
    Path("frontend/public/static/docs-assets/favicon-32x32.png"),
)


async def check_docs_offline() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        assert docs.status_code == 200
        assert "/static/docs-assets/js/swagger-ui-bundle.js" in docs.text
        assert "/static/docs-assets/css/swagger-ui.css" in docs.text
        assert "/static/docs-assets/favicon-32x32.png" in docs.text

        redoc = await client.get("/redoc")
        assert redoc.status_code == 200
        assert "/static/docs-assets/js/redoc.standalone.js" in redoc.text

        redirect = await client.get("/docs/oauth2-redirect")
        assert redirect.status_code == 200

        for name, response in (("docs", docs), ("redoc", redoc), ("redirect", redirect)):
            for host in EXTERNAL_HOSTS:
                assert host not in response.text, f"{name}: внешний хост {host}"

    for asset in ASSETS:
        assert asset.is_file(), f"нет ассета {asset}"

    nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")
    for location in ("location /docs", "location /redoc", "location = /openapi.json"):
        assert location in nginx, f"в nginx.conf нет локации {location}"
