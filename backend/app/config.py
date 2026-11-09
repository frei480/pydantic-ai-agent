import os
from pathlib import Path

DOCS_ROOT = Path(os.getenv("DOCS_ROOT", "/app/docs")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", "/app/data/chats.db"))

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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip() or "sk-no-key"
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
OPENAI_MAX_RETRIES = max(0, int(os.getenv("OPENAI_MAX_RETRIES", "5")))

# --- лимиты контекста ---
# Оценка объёма: ~4 символа = 1 токен
CHARS_PER_TOKEN = 4.0
# Бюджет входного контекста модели (для file_info)
CONTEXT_TOKEN_LIMIT = int(os.getenv("CONTEXT_TOKEN_LIMIT", "120000"))
# Одна порция чтения файла (в токенах)
READ_TOKEN_BUDGET = int(os.getenv("READ_TOKEN_BUDGET", "20000"))

# --- поиск ---
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "80"))
SNIPPET_MAX_CHARS = 240
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))

MAX_CRITIC_ROUNDS = int(os.getenv("MAX_CRITIC_ROUNDS", "3"))
