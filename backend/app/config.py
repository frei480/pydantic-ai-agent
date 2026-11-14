import os
from pathlib import Path

DOCS_ROOT = Path(os.getenv("DOCS_ROOT", "/app/docs")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", "/app/data/chats.db"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# --- модель ---
RAW_MODEL = os.getenv("AI_MODEL", "openai:gpt-4o-mini").strip()
# принимаем вид "openai:<имя>" или просто <имя> (OpenAI-совместимый провайдер)
MODEL_NAME = RAW_MODEL.split(":", 1)[1] if RAW_MODEL.lower().startswith("openai:") else RAW_MODEL
RAW_CRITIC_MODEL = (os.getenv("CRITIC_MODEL") or "").strip()
CRITIC_MODEL_NAME = (
    RAW_CRITIC_MODEL.split(":", 1)[1]
    if RAW_CRITIC_MODEL.lower().startswith("openai:")
    else (RAW_CRITIC_MODEL or MODEL_NAME)
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
OPENAI_MAX_RETRIES = max(0, int(os.getenv("OPENAI_MAX_RETRIES", "5")))
AGENT_REQUEST_LIMIT = max(1, int(os.getenv("AGENT_REQUEST_LIMIT", "100")))

# --- лимиты контекста ---
# Консервативная оценка для смешанного текста, включая русский: 2 символа на токен.
CHARS_PER_TOKEN = 2.0
# Бюджет входного контекста модели (для file_info)
CONTEXT_TOKEN_LIMIT = int(os.getenv("CONTEXT_TOKEN_LIMIT", "120000"))
DEFAULT_CONTEXT_WINDOW_TOKENS = CONTEXT_TOKEN_LIMIT
# Лимиты генерации ответа: увеличены относительно жёстких 1024/4096, чтобы не
# упираться в лимит модели до формирования ответа, но при этом остаются
# безопасными для окна контекста. Переопределяются из env для конкретной модели.
MAX_AGENT_RESPONSE_TOKENS = max(256, int(os.getenv("MAX_AGENT_RESPONSE_TOKENS", "4096")))
MAX_CRITIC_RESPONSE_TOKENS = max(256, int(os.getenv("MAX_CRITIC_RESPONSE_TOKENS", "2048")))
# Одна порция чтения файла (в токенах)
READ_TOKEN_BUDGET = int(os.getenv("READ_TOKEN_BUDGET", "20000"))

# --- поиск ---
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "80"))
SNIPPET_MAX_CHARS = 240
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))

MAX_CRITIC_ROUNDS = int(os.getenv("MAX_CRITIC_ROUNDS", "3"))
