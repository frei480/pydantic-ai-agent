"""Verify authenticated administration and persistent agent content."""

import asyncio
from pathlib import Path
import sys
import tempfile

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "backend")

from app import agent, main  # noqa: E402
from app.admin_content import AdminContentStore  # noqa: E402


def check_admin_content_migration() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = AdminContentStore(Path(directory))
        defaults = agent.default_agent_admin_config()
        config = store.initialize(
            defaults.model_copy(deep=True), Path("backend/app/skills").resolve()
        )
        config.subagents = config.subagents[:4]
        config.prompts.writer = "Пользовательская инструкция"
        store.save_config(config)
        (store.data_dir / ".api-examples-content-v1").unlink()

        new_skill_ids = {
            "tflex-docs-reference-import",
            "tflex-docs-test-data-generation",
            "tflex-docs-unit-conversion",
            "tflex-docs-plugin-ui-extensions",
            "tflex-docs-parameters",
            "tflex-docs-stages-signatures",
        }
        for skill_id in new_skill_ids:
            skill_directory = store.skills_root / skill_id
            for path in skill_directory.iterdir():
                path.unlink()
            skill_directory.rmdir()

        migrated = store.initialize(defaults, Path("backend/app/skills").resolve())
        assert migrated.prompts.writer == "Пользовательская инструкция"
        assert {
            "tflex_docs_reference_importer",
            "tflex_docs_test_data_generator",
            "tflex_docs_units_researcher",
            "tflex_docs_plugin_ui_researcher",
            "tflex_docs_events_researcher",
        }.issubset({subagent.name for subagent in migrated.subagents})
        assert new_skill_ids.issubset(
            {skill["name"] for skill in store.list_skills()}
        )

        migrated.subagents = [
            subagent
            for subagent in migrated.subagents
            if subagent.name != "tflex_docs_units_researcher"
        ]
        store.save_config(migrated)
        deleted_skill = store.skills_root / "tflex-docs-unit-conversion"
        (deleted_skill / "SKILL.md").unlink()
        deleted_skill.rmdir()
        reloaded = store.initialize(defaults, Path("backend/app/skills").resolve())
        assert "tflex_docs_units_researcher" not in {
            subagent.name for subagent in reloaded.subagents
        }
        assert "tflex-docs-unit-conversion" not in {
            skill["name"] for skill in store.list_skills()
        }


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
        assert len(store.list_skills()) == 17
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
                assert reloaded.subagents[0].name == "custom_docs_researcher"
                assert {
                    "tflex_docs_reference_importer",
                    "tflex_docs_test_data_generator",
                    "tflex_docs_units_researcher",
                    "tflex_docs_plugin_ui_researcher",
                }.issubset({subagent.name for subagent in reloaded.subagents})
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


check_admin_content_migration()
asyncio.run(check_admin_endpoints())
print("ADMIN-OK")
