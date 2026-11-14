"""Verify the HTTP endpoint exposes the indexed-page search result."""

import asyncio
from pathlib import Path
import sys

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import main  # noqa: E402


async def check_search_endpoint():
    original_docs_root = main.DOCS_ROOT
    main.DOCS_ROOT = Path("docs").resolve()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=main.app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/tools/search-indexed-pages",
                json={
                    "query": "ServerConnection",
                    "product": "TFlexDOCs API",
                    "limit": 5,
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["query"] == "ServerConnection"
            assert payload["indexed_pages"] > 0
            assert payload["result_count"] > 0
            assert payload["results"][0]["path"] == (
                "590BF971-0256-450B-8D9D-46C870673B97.md"
            )
            assert payload["results"][0]["excerpt_start_line"] > 0
            assert "ServerConnection" in payload["results"][0]["excerpt"]

            response = await client.post(
                "/api/tools/search-indexed-pages",
                json={
                    "query": "Файлы",
                    "product": "TFlexDOCs API",
                    "limit": 10,
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["result_count"] > 0
            files_page = payload["results"][0]
            assert files_page["path"] == "0BBDFA21-580C-4D3B-A6E8-30C3E6186D78.md"
            assert "Справочник" in files_page["excerpt"]

            for invalid in (
                {"query": "   "},
                {"query": "API", "product": "Unknown API"},
                {"query": "API", "limit": 21},
            ):
                response = await client.post(
                    "/api/tools/search-indexed-pages",
                    json=invalid,
                )
                assert response.status_code == 422, response.text
    finally:
        main.DOCS_ROOT = original_docs_root


asyncio.run(check_search_endpoint())
print("INDEXED-SEARCH-ENDPOINT-OK")
