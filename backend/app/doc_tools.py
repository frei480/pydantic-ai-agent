"""Доступ к файлам документации. Безопасность:

- Идеальных jail'ов не бывает, поэтому образовано несколько барьеров:
  1) разрешены только чтения: нет ни bash, ни исполнения чего-либо;
  2) путь всегда резолвится и проверяется на принадлежность DOCS_ROOT
     (учитываются symlinks через resolve());
  3) в контейнер документация монтируется в режиме read-only;
  4) поиск выполняется ripgrep-ом как subprocess (exec, не shell).
"""

import asyncio
import math
import re
from pathlib import Path, PureWindowsPath

from pydantic_ai import ModelRetry

from .config import (
    CHARS_PER_TOKEN,
    DOCS_ROOT,
    READ_TOKEN_BUDGET,
    SEARCH_MAX_RESULTS,
    SEARCH_TIMEOUT,
    SNIPPET_MAX_CHARS,
)

_BM25_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_BM25_STOP_WORDS = frozenset(
    "а без более бы был была были было быть в вам вас весь во вот все всего "
    "вы где да даже для до его ее если есть еще же за и из или им их к как "
    "ко когда кто ли либо мне может мы на над надо наш не него нее нет ни но "
    "о об однако он она они оно от по под при про с со так также такой там те "
    "то того тоже той только том ты у уже что чтобы эта эти это я".split()
)
_RUSSIAN_SUFFIXES = tuple(
    sorted(
        "иями ями ами евами ово ему ому ими ыми их ых ая яя ое ее ые ие "
        "ый ий ой ей ам ям ах ях ов ев ем ом им ым ую юю а я ы и е у ю".split(),
        key=len,
        reverse=True,
    )
)
_BM25_MAX_CANDIDATES = 1000
_BM25_MAX_DOCUMENT_CHARS = 128_000


def rel_display(path: Path) -> str:
    """Путь для показа агенту/пользователю — относительно корня документации."""
    try:
        return str(path.relative_to(DOCS_ROOT))
    except ValueError:
        return str(path)


def safe_resolve(rel: str) -> Path:
    """Резолвит путь внутри корня документации, иначе raises ModelRetry."""
    rel = (rel or "").strip()
    path_text = rel.replace("\\", "/")
    requested = Path(path_text)
    windows_requested = PureWindowsPath(rel)
    if not rel or rel == ".":
        candidate = DOCS_ROOT
    elif requested.is_absolute():
        candidate = requested
    elif windows_requested.is_absolute():
        candidate = _resolve_external_path(windows_requested.parts) or requested
    else:
        candidate = DOCS_ROOT / path_text.lstrip("/")
    try:
        candidate = candidate.resolve()
    except OSError:
        raise ModelRetry(f"Некорректный путь: {rel!r}")
    if candidate != DOCS_ROOT and DOCS_ROOT not in candidate.parents:
        path_parts = (
            windows_requested.parts
            if windows_requested.is_absolute()
            else candidate.parts
        )
        mapped = _resolve_external_path(path_parts)
        if mapped is not None:
            try:
                candidate = mapped.resolve()
            except OSError:
                raise ModelRetry(f"Некорректный путь: {rel!r}")
    if candidate != DOCS_ROOT and DOCS_ROOT not in candidate.parents:
        raise ModelRetry(
            f"Доступ запрещён: путь «{rel}» вне каталога документации. "
            f"Корень документации: {DOCS_ROOT.name}/ — используйте пути от него."
        )
    if not candidate.exists():
        raise ModelRetry(
            f"Путь «{rel_display(candidate)}» не найден. Сначала поищите search_docs/list_dir."
        )
    return candidate


def _resolve_external_path(parts: tuple[str, ...]) -> Path | None:
    """Сопоставляет абсолютный путь хоста с каталогом документации."""
    doc_dirs = {entry.name for entry in DOCS_ROOT.iterdir() if entry.is_dir()}
    for index, part in enumerate(parts):
        if part in doc_dirs:
            return DOCS_ROOT.joinpath(*parts[index:])
    return None


def _stem_russian(word: str) -> str:
    if not re.fullmatch(r"[а-яё]+", word):
        return word
    for suffix in _RUSSIAN_SUFFIXES:
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _bm25_tokens(text: str) -> list[str]:
    return [
        _stem_russian(token)
        for token in _BM25_TOKEN_RE.findall(text.casefold())
        if token not in _BM25_STOP_WORDS and len(token) > 1
    ]


def bm25_rank_documents(
    query: str, documents: list[tuple[str, str]]
) -> list[tuple[float, str, str]]:
    """Rank candidate document texts using BM25, returning score, path, and text."""
    query_terms = set(_bm25_tokens(query))
    if not query_terms or not documents:
        return [(0.0, path, text) for path, text in documents]

    tokenized = [_bm25_tokens(path + "\n" + text) for path, text in documents]
    average_length = sum(map(len, tokenized)) / len(tokenized) or 1.0
    token_sets = [set(tokens) for tokens in tokenized]
    document_frequencies = {
        term: sum(term in tokens for tokens in token_sets)
        for term in query_terms
    }

    ranked: list[tuple[float, str, str]] = []
    for (path, text), tokens in zip(documents, tokenized):
        frequencies: dict[str, int] = {}
        for token in tokens:
            if token in query_terms:
                frequencies[token] = frequencies.get(token, 0) + 1
        score = 0.0
        for term, frequency in frequencies.items():
            inverse_document_frequency = math.log(
                1
                + (len(documents) - document_frequencies[term] + 0.5)
                / (document_frequencies[term] + 0.5)
            )
            length_normalization = 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / average_length
            )
            score += (
                inverse_document_frequency
                * frequency
                * 2.5
                / (frequency + length_normalization)
            )
        ranked.append((score, path, text))

    return sorted(ranked, key=lambda result: (-result[0], result[1].casefold()))


async def ripgrep_search(
    pattern: str,
    *,
    glob: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    rank_query: str = "",
    max_results: int = SEARCH_MAX_RESULTS,
    offset: int = 0,
) -> tuple[list[tuple[str, int, str]], bool]:
    """Полнотекстовый поиск по документации через ripgrep.

    Возвращает страницу результатов и признак наличия следующей страницы.
    Поиск по всему поддереву DOCS_ROOT, скрытые каталоги (git) игнорируются.
    """
    if offset < 0:
        raise ValueError("offset не может быть отрицательным")
    max_results = max(1, max_results)
    ranked_search = bool(rank_query.strip())
    args = ["rg", "--no-messages"]
    if ranked_search:
        args.append("--files-with-matches")
    else:
        args += ["--no-heading", "-n", "--color", "never"]
    if literal:
        args.append("-F")
    if not case_sensitive:
        args.append("-i")
    if glob:
        args += ["-g", glob]
    args += ["--", pattern, str(DOCS_ROOT)]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )
    killed = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=SEARCH_TIMEOUT)
        return_code = proc.returncode
    except (asyncio.TimeoutError, TimeoutError):
        killed = True
        proc.kill()
        out, err = await proc.communicate()
        return_code = None

    if return_code is not None and return_code not in (0, 1):
        message = (err or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ripgrep ошибка (код {return_code}): {message}")

    text = (out or b"").decode("utf-8", "replace")
    # нормализуем разделители, чтобы парсинг был одинаковым на Linux и Windows
    root_prefix = str(DOCS_ROOT).replace("\\", "/").rstrip("/") + "/"
    if ranked_search:
        relative_paths = []
        for raw_path in text.splitlines():
            raw_norm = raw_path.replace("\\", "/")
            if raw_norm.startswith(root_prefix):
                relative_paths.append(raw_norm[len(root_prefix):])
        relative_paths = relative_paths[:_BM25_MAX_CANDIDATES]
        documents = await asyncio.to_thread(_read_rank_candidates, relative_paths)
        ranked_documents = bm25_rank_documents(rank_query, documents)
        page_documents = ranked_documents[offset : offset + max_results]
        page_paths = [path for _, path, _ in page_documents]
        page = await _ripgrep_first_match_lines(
            pattern,
            page_paths,
            literal=literal,
            case_sensitive=case_sensitive,
        )
        return page, offset + len(page_documents) < len(ranked_documents)

    results: list[tuple[str, int, str]] = []
    matching_lines = 0
    has_more = False
    for raw in text.splitlines():
        raw_norm = raw.replace("\\", "/")
        # формат: <путь>:<номер>:<текст>. Отрезаем известный префикс корня, чтобы
        # ':' внутри абсолютных путей (Windows «D:») не мешал разбору.
        if not raw_norm.startswith(root_prefix):
            continue
        remainder = raw_norm[len(root_prefix):]
        parts = remainder.split(":", 2)
        if len(parts) < 3 or not parts[0] or not parts[1].isdigit():
            continue
        path_part, line_no_raw, line_part = parts[0], int(parts[1]), parts[2]
        matching_lines += 1
        if matching_lines <= offset:
            continue
        if len(results) >= max_results:
            has_more = True
            break
        snippet = line_part.strip()
        if len(snippet) > SNIPPET_MAX_CHARS:
            snippet = snippet[: SNIPPET_MAX_CHARS - 1] + "…"
        results.append((path_part, line_no_raw, snippet))
    return results, has_more


def _read_rank_candidates(relative_paths: list[str]) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    for relative_path in relative_paths:
        path = (DOCS_ROOT / relative_path).resolve()
        if DOCS_ROOT not in path.parents or not path.is_file():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as file:
            text = file.read(_BM25_MAX_DOCUMENT_CHARS)
        documents.append((relative_path, text))
    return documents


async def _ripgrep_first_match_lines(
    pattern: str,
    relative_paths: list[str],
    *,
    literal: bool,
    case_sensitive: bool,
) -> list[tuple[str, int, str]]:
    if not relative_paths:
        return []
    args = [
        "rg",
        "--no-heading",
        "-n",
        "--color",
        "never",
        "--no-messages",
        "--max-count",
        "1",
    ]
    if literal:
        args.append("-F")
    if not case_sensitive:
        args.append("-i")
    paths = [str(DOCS_ROOT / path) for path in relative_paths]
    args += ["--", pattern, *paths]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=SEARCH_TIMEOUT
        )
    except (asyncio.TimeoutError, TimeoutError):
        proc.kill()
        await proc.communicate()
        raise TimeoutError("ripgrep превысил время поиска совпадающих строк")
    if proc.returncode not in (0, 1):
        message = (err or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"ripgrep ошибка (код {proc.returncode}): {message}"
        )

    root_prefix = str(DOCS_ROOT).replace("\\", "/").rstrip("/") + "/"
    results: list[tuple[str, int, str]] = []
    for raw in (out or b"").decode("utf-8", "replace").splitlines():
        raw_norm = raw.replace("\\", "/")
        if not raw_norm.startswith(root_prefix):
            continue
        parts = raw_norm[len(root_prefix) :].split(":", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        snippet = parts[2].strip()
        if len(snippet) > SNIPPET_MAX_CHARS:
            snippet = snippet[: SNIPPET_MAX_CHARS - 1] + "…"
        results.append((parts[0], int(parts[1]), snippet))
    result_by_path = {result[0]: result for result in results}
    return [result_by_path[path] for path in relative_paths if path in result_by_path]


def estimate_tokens(text: str) -> int:
    """Консервативная оценка числа токенов для смешанного текста."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ToolOutputBudget:
    """Ограничивает совокупный размер результатов поиска в одном запросе."""

    def __init__(self, context_window_tokens: int):
        self.context_window_tokens = context_window_tokens
        self.remaining_tokens = max(1, context_window_tokens // 12)
        self.seen_calls: set[tuple[object, ...]] = set()
        self.tool_calls = 0
        self.max_tool_calls = 16

    @property
    def read_token_limit(self) -> int:
        return min(
            READ_TOKEN_BUDGET,
            self.remaining_tokens,
            self.context_window_tokens * 5 // 100,
        )

    def is_duplicate_call(self, key: tuple[object, ...]) -> bool:
        if key in self.seen_calls:
            return True
        self.seen_calls.add(key)
        return False

    def allow_tool_call(self) -> bool:
        if self.tool_calls >= self.max_tool_calls:
            return False
        self.tool_calls += 1
        return True

    def limit(self, text: str) -> str:
        remaining_chars = int(self.remaining_tokens * CHARS_PER_TOKEN)
        if remaining_chars <= 0:
            return "Бюджет контекста поиска исчерпан; продолжай по уже найденным фактам."
        if len(text) > remaining_chars:
            marker = "\n[результат сокращён: исчерпан бюджет контекста поиска]"
            text = text[: max(0, remaining_chars - len(marker))] + marker[:remaining_chars]
        self.remaining_tokens = max(0, self.remaining_tokens - estimate_tokens(text))
        return text


async def count_lines(path: Path) -> int:
    def _count() -> int:
        n = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                n += chunk.count(b"\n")
        return n + 1

    return await asyncio.to_thread(_count)


async def read_lines(
    path: Path,
    start_line: int = 1,
    line_limit: int | None = None,
    token_budget: int | None = None,
) -> tuple[str, int, int, int]:
    def _read() -> list[str]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines

    lines = await asyncio.to_thread(_read)
    total = len(lines)
    start = max(1, start_line)
    effective_token_budget = min(
        READ_TOKEN_BUDGET,
        token_budget if token_budget is not None else READ_TOKEN_BUDGET,
    )
    max_lines = max(1, int(effective_token_budget * CHARS_PER_TOKEN) // 60)
    if line_limit is not None and line_limit > 0:
        max_lines = min(max_lines, line_limit)
    end = min(total, start - 1 + max_lines)
    selected = "".join(lines[start - 1 : end])
    # дополнительно ужмём по бюджету символов, если строки длинные
    budget_chars = int(effective_token_budget * CHARS_PER_TOKEN)
    if len(selected) > budget_chars:
        keep = selected[:budget_chars].splitlines(keepends=True)
        selected = "".join(keep)
        end = start - 1 + len(keep)
    return selected, start, end, total
