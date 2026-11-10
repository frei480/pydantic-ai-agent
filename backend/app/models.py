from typing import TypedDict


class ChatSummary(TypedDict):
    id: int
    title: str
    created_at: str
    updated_at: str


class Chat(ChatSummary):
    history_json: str


class Message(TypedDict):
    id: int
    role: str
    content: str
    created_at: str


class ModelSettings(TypedDict):
    provider: str
    model: str
    api_key: str
    base_url: str | None
    context_window_tokens: int
