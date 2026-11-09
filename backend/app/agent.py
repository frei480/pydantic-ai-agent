"""Агентский цикл: исследователь -> критик -> (уточнение поиска) -> писатель.

Пайплайн:
 1. RESEARCH-агент ищет по документации инструментами (ripgrep, чтение файлов)
    и выдаёт черновик фактов со ссылками файл:строка.
 2. CRITIC-агент оценивает, достаточно ли собранного для написания РАБОЧЕГО кода
    (структурированный вердикт). Если нет — перечисляет пробелы и конкретные
    поисковые запросы, RESEARCH продолжает цикл (до MAX_CRITIC_ROUNDS итераций).
 3. WRITER-агент пишет финальный ответ с рабочим кодом со списком источников.

Все фазы стримятся событиями для SSE.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent, messages as ai_messages
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config import (
    CRITIC_MODEL_NAME,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    MAX_CRITIC_ROUNDS,
    MODEL_NAME,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MAX_RETRIES,
    RAW_CRITIC_MODEL,
)
from .doc_tools import (
    ToolOutputBudget,
    count_lines,
    estimate_tokens,
    read_lines,
    rel_display,
    ripgrep_search,
    safe_resolve,
)

SHOW_LIMIT = 60


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS


_model_settings = ModelSettings(
    provider="openai",
    model=MODEL_NAME,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
)


def current_model_settings() -> ModelSettings:
    return _model_settings


def configure_model(settings: ModelSettings) -> None:
    global _model_settings
    _model_settings = settings


# -------------------------------------------------------------------
# Инструкции
# -------------------------------------------------------------------

RESEARCH_INSTRUCTIONS = """Ты — агент-исследователь API-документации (T-FLEX CAD / T-FLEX DOCs Open API, C#).
Корпус: тысячи markdown-файлов в каталогах документации; имена файлов — GUID, поэтому
ориентируйся только на ПОИСК ПО СОДЕРЖИМОМУ и листинг каталогов, а не на имена файлов.

Твоя задача: найти документацию, необходимую, чтобы написать РАБОЧИЙ код под вопрос пользователя.

Правила работы:
1. Начинай исследование с корневых файлов документации: прочитай index.md (оглавление)
   и search.md (поисковый индекс), используя file_info и read_file. По ним определи
   релевантные разделы и термины для поиска; только после этого переходи к search_docs.
2. Используй search_docs для поиска по ключевым словам из вопроса, затем уточняй запросы.
   Примеры в документации — C# (классы, свойства, методы, перечисления). Ищи также по
   именам классов/методов, которые встретились в найденных примерах.
3. Каждое утверждение подтверждай чтением файла через read_file. НИКОГДА не выдумывай
   сигнатуры методов, имена классов, свойства или порядок вызовов.
4. Перед чтением файла вызывай file_info, чтобы оценить его объём; большие файлы читай
   частями через параметры start_line/line_limit.
5. Состав каталогов смотри через list_dir; полнотекстовый поиск — только через search_docs.

В конце хода ОБЯЗАТЕЛЬНО выдай черновик ровно в таком формате:
ФАКТЫ: (маркированный список подтверждённых фактов, каждый со ссылкой файл:строка)
ЕДИНЦЫ API: (классы/методы/свойства/перечисления с найденными сигнатурами)
ПРОБЕЛЫ: (что осталось неизвестным/неподтверждённым)

Отвечай на языке пользователя (по умолчанию — русский).
"""

CRITIC_INSTRUCTIONS = """Ты — строгий технический критик результата исследования документации API.
Тебе дан вопрос пользователя и черновик фактов, найденных агентом-исследователем.

Оцени черновик по критериям:
- достаточность: хватит ли сведений, чтобы написать РАБОЧИЙ код требуемого;
- подтверждённость: все классы/методы/свойства и сигнатуры снабжены ссылками файл:строка;
- полнота: понятен ли сценарий работы с API (получение документа, создание объектов,
  начало/конец транзакции изменений, владельцы объектов), учтены ли зависимости и перечисления;
- согласованность: не смешаны ли разные подсистемы/версии API.

Верди is_sufficient=true ТОЛЬКО если все критерии выполнены и ты уверен, что по этим фактам
можно собрать рабочий код. Иначе перечисли в missing_info конкретные пробелы, а в
search_queries предложи 1-5 конкретных поисковых запросов (ключевые слова или regex для
ripgrep), которые закроют пробелы. Не дублируй в suggestions уже найденное."""

WRITER_INSTRUCTIONS = """Ты — инженер-технический писатель. По вопросу пользователя и фактам,
собранным из документации API (в контексте), напиши ФИНАЛЬНЫЙ ответ:
- краткое объяснение, как задача решается средствами API;
- рабочий код на C# (T-FLEX CAD Open API) в блоке ```csharp с комментариями;
- список источников: файл документации (путь:строка) для каждого ключевого факта.

Код должен использовать ТОЛЬКО классы/методы/свойства, подтверждённые фактами из контекста.
Если какой-то элемент кода не удалось подтвердить документацией — отметь это явно
предупреждением рядом с кодом. Инструменты используй лишь для быстрой проверки отдельной
детали. Без длинных вступлений — сразу к делу. Отвечай на языке пользователя
(по умолчанию русский)."""


class Critique(BaseModel):
    """Структурированный вердикт критика."""

    is_sufficient: bool = Field(description="Достаточно ли фактов для рабочего кода")
    missing_info: list[str] = Field(default_factory=list, description="Конкретные пробелы")
    search_queries: list[str] = Field(
        default_factory=list, description="Предложенные поисковые запросы"
    )
    comments: str = Field(default="", description="Краткий вердикт для пользователя")


# -------------------------------------------------------------------
# Модель
# -------------------------------------------------------------------


def _build_model(name: str, settings: ModelSettings | None = None) -> OpenAIChatModel:
    provider = _build_provider(settings)
    return OpenAIChatModel(name, provider=provider)


class _RetryTransientErrorsAsyncOpenAI(AsyncOpenAI):
    def _should_retry(self, response: Any) -> bool:
        if response.status_code == 429:
            return response.headers.get("x-should-retry") == "true"
        return super()._should_retry(response)


def _build_provider(settings: ModelSettings | None = None) -> OpenAIProvider:
    settings = settings or current_model_settings()
    client = _RetryTransientErrorsAsyncOpenAI(
        api_key=settings.api_key or "sk-no-key",
        base_url=settings.base_url,
        max_retries=OPENAI_MAX_RETRIES,
    )
    return OpenAIProvider(openai_client=client)


async def probe_model() -> bool:
    settings = current_model_settings()
    provider = _build_provider(settings)
    try:
        response = await provider.client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "Reply with exactly: HEALTH_OK"}],
            max_tokens=8,
            timeout=10,
        )
        return any(
            text and text.strip()
            for choice in response.choices or []
            for text in (
                getattr(choice.message, "content", None),
                getattr(choice.message, "reasoning_content", None),
            )
        )
    finally:
        await provider.client.close()


# -------------------------------------------------------------------
# Инструменты
# -------------------------------------------------------------------


def register_tools(agent: Agent, budget: ToolOutputBudget) -> None:
    @agent.tool_plain
    async def search_docs(
        pattern: str,
        glob: str = "",
        literal: bool = False,
        case_sensitive: bool = False,
    ) -> str:
        """Полнотекстовый поиск ripgrep по всей документации.

        pattern: regex или текст (при literal=true). Ищет по содержимому файлов.
        glob: необязательный фильтр имён файлов, например "*.md".
        Возвращает совпадения в формате путь:строка:текст.
        """
        if not pattern.strip():
            raise ValueError("pattern не может быть пустым")
        results = await ripgrep_search(
            pattern.strip(),
            glob=glob.strip() or None,
            literal=literal,
            case_sensitive=case_sensitive,
        )
        if not results:
            return budget.limit(
                "Совпадений не найдено. Попробуй другие ключевые слова, "
                "literal=true или поиск без glob."
            )
        lines = [f"{path}:{n}: {text}" for path, n, text in results]
        header = f"Найдено {len(lines)} совпадений (показано до {SHOW_LIMIT}):"
        return budget.limit(header + "\n" + "\n".join(lines))

    @agent.tool_plain
    async def list_dir(path: str) -> str:
        """Листинг каталога документации. Корень — «» или «.»."""
        p = safe_resolve(path)
        if not p.is_dir():
            raise ValueError(f"{rel_display(p)} — не каталог")
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        hidden = [e for e in entries if e.name.startswith(".")]
        visible = [e for e in entries if not e.name.startswith(".")]
        cap = 200
        out = [f"Каталог «{rel_display(p) or '.'}»: записей {len(visible)}"]
        for e in visible[:cap]:
            if e.is_dir():
                out.append(f"[DIR] {e.name}/")
            else:
                out.append(f"{e.name} ({e.stat().st_size} байт)")
        if len(visible) > cap:
            out.append(
                f"…показаны первые {cap} из {len(visible)}. В каталогах тысячи файлов "
                "с GUID-именами — используй search_docs по содержимому."
            )
        if hidden:
            out.append(f"Служебные скрытые: {[e.name for e in hidden]}")
        return budget.limit("\n".join(out))

    @agent.tool_plain
    async def file_info(path: str) -> str:
        """Оценка объёма файла: байты, строки, примерные токены и доля от
        контекстного окна. Вызывай ПЕРЕД чтением больших файлов."""
        p = safe_resolve(path)
        if not p.is_file():
            raise ValueError(f"{rel_display(p)} — не файл")
        size = p.stat().st_size
        line_count = await count_lines(p)
        context_window_tokens = budget.context_window_tokens
        tokens = estimate_tokens("x" * size)
        share = tokens / context_window_tokens * 100 if context_window_tokens else 0
        warnings = []
        if tokens > context_window_tokens * 0.5:
            warnings.append(
                "ФАЙЛ КРУПНЫЙ: чтение целиком переполнит контекстное окно — "
                "читай частями: read_file(path, start_line, line_limit)."
            )
        elif tokens > context_window_tokens * 0.2:
            warnings.append("Файл крупный — лучше читать по частям.")
        return budget.limit(
            f"Файл «{rel_display(p)}»: {size} байт, {line_count} строк, "
            f"примерно {tokens} токенов (~{share:.1f}% от контекстного окна). "
            + (" ".join(warnings) if warnings else "")
        )

    @agent.tool_plain
    async def read_file(path: str, start_line: int = 1, line_limit: int = 0) -> str:
        """Чтение файла документации.

        line_limit=0 — попытка прочитать файл ЦЕЛИКОМ (полное чтение); если файл не
        влезает в бюджет контекста — вернётся первая порция с подсказкой продолжения
        (остаток читай через read_file(path, start_line=...)). line_limit>0 читает
        не более line_limit строк с позиции start_line.
        """
        p = safe_resolve(path)
        if not p.is_file():
            raise ValueError(f"{rel_display(p)} — не файл")
        token_budget = budget.read_token_limit
        if token_budget <= 0:
            return budget.limit("Бюджет контекста поиска исчерпан; продолжай по уже найденным фактам.")
        text, start, end, total = await read_lines(
            p,
            start_line=start_line,
            line_limit=line_limit or None,
            token_budget=token_budget,
        )
        header = f"«{rel_display(p)}», строки {start}–{end} из {total}:"
        if end < total and (line_limit <= 0 or start_line > 1):
            header += (
                f" ПОРЦИЯ УСЕЧЕНА по бюджету контекста. Продолжай: read_file(«{path}», "
                f"start_line={end + 1}) или прочти отдельные смысловые фрагменты."
            )
        return budget.limit(header + "\n" + text)


# -------------------------------------------------------------------
# Стриминг хода агента
# -------------------------------------------------------------------


async def _stream_text(node, run) -> AsyncIterator[str]:
    """Дельты текста из узла модельного запроса (pydantic-ai v2)."""
    async with node.stream(run.ctx) as stream:
        async for event in stream:
            if isinstance(event, ai_messages.PartStartEvent) and isinstance(
                event.part, ai_messages.TextPart
            ):
                yield event.part.content
            elif isinstance(event, ai_messages.PartDeltaEvent) and isinstance(
                event.delta, ai_messages.TextPartDelta
            ):
                yield event.delta.content_delta


class TurnResult:
    def __init__(self) -> None:
        self.output: str = ""
        self.messages_json: bytes = b""


async def _iter_agent_turn(
    agent: Agent, prompt: str, history: list[Any] | None
) -> AsyncIterator[tuple[str, Any]]:
    """Один ход агента: события (text|tool|result); в конце ('messages', json)."""
    result = TurnResult()
    async with agent.iter(user_prompt=prompt, message_history=history) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                async for delta in _stream_text(node, run):
                    result.output += delta
                    yield ("text", delta)
            elif Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as event_stream:
                    async for event in event_stream:
                        if isinstance(event, ai_messages.FunctionToolCallEvent):
                            detail = f"{event.part.tool_name}({str(event.part.args)[:160]})"
                            yield ("tool", detail)
        run_result = run.result
        if run_result is None:
            raise RuntimeError("ход агента не завершился результатом")
        all_msgs = run_result.all_messages()
        result.messages_json = ModelMessagesTypeAdapter.dump_json(all_msgs)
        result.output = result.output or _output_of(all_msgs)
    yield ("result", result)


def _is_user_prompt_message(message: Any) -> bool:
    return getattr(message, "kind", None) == "request" and any(
        getattr(part, "part_kind", None) == "user-prompt"
        for part in getattr(message, "parts", ())
    )


def _fit_context(
    history: list[Any] | None,
    prompt: str,
    instructions: str,
    max_input_tokens: int,
) -> tuple[list[Any] | None, str, bool, bool]:
    messages = list(history or [])
    dropped_history = False

    def input_tokens() -> int:
        serialized = ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")
        return estimate_tokens(serialized + instructions + prompt)

    while messages and input_tokens() > max_input_tokens:
        prompt_starts = [
            index for index, message in enumerate(messages) if _is_user_prompt_message(message)
        ]
        if len(prompt_starts) > 1:
            messages = messages[prompt_starts[1] :]
        else:
            messages = []
        dropped_history = True

    prompt_truncated = False
    if input_tokens() > max_input_tokens:
        serialized = ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")
        available_chars = max(
            0,
            max_input_tokens * 4 - len(serialized) - len(instructions) - 64,
        )
        prompt = prompt[:available_chars] + "\n[Текст сокращён по лимиту контекста.]"
        prompt_truncated = True

    return messages or None, prompt, dropped_history, prompt_truncated


def _output_of(messages: list[Any]) -> str:
    """Текст последнего сообщения модели (черновик хода)."""
    for msg in reversed(messages):
        if getattr(msg, "parts", None):
            for part in reversed(msg.parts):
                if part.__class__.__name__ == "TextPart":
                    return str(getattr(part, "content", "")) or ""
    return ""


# -------------------------------------------------------------------
# Пайплайн
# -------------------------------------------------------------------


async def run_pipeline(
    user_text: str, history_json: str
) -> AsyncIterator[dict[str, Any]]:
    """Агентский цикл. Генератор событий для SSE; последнее событие — «final»."""
    settings = current_model_settings()
    context_window_tokens = settings.context_window_tokens
    response_tokens = max(256, context_window_tokens // 5)
    input_tokens = context_window_tokens - response_tokens - context_window_tokens // 20
    research_input_tokens = input_tokens - context_window_tokens // 5
    tool_budget = ToolOutputBudget(context_window_tokens)
    model_settings = {"max_tokens": response_tokens}
    base_history: list[Any] = []
    if history_json:
        base_history = ModelMessagesTypeAdapter.validate_json(history_json)

    researcher = Agent(
        _build_model(settings.model, settings),
        instructions=RESEARCH_INSTRUCTIONS,
        model_settings=model_settings,
        retries=2,
    )
    register_tools(researcher, tool_budget)
    critic = Agent(
        _build_model(RAW_CRITIC_MODEL and CRITIC_MODEL_NAME or settings.model, settings),
        instructions=CRITIC_INSTRUCTIONS,
        model_settings=model_settings,
        output_type=Critique,
        retries=1,
    )
    writer = Agent(
        _build_model(settings.model, settings),
        instructions=WRITER_INSTRUCTIONS,
        model_settings=model_settings,
        retries=2,
    )
    register_tools(writer, tool_budget)

    prompt = user_text
    draft = ""
    research_history: list[Any] | None = base_history or None
    research_messages_json = b""
    round_no = 1

    for round_no in range(1, MAX_CRITIC_ROUNDS + 1):
        # --- фаза: исследование ---
        yield {"type": "phase", "phase": "research", "round": round_no}
        research_history, prompt, dropped, truncated = _fit_context(
            research_history, prompt, RESEARCH_INSTRUCTIONS, research_input_tokens
        )
        if dropped:
            yield {
                "type": "warning",
                "message": "Старая история чата сокращена, чтобы вместить запрос в окно контекста модели.",
            }
        if truncated:
            yield {
                "type": "warning",
                "message": "Текст запроса сокращён, чтобы вместить его в окно контекста модели.",
            }
        tool_events: list[str] = []
        async for kind, payload in _iter_agent_turn(researcher, prompt, research_history):
            if kind == "text":
                yield {"type": "draft", "text": payload}
            elif kind == "tool":
                tool_events.append(payload)
                yield {"type": "tool", "detail": payload}
            else:
                draft = payload.output
                research_messages_json = payload.messages_json
        research_history = (
            ModelMessagesTypeAdapter.validate_json(research_messages_json)
            if research_messages_json
            else research_history
        )

        # --- фаза: критика ---
        yield {"type": "phase", "phase": "critique", "round": round_no}
        critique_input = f"Вопрос пользователя:\n{user_text}\n\nЧерновик фактов:\n{draft}"
        if tool_events:
            critique_input += "\n\nВыполненные поиска:\n" + "\n".join(tool_events[-12:])
        _, critique_input, _, truncated = _fit_context(
            None, critique_input, CRITIC_INSTRUCTIONS, input_tokens
        )
        if truncated:
            yield {
                "type": "warning",
                "message": "Материалы для проверки сокращены по лимиту контекста модели.",
            }
        critique_res = await critic.run(critique_input)
        critique: Critique = critique_res.output
        yield {
            "type": "critique",
            "sufficient": critique.is_sufficient,
            "comments": critique.comments,
            "missing": critique.missing_info[:8],
            "round": round_no,
        }
        if critique.is_sufficient:
            break

        feedback = (
            "Критик отметил пробелы в исследовании. Продолжи поиск и устраняй их.\n"
            "Текущий черновик фактов:\n"
            + draft
            + "\nНедостающая информация:\n- "
            + "\n- ".join(critique.missing_info[:10] or ["уточнить детали API"])
            + "\nПредложенные поисковые запросы:\n- "
            + "\n- ".join(critique.search_queries[:5] or [])
            + "\nЗатем снова выдай черновик в прежнем формате "
            "(ФАКТЫ / ЕДИНЦЫ API / ПРОБЕЛЫ)."
        )
        prompt = feedback
        yield {"type": "phase", "phase": "refine", "round": round_no}

    # --- фаза: писатель ---
    yield {"type": "phase", "phase": "write", "round": round_no}
    writer_prompt = (
        f"Напиши финальный ответ на вопрос пользователя:\n{user_text}\n\n"
        f"Собранные факты из документации:\n{draft}"
    )
    research_history, writer_prompt, dropped, truncated = _fit_context(
        research_history, writer_prompt, WRITER_INSTRUCTIONS, research_input_tokens
    )
    if dropped:
        yield {
            "type": "warning",
            "message": "Старая история чата сокращена для подготовки ответа в пределах окна контекста.",
        }
    if truncated:
        yield {
            "type": "warning",
            "message": "Часть материалов ответа сокращена по лимиту контекста.",
        }
    acc: list[str] = []
    writer_all: list[Any] = []
    async with writer.iter(
        user_prompt=writer_prompt, message_history=research_history
    ) as wrun:
        async for node in wrun:
            if Agent.is_model_request_node(node):
                async for delta in _stream_text(node, wrun):
                    acc.append(delta)
                    yield {"type": "text", "text": delta}
        if wrun.result is None:
            raise RuntimeError("писатель не завершился результатом")
        writer_all = list(wrun.result.all_messages())

    writer_prefix_len = len(research_history) if research_history else 0
    writer_new = writer_all[writer_prefix_len:] if len(writer_all) > writer_prefix_len else []

    # Сохраняем только историю, которая поместилась в текущее окно модели.
    full_history = list(research_history or [])
    full_history.extend(writer_new)
    history_out = ModelMessagesTypeAdapter.dump_json(full_history).decode("utf-8")

    yield {
        "type": "final",
        "text": "".join(acc),
        "history_json": history_out,
    }
