"""Доступ к файлам документации. Безопасность:

- Идеальных jail'ов не бывает, поэтому образовано несколько барьеров:
  1) разрешены только чтения: нет ни bash, ни исполнения чего-либо;
  2) путь всегда резолвится и проверяется на принадлежность DOCS_ROOT
     (учитываются symlinks через resolve());
  3) в контейнер документация монтируется в режиме read-only;
  4) поиск выполняется ripgrep-ом как subprocess (exec, не shell).
"""

import asyncio
from pathlib import Path
from typing import Iterable

from pydantic_ai import ModelRetry

from .config import (
    CONTEXT_TOKEN_LIMIT,
    DOCS_ROOT,
    READ_TOKEN_BUDGET,
    SEARCH_MAX_RESULTS,
    SEARCH_TIMEOUT,
    SNIPPET_MAX_CHARS,
)


def rel_display(path: Path) -> str:
    """Путь для показа агенту/пользователю — относительно корня документации."""
    try:
        return str(path.relative_to(DOCS_ROOT))
    except ValueError:
        return str(path)


def safe_resolve(rel: str) -> Path:
    """Резолвит путь внутри корня документации, иначе raises ModelRetry."""
    rel = (rel or "").strip().replace("\\", "/").strip("/")
    candidate: Path
    if not rel or rel == ".":
        candidate = DOCS_ROOT
    elif Path(rel).is_absolute():
        candidate = Path(rel)
    else:
        candidate = DOCS_ROOT / rel
    try:
        candidate = candidate.resolve()
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


async def ripgrep_search(
    pattern: str,
    *,
    glob: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = SEARCH_MAX_RESULTS,
) -> Iterable[tuple[str, int, str]]:
    """Полнотекстовый поиск по документации через ripgrep.

    Возвращает максимум max_results пар (путь, строка, текст совпадения).
    Поиск по всему поддереву DOCS_ROOT, скрытые каталоги (git) игнорируются.
    """
    args = ["rg", "--no-heading", "-n", "--color", "never", "--no-messages"]
    args.append("-F" if literal else "-S")
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
    results: list[tuple[str, int, str]] = []
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
        snippet = line_part.strip()
        if len(snippet) > SNIPPET_MAX_CHARS:
            snippet = snippet[: SNIPPET_MAX_CHARS - 1] + "…"
        results.append((path_part, line_no_raw, snippet))
        if len(results) >= max_results:
            break
    return results


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов: эвристика ~4 символа на токен."""
    return int(len(text) / 4.0) + 1


async def count_lines(path: Path) -> int:
    def _count() -> int:
        n = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                n += chunk.count(b"\n")
        return n + 1

    return await asyncio.to_thread(_count)


async def read_lines(
    path: Path, start_line: int = 1, line_limit: int | None = None
) -> tuple[str, int, int, int]:
    def _read() -> list[str]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines

    lines = await asyncio.to_thread(_read)
    total = len(lines)
    start = max(1, start_line)
    max_lines = READ_TOKEN_BUDGET * 4 // 60  # приблизительно: строка ~60 символов
    if line_limit is not None and line_limit > 0:
        max_lines = min(max_lines, line_limit)
    end = min(total, start - 1 + max_lines)
    selected = "".join(lines[start - 1 : end])
    # дополнительно ужмём по бюджету символов, если строки длинные
    budget_chars = READ_TOKEN_BUDGET * 4
    if len(selected) > budget_chars:
        keep = selected[:budget_chars].splitlines(keepends=True)
        selected = "".join(keep)
        end = start - 1 + len(keep)
    return selected, start, end, total
