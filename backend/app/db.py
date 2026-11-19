import json

import aiosqlite

from .model import Chat, ChatSummary, Message, ModelSettings
from .config import DB_PATH, DEFAULT_CONTEXT_WINDOW_TOKENS


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    upn TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Новый чат',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    history_json TEXT NOT NULL DEFAULT '',
    user_id INTEGER REFERENCES users(id)
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
    context_window_tokens INTEGER NOT NULL DEFAULT 120000,
    max_agent_response_tokens INTEGER NOT NULL DEFAULT 4096,
    max_critic_response_tokens INTEGER NOT NULL DEFAULT 2048
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
        for column, default in (
            ("max_agent_response_tokens", 4096),
            ("max_critic_response_tokens", 2048),
        ):
            if column not in columns:
                await self._conn.execute(
                    f"ALTER TABLE model_settings ADD COLUMN {column} "
                    f"INTEGER NOT NULL DEFAULT {default}"
                )
        cur = await self._conn.execute("PRAGMA table_info(chats)")
        chat_columns = {row["name"] for row in await cur.fetchall()}
        if "user_id" not in chat_columns:
            await self._conn.execute(
                "ALTER TABLE chats ADD COLUMN user_id INTEGER REFERENCES users(id)"
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

    # ---- users ----

    async def get_or_create_user(self, login: str, upn: str | None = None) -> int:
        login = login.lower()
        cur = await self.conn.execute(
            "SELECT id FROM users WHERE login = ?", (login,)
        )
        row = await cur.fetchone()
        if row is not None:
            return int(row["id"])
        cur = await self.conn.execute(
            "INSERT INTO users (login, upn) VALUES (?, ?)", (login, upn or "")
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def touch_user(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
        await self.conn.commit()

    # ---- app_meta ----

    async def get_meta(self, key: str) -> str | None:
        cur = await self.conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return row["value"] if row is not None else None

    async def set_meta(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    # ---- chats ----

    async def list_chats(
        self, user_id: int | None = None, include_legacy: bool = True
    ) -> list[ChatSummary]:
        # Псевдопользователь без id (off-режим) видит только наследие;
        # владелец — свои чаты и, с include_legacy, ещё и наследие.
        if user_id is None:
            clause = "user_id IS NULL" if include_legacy else "1 = 0"
            params: tuple = ()
        else:
            clause = "user_id = ?"
            if include_legacy:
                clause += " OR user_id IS NULL"
            params = (user_id,)
        cur = await self.conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats "
            f"WHERE {clause} "
            "ORDER BY updated_at DESC, id DESC",
            params,
        )
        return [
            ChatSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in await cur.fetchall()
        ]

    async def create_chat(
        self, title: str = "Новый чат", user_id: int | None = None
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO chats (title, user_id) VALUES (?, ?)", (title, user_id)
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_chat(self, chat_id: int) -> Chat | None:
        cur = await self.conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        return Chat(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            history_json=row["history_json"],
            user_id=row["user_id"],
        )

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

    async def set_history(self, chat_id: int, messages: list[object]) -> None:
        raw = json.dumps(messages)  # pydantic-ai messages: list[dict]
        await self.conn.execute(
            "UPDATE chats SET history_json = ? WHERE id = ?", (raw, chat_id)
        )
        await self.conn.commit()

    # ---- messages ----

    async def get_messages(self, chat_id: int) -> list[Message]:
        cur = await self.conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        )
        return [
            Message(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in await cur.fetchall()
        ]

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

    async def get_model_settings(self) -> ModelSettings | None:
        cur = await self.conn.execute(
            """
            SELECT provider, model, api_key, base_url, context_window_tokens,
                   max_agent_response_tokens, max_critic_response_tokens
            FROM model_settings WHERE id = 1
            """
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return ModelSettings(
            provider=row["provider"],
            model=row["model"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            context_window_tokens=row["context_window_tokens"],
            max_agent_response_tokens=row["max_agent_response_tokens"],
            max_critic_response_tokens=row["max_critic_response_tokens"],
        )

    async def save_model_settings(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None,
        context_window_tokens: int,
        max_agent_response_tokens: int = 4096,
        max_critic_response_tokens: int = 2048,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO model_settings
                (id, provider, model, api_key, base_url, context_window_tokens,
                 max_agent_response_tokens, max_critic_response_tokens)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                api_key = excluded.api_key,
                base_url = excluded.base_url,
                context_window_tokens = excluded.context_window_tokens,
                max_agent_response_tokens = excluded.max_agent_response_tokens,
                max_critic_response_tokens = excluded.max_critic_response_tokens
            """,
            (
                provider,
                model,
                api_key,
                base_url,
                context_window_tokens,
                max_agent_response_tokens,
                max_critic_response_tokens,
            ),
        )
        await self.conn.commit()
