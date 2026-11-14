import re
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .config import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    MAX_AGENT_RESPONSE_TOKENS,
    MAX_CRITIC_RESPONSE_TOKENS,
)


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
    max_agent_response_tokens: int
    max_critic_response_tokens: int


class SettingsOut(TypedDict):
    provider: str
    model: str
    base_url: str
    api_key_configured: bool
    context_window_tokens: int
    max_agent_response_tokens: int
    max_critic_response_tokens: int


class ChatOut(TypedDict):
    id: int
    title: str
    created_at: str
    updated_at: str


class HealthOut(TypedDict):
    status: Literal["ok"]
    model: str
    provider: str
    docs_root: str
    context_token_limit: int


class ModelHealthOut(TypedDict):
    status: Literal["ok", "error"]
    model: str
    detail: str


class ChatMessagesOut(TypedDict):
    chat: ChatOut
    messages: list[Message]


class ChatIn(BaseModel):
    title: str = "Новый чат"


class MessageIn(BaseModel):
    content: str


class IndexedPageSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    product: Literal["TFlexCAD API", "TFlexDOCs API"] = "TFlexDOCs API"
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите поисковый запрос")
        return value


class IndexedPageSearchResultOut(BaseModel):
    title: str
    path: str
    breadcrumb: str
    section: str
    keywords: list[str]
    intro: str
    excerpt: str
    excerpt_start_line: int
    excerpt_end_line: int


class IndexedPageSearchOut(BaseModel):
    query: str
    product: str
    indexed_pages: int
    result_count: int
    elapsed_ms: float
    results: list[IndexedPageSearchResultOut]


class ModelSettingsIn(BaseModel):
    provider: Literal["openai", "openrouter", "ollama", "lmstudio", "custom"]
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    context_window_tokens: int = Field(
        default=DEFAULT_CONTEXT_WINDOW_TOKENS, ge=4096, le=2_000_000
    )
    max_agent_response_tokens: int = Field(
        default=MAX_AGENT_RESPONSE_TOKENS, ge=256, le=32_768
    )
    max_critic_response_tokens: int = Field(
        default=MAX_CRITIC_RESPONSE_TOKENS, ge=256, le=16_384
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите название модели")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        value = (value or "").strip()
        if not value:
            provider = info.data.get("provider")
            if provider == "openrouter":
                return "https://openrouter.ai/api/v1"
            if provider == "ollama":
                return "http://host.docker.internal:11434/v1"
            if provider == "lmstudio":
                return "http://host.docker.internal:1234/v1"
            if provider == "custom":
                raise ValueError("Для пользовательского провайдера укажите API-адрес")
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Адрес должен начинаться с http:// или https://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Адрес не должен содержать логин, пароль, параметры или фрагмент")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Порт в API-адресе указан некорректно") from exc
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def trim_api_key(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AdminLoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class AdminSessionOut(BaseModel):
    authenticated: bool = True


class AdminPrompts(BaseModel):
    researcher: str = Field(min_length=1, max_length=100_000)
    delegation: str = Field(min_length=1, max_length=30_000)
    critic: str = Field(min_length=1, max_length=30_000)
    writer: str = Field(min_length=1, max_length=30_000)


class AdminSubAgent(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    description: str = Field(min_length=1, max_length=2_000)
    instructions: str = Field(min_length=1, max_length=50_000)
    skills_enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", value):
            raise ValueError("ID должен содержать строчные латинские буквы, цифры и _")
        return value


class AgentAdminConfig(BaseModel):
    prompts: AdminPrompts
    subagents: list[AdminSubAgent] = Field(min_length=1, max_length=32)

    @field_validator("subagents")
    @classmethod
    def validate_unique_subagents(
        cls, value: list[AdminSubAgent]
    ) -> list[AdminSubAgent]:
        names = [subagent.name for subagent in value]
        if len(set(names)) != len(names):
            raise ValueError("ID субагентов должны быть уникальными")
        return value


class SkillContentIn(BaseModel):
    content: str = Field(min_length=1, max_length=131_072)


class SkillSummaryOut(BaseModel):
    name: str
    description: str


class SkillOut(SkillSummaryOut):
    content: str
