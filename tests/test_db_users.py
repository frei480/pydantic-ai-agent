"""Проверки пользователей, app_meta и владения чатами в БД."""
import asyncio
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "backend")

from app.db import Database  # noqa: E402


async def check_users_and_meta():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "users.db"))
        await database.connect()
        try:
            ivanov = await database.get_or_create_user(
                "IVANOV", "IVANOV@CORP.LOCAL"
            )
            assert isinstance(ivanov, int)
            # тот же пользователь при другом регистре логина, UPN не нужен
            again = await database.get_or_create_user("ivanov")
            assert again == ivanov
            # существующий логин: UPN не перезаписывается
            await database.get_or_create_user("Ivanov", "OTHER@CORP.LOCAL")
            cur = await database.conn.execute(
                "SELECT login, upn FROM users WHERE id = ?", (ivanov,)
            )
            row = await cur.fetchone()
            assert row["login"] == "ivanov"
            assert row["upn"] == "IVANOV@CORP.LOCAL"

            # touch_user обновляет last_seen_at
            await database.conn.execute(
                "UPDATE users SET last_seen_at = '2000-01-01 00:00:00' "
                "WHERE id = ?",
                (ivanov,),
            )
            await database.touch_user(ivanov)
            cur = await database.conn.execute(
                "SELECT last_seen_at FROM users WHERE id = ?", (ivanov,)
            )
            row = await cur.fetchone()
            assert row["last_seen_at"] > "2000-01-01"

            # set_meta/get_meta: roundtrip, перезапись, отсутствие ключа
            assert await database.get_meta("missing") is None
            await database.set_meta("session_secret", "abc")
            assert await database.get_meta("session_secret") == "abc"
            await database.set_meta("session_secret", "xyz")
            assert await database.get_meta("session_secret") == "xyz"
        finally:
            await database.close()


async def check_chats_migration():
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "legacy.db")
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'Новый чат',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                history_json TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute("INSERT INTO chats (title) VALUES ('старый чат')")
        connection.commit()
        connection.close()

        database = Database(db_path)
        await database.connect()
        try:
            cur = await database.conn.execute("PRAGMA table_info(chats)")
            columns = {row["name"] for row in await cur.fetchall()}
            assert "user_id" in columns, columns
            chat = await database.get_chat(1)
            assert chat is not None
            assert chat["title"] == "старый чат"
            assert chat["user_id"] is None
        finally:
            await database.close()


async def check_list_chats_scoping():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(os.path.join(directory, "scoping.db"))
        await database.connect()
        try:
            alice = await database.get_or_create_user("alice", "ALICE@CORP.LOCAL")
            bob = await database.get_or_create_user("bob", "BOB@CORP.LOCAL")
            await database.create_chat("чат alice", user_id=alice)
            await database.create_chat("чат bob", user_id=bob)
            await database.create_chat("наследие")

            def titles(chats):
                return {chat["title"] for chat in chats}

            only_alice = await database.list_chats(
                user_id=alice, include_legacy=False
            )
            assert titles(only_alice) == {"чат alice"}, titles(only_alice)

            only_bob = await database.list_chats(user_id=bob, include_legacy=False)
            assert titles(only_bob) == {"чат bob"}, titles(only_bob)

            alice_with_legacy = await database.list_chats(
                user_id=alice, include_legacy=True
            )
            assert titles(alice_with_legacy) == {"чат alice", "наследие"}, titles(
                alice_with_legacy
            )

            # off-режим: псевдользователь без id видит только наследие
            legacy_only = await database.list_chats(user_id=None, include_legacy=True)
            assert titles(legacy_only) == {"наследие"}, titles(legacy_only)

            none_strict = await database.list_chats(user_id=None, include_legacy=False)
            assert none_strict == [], none_strict

            # вызов без аргументов (старые вызовы main.py) не ломается
            default_call = await database.list_chats()
            assert titles(default_call) == {"наследие"}, titles(default_call)
        finally:
            await database.close()


asyncio.run(check_users_and_meta())
asyncio.run(check_chats_migration())
asyncio.run(check_list_chats_scoping())
print("DB-USERS-OK")
