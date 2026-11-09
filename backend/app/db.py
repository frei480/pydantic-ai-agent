import json
from typing import Any

import aiosqlite

from .config import DB_PATH, DEFAULT_CONTEXT_WINDOW_TOKENS

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Новый чат',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    history_json TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
CREATE TABLE IF NOT EXISTS model_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    base_url TEXT,
    context_window_tokens INTEGER NOT NULL DEFAULT 120000
);
"""


class Database:
    def __init__(self, path: str):
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        cur = await self._conn.execute("PRAGMA table_info(model_settings)")
        columns = {row["name"] for row in await cur.fetchall()}
        if "context_window_tokens" not in columns:
            await self._conn.execute(
                "ALTER TABLE model_settings ADD COLUMN context_window_tokens "
                f"INTEGER NOT NULL DEFAULT {DEFAULT_CONTEXT_WINDOW_TOKENS}"
            )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "database not connected"
        return self._conn

    # ---- chats ----

    async def list_chats(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC, id DESC"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def create_chat(self, title: str = "Новый чат") -> int:
        cur = await self.conn.execute(
            "INSERT INTO chats (title) VALUES (?)", (title,)
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_chat(self, chat_id: int) -> dict[str, Any] | None:
        cur = await self.conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_chat(self, chat_id: int) -> None:
        await self.conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        await self.conn.commit()

    async def rename_chat(self, chat_id: int, title: str) -> None:
        await self.conn.execute(
            "UPDATE chats SET title = ? WHERE id = ?", (title, chat_id)
        )
        await self.conn.commit()

    async def touch_chat(self, chat_id: int) -> None:
        await self.conn.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,)
        )
        await self.conn.commit()

    async def set_history(self, chat_id: int, messages: list[Any]) -> None:
        raw = json.dumps(messages)  # pydantic-ai messages: list[dict]
        await self.conn.execute(
            "UPDATE chats SET history_json = ? WHERE id = ?", (raw, chat_id)
        )
        await self.conn.commit()

    # ---- messages ----

    async def get_messages(self, chat_id: int) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_message(self, chat_id: int, role: str, content: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        await self.touch_chat(chat_id)
        return cur.lastrowid  # type: ignore[return-value]

    async def count_messages(self, chat_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    # ---- model settings ----

    async def get_model_settings(self) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            """
            SELECT provider, model, api_key, base_url, context_window_tokens
            FROM model_settings WHERE id = 1
            """
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def save_model_settings(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None,
        context_window_tokens: int,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO model_settings
                (id, provider, model, api_key, base_url, context_window_tokens)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                api_key = excluded.api_key,
                base_url = excluded.base_url,
                context_window_tokens = excluded.context_window_tokens
            """,
            (provider, model, api_key, base_url, context_window_tokens),
        )
        await self.conn.commit()
