"""Склейка system-сообщений в одно ведущее system-сообщение.

Некоторые серверные chat-шаблоны (Qwen 3.x и часть Llama-подобных) требуют,
чтобы system-сообщение было только первым: иначе Jinja-шаблон падает с
`System message must be at the beginning` и провайдер отвечает HTTP 500.
pydantic-ai при этом формирует несколько system-сообщений — инструкции
агента, подсказку о подагентах, контекст отложенных возможностей, — поэтому
такие модели не отвечают вовсе.

Модуль нормализует тело запроса к `chat.completions.create`: все system- и
developer-сообщения склеиваются в одно system-сообщение в начале списка,
остальные сообщения сохраняют порядок. Модуль не импортирует openai и
pydantic-ai — на границе используются точные типы (`Mapping[str, object]`
плюс Protocol для клиента), поэтому он проверяется обычным python и mypy
без зависимостей.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Final, Protocol

__all__ = [
    "ChatClient",
    "Content",
    "Message",
    "SYSTEM_ROLES",
    "merge_system_messages",
    "merge_system_messages_in_requests",
]

logger = logging.getLogger(__name__)

#: Сообщение запроса в формате OpenAI chat: роль, содержимое и служебные
#: поля (tool_calls, tool_call_id, name и т.п.).
type Message = Mapping[str, object]
#: Содержимое сообщения: строка, content-parts или их отсутствие.
type Content = str | Sequence[Mapping[str, object]] | None

#: Роли, содержимое которых chat-шаблон трактует как системную инструкцию.
#: `developer` — новое имя system в API OpenAI; в один блок его тоже склеиваем,
#: иначе строгий шаблон отвергнет незнакомую роль.
SYSTEM_ROLES: Final[frozenset[str]] = frozenset({"system", "developer"})

#: Разделитель между склеенными промптами: пустая строка визуально отделяет
#: блоки инструкций друг от друга и не даёт им слипнуться.
_MERGE_SEPARATOR: Final = "\n\n"


class _CompletionsResource(Protocol):
    """Ресурс `chat.completions` OpenAI-клиента (модулю нужен только `create`)."""

    @property
    def create(self) -> Callable[..., Awaitable[object]]:
        """Вызов модели; подменяется обёрткой в `merge_system_messages_in_requests`."""
        ...


class _ChatResource(Protocol):
    @property
    def completions(self) -> _CompletionsResource: ...


class ChatClient(Protocol):
    """Минимальная часть OpenAI-клиента, которая нужна модулю."""

    @property
    def chat(self) -> _ChatResource: ...


def _as_message_list(messages: object) -> list[Message] | None:
    """Привести значение kwargs к списку сообщений.

    None — форма неожиданная (не список, пустой список или элементы не
    отображения): такой запрос лучше не трогать, чем испортить.
    """
    if not isinstance(messages, list):
        return None
    normalized: list[Message] = []
    for message in messages:
        if not isinstance(message, Mapping):
            return None
        normalized.append(message)
    return normalized or None


def _content_text(content: object) -> str:
    """Текст system-сообщения независимо от формата `content`.

    Поддерживается строка и content-parts (список частей): переносятся только
    текстовые части, нетекстовые (image_url и подобные) отбрасываются —
    системная инструкция всё равно не может нести изображение.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def merge_system_messages(messages: Sequence[Message]) -> list[Message] | None:
    """Список сообщений с единственным ведущим system-сообщением.

    Возвращает None, если менять нечего: сообщений нет, system-ролей нет, либо
    system-сообщение уже единственное и стоит первым. Исходная
    последовательность и её элементы не изменяются: при склейке создаётся новое
    сообщение, остальные передаются по ссылке.
    """
    if not messages:
        return None

    system_count = 0
    system_texts: list[str] = []
    rest: list[Message] = []
    for message in messages:
        role = message.get("role")
        if isinstance(role, str) and role in SYSTEM_ROLES:
            system_count += 1
            text = _content_text(message.get("content"))
            if text:
                system_texts.append(text)
        else:
            rest.append(message)

    if not system_count:
        return None
    if system_count == 1 and messages[0].get("role") == "system":
        # уже ровно та форма, которую требует строгий шаблон
        return None
    if not system_texts:
        # все system-сообщения пустые — склеивать нечего
        return None
    return [{"role": "system", "content": _MERGE_SEPARATOR.join(system_texts)}, *rest]


def merge_system_messages_in_requests(client: ChatClient) -> None:
    """Обернуть `client.chat.completions.create`, склеивая system-сообщения.

    Обёртка ставится на ресурс клиента, как и `capture_llm_requests`: openai
    пересоздаёт клиента в `with_options`/`copy`, а `__init__` навешивает
    перехват заново. Возвращаемое значение и исключения проксируются как есть,
    остальные kwargs запроса не меняются.
    """
    inner = client.chat.completions.create

    @functools.wraps(inner)
    async def _create(**kwargs: object) -> object:
        request_messages = _as_message_list(kwargs.get("messages"))
        if request_messages is not None:
            merged = merge_system_messages(request_messages)
            if merged is not None:
                logger.debug(
                    "system-сообщения склеены: сообщений %d -> %d",
                    len(request_messages),
                    len(merged),
                )
                kwargs["messages"] = merged
        return await inner(**kwargs)

    # Подмена метода на ресурсе клиента: openai пересоздаёт клиента в
    # `with_options`/`copy`, и `__init__` навешивает перехват заново.
    # В протоколе `create` объявлен read-only, поэтому установка — через setattr.
    setattr(client.chat.completions, "create", _create)
