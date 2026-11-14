"""Verify authenticated administration and persistent agent content."""

import asyncio
from pathlib import Path
import sys
import tempfile

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import agent, main  # noqa: E402
from app.admin_content import AdminContentStore  # noqa: E402


async def check_admin_endpoints() -> None:
    original_password = main.ADMIN_PASSWORD
    original_store = main.admin_content
    original_config = agent.current_agent_admin_config()
    password = "test-admin-password-with-entropy"
    with tempfile.TemporaryDirectory() as directory:
        store = AdminContentStore(Path(directory))
        initial_config = store.initialize(
            agent.default_agent_admin_config(),
            Path("backend/app/skills").resolve(),
        )
        assert len(store.list_skills()) == 8
        agent.configure_agent_admin_content(initial_config, store.skills_root)
        main.admin_content = store
        main._admin_login_failures.clear()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=main.app),
                base_url="http://test",
            ) as client:
                main.ADMIN_PASSWORD = ""
                response = await client.post(
                    "/api/admin/login",
                    json={"password": password},
                )
                assert response.status_code == 503

                main.ADMIN_PASSWORD = password
                response = await client.get("/api/admin/config")
                assert response.status_code == 401

                response = await client.post(
                    "/api/admin/login",
                    json={"password": "wrong"},
                )
                assert response.status_code == 401

                response = await client.post(
                    "/api/admin/login",
                    json={"password": password},
                )
                assert response.status_code == 200
                assert "httponly" in response.headers["set-cookie"].lower()

                response = await client.get("/api/admin/config")
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "no-store"
                config = response.json()
                config["prompts"]["writer"] = "Изменённая инструкция писателя"
                config["subagents"][0]["name"] = "custom_docs_researcher"
                response = await client.put(
                    "/api/admin/config",
                    json=config,
                    headers={"X-Admin-Request": "1"},
                )
                assert response.status_code == 200, response.text
                assert (
                    agent.current_agent_admin_config().prompts.writer
                    == "Изменённая инструкция писателя"
                )
                assert (
                    agent.current_agent_admin_config().subagents[0].name
                    == "custom_docs_researcher"
                )

                skill_id = "admin-test-skill"
                content = (
                    "---\n"
                    f"name: {skill_id}\n"
                    "description: Тестовый навык.\n"
                    "---\n\n"
                    "# Тест\n"
                )
                headers = {"X-Admin-Request": "1"}
                response = await client.post(
                    f"/api/admin/skills/{skill_id}",
                    json={"content": content},
                    headers=headers,
                )
                assert response.status_code == 201, response.text

                response = await client.get(f"/api/admin/skills/{skill_id}")
                assert response.status_code == 200
                assert response.json()["content"] == content

                updated_content = content.replace("# Тест", "# Обновлено")
                response = await client.put(
                    f"/api/admin/skills/{skill_id}",
                    json={"content": updated_content},
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                assert "# Обновлено" in store.get_skill(skill_id)

                response = await client.post(
                    "/api/admin/skills/invalid",
                    json={"content": content},
                    headers=headers,
                )
                assert response.status_code == 400

                response = await client.delete(
                    f"/api/admin/skills/{skill_id}",
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                assert not (store.skills_root / skill_id).exists()
                reloaded = store.initialize(
                    agent.default_agent_admin_config(),
                    Path("backend/app/skills").resolve(),
                )
                assert reloaded.prompts.writer == "Изменённая инструкция писателя"
                assert all(skill["name"] != skill_id for skill in store.list_skills())

                response = await client.put("/api/admin/config", json=config)
                assert response.status_code == 403

                response = await client.post(
                    "/api/admin/logout",
                    headers=headers,
                )
                assert response.status_code == 200
                response = await client.get("/api/admin/config")
                assert response.status_code == 401
        finally:
            main.ADMIN_PASSWORD = original_password
            main.admin_content = original_store
            agent.configure_agent_admin_content(
                original_config, Path("backend/app/skills").resolve()
            )
            main._admin_login_failures.clear()


asyncio.run(check_admin_endpoints())
print("ADMIN-OK")
