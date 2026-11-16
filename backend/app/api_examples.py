"""Confined, read-only search over the installed DOCs API sample projects."""

from collections import Counter
from pathlib import Path, PurePosixPath
import re
import unicodedata


EXAMPLE_PROJECTS = (
    "Graphs",
    "ImportReference",
    "ReferenceObjectsGenerator",
    "UnitConverter",
)
_QUERY_TOKEN = re.compile(r"[^\W_]+(?:[_][^\W_]+)*", re.UNICODE)
_MAX_SOURCE_FILES = 1_000
_MAX_SOURCE_FILE_BYTES = 2_000_000
_MAX_READ_LINES = 120


def _has_symlink_component(path: Path, stop: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current == stop:
            return False
        current = current.parent


def _split_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    normalized = normalized.casefold()
    return tuple(_QUERY_TOKEN.findall(normalized))


def _query_terms(query: str) -> tuple[str, ...]:
    normalized = _split_tokens(query)
    return tuple(dict.fromkeys(normalized))


def _source_files(root: Path, project: str) -> list[Path]:
    if project and project not in EXAMPLE_PROJECTS:
        raise ValueError(f"Неизвестный проект примеров: {project}")
    if not root.is_dir():
        raise FileNotFoundError(f"Каталог примеров DOCs API недоступен: {root}")

    projects = (project,) if project else EXAMPLE_PROJECTS
    files: list[Path] = []
    resolved_root = root.resolve()
    for project_name in projects:
        project_root = (resolved_root / project_name).resolve()
        if not project_root.is_relative_to(resolved_root):
            raise ValueError("Каталог проекта находится вне корня примеров")
        if not project_root.is_dir():
            continue
        for path in project_root.rglob("*.cs"):
            if (
                ".Designer." in path.name
                or any(part.casefold() in {"bin", "obj"} for part in path.parts)
                or _has_symlink_component(path, project_root)
            ):
                continue
            resolved_path = path.resolve()
            if (
                resolved_path.is_relative_to(project_root)
                and resolved_path.stat().st_size <= _MAX_SOURCE_FILE_BYTES
            ):
                files.append(resolved_path)
                if len(files) > _MAX_SOURCE_FILES:
                    raise ValueError(
                        f"Каталог примеров содержит более {_MAX_SOURCE_FILES} "
                        "исходников; укажи конкретный проект"
                    )
    return files


def search_api_examples(
    query: str,
    root: Path,
    project: str = "",
    limit: int = 10,
) -> list[tuple[str, int, str]]:
    """Return matching project-relative C# source lines with line numbers."""
    if not query.strip():
        raise ValueError("query не может быть пустым")
    if len(query) > 500:
        raise ValueError("query не должен превышать 500 символов")
    if not 1 <= limit <= 20:
        raise ValueError("limit должен быть от 1 до 20")
    terms = _query_terms(query)
    exact_terms = tuple(
        dict.fromkeys(
            _QUERY_TOKEN.findall(unicodedata.normalize("NFC", query).casefold())
        )
    )
    if not terms:
        raise ValueError("query не содержит поисковых терминов")
    if len(terms) > 32:
        raise ValueError("Сократи запрос до 32 поисковых терминов")
    exact_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(term) for term in exact_terms) + r")(?!\w)"
    )
    call_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(term) for term in exact_terms) + r")\s*\("
    )

    resolved_root = root.resolve()
    ranked_files: list[tuple[int, int, str, list[tuple[int, str]]]] = []
    for path in _source_files(resolved_root, project):
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        normalized_source = unicodedata.normalize("NFC", source.casefold())
        source_counts = Counter(_split_tokens(source))
        term_counts = {term: source_counts[term] for term in terms}
        exact_counts = Counter(
            match.group() for match in exact_pattern.finditer(normalized_source)
        )
        exact_coverage = sum(count > 0 for count in exact_counts.values())
        coverage = sum(count > 0 for count in term_counts.values())
        if coverage == 0:
            continue

        matching_lines = []
        for line_no, line in enumerate(source.splitlines(), start=1):
            normalized_line = unicodedata.normalize("NFC", line.casefold())
            exact_matches = len(exact_pattern.findall(normalized_line))
            call_matches = len(call_pattern.findall(normalized_line))
            split_matches = sum(
                term in _split_tokens(line)
                for term, count in term_counts.items()
                if count
            )
            line_score = exact_matches * 10 + call_matches * 8 + split_matches
            if line_score:
                matching_lines.append((line_score, line_no, line.strip()))
                if len(matching_lines) > 2:
                    matching_lines.sort(key=lambda hit: (-hit[0], hit[1]))
                    del matching_lines[2:]
        if not matching_lines:
            continue
        matching_lines.sort(key=lambda hit: (-hit[0], hit[1]))
        relative_path = path.relative_to(resolved_root).as_posix()
        score = exact_coverage * 1_000 + coverage * 100 + sum(term_counts.values())
        ranked_files.append(
            (
                score,
                coverage,
                relative_path,
                [(line_no, line) for _, line_no, line in matching_lines],
            )
        )

    ranked_files.sort(
        key=lambda item: (-item[0], -item[1], item[2].casefold())
    )
    results: list[tuple[str, int, str]] = []
    for _, _, path, matching_lines in ranked_files:
        for line_no, line in matching_lines[:2]:
            results.append((path, line_no, line[:300]))
            if len(results) >= limit:
                return results
    return results


def read_api_example(
    path: str,
    root: Path,
    start_line: int = 1,
    line_limit: int = 80,
) -> tuple[str, int, int, int]:
    """Read a bounded line range from one non-generated C# sample source."""
    if not 1 <= start_line:
        raise ValueError("start_line должен быть не меньше 1")
    if not 1 <= line_limit <= _MAX_READ_LINES:
        raise ValueError(f"line_limit должен быть от 1 до {_MAX_READ_LINES}")

    relative = PurePosixPath(path.replace("\\", "/"))
    if (
        relative.is_absolute()
        or len(relative.parts) < 2
        or relative.parts[0] not in EXAMPLE_PROJECTS
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix.casefold() != ".cs"
        or ".Designer." in relative.name
    ):
        raise ValueError("Укажи путь к обычному .cs файлу одного из проектов примеров")

    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*relative.parts)
    project_root = resolved_root / relative.parts[0]
    if (
        _has_symlink_component(candidate, project_root)
        or not candidate.resolve().is_relative_to(project_root.resolve())
        or not candidate.is_file()
    ):
        raise FileNotFoundError(f"Исходник примера не найден: {path}")
    resolved_path = candidate.resolve()
    if resolved_path.stat().st_size > _MAX_SOURCE_FILE_BYTES:
        raise ValueError("Файл примера превышает допустимый размер")

    lines = resolved_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if start_line > len(lines):
        raise ValueError(f"start_line превышает число строк файла ({len(lines)})")
    end_line = min(len(lines), start_line + line_limit - 1)
    text = "\n".join(
        f"{line_no}: {lines[line_no - 1]}"
        for line_no in range(start_line, end_line + 1)
    )
    return text, start_line, end_line, len(lines)
