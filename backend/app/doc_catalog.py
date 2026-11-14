"""Search linked documentation topics in product indexes and namespace catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .doc_tools import bm25_rank_documents

_LINKED_ITEM = re.compile(
    r"^(?P<indent>\s*)[-*]\s+\[(?P<title>.+?)\]\((?P<target>[^)]+)\)\s*$"
)
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<title>\S.*)$")
_MARKDOWN_LINK = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<target>[^)]+)\)")
_TABLE_KINDS = ("Класс", "Интерфейс", "Перечисление", "Структура", "Делегат")
SUPPORTED_PRODUCTS = ("TFlexCAD API", "TFlexDOCs API")


@dataclass(frozen=True)
class DocTopic:
    title: str
    path: str
    breadcrumb: str
    description: str = ""


def search_doc_topics(
    query: str,
    product: str,
    docs_root: Path,
    limit: int = 10,
) -> tuple[list[DocTopic], int]:
    """Return relevant linked pages and their breadcrumb in the product index."""
    if not query.strip():
        raise ValueError("query не может быть пустым")
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"Неизвестный продукт документации: {product}")
    if not 1 <= limit <= 20:
        raise ValueError("limit должен быть от 1 до 20")

    product_root = (docs_root / product).resolve()
    index_path = product_root / "index.md"
    if not index_path.is_file():
        raise FileNotFoundError(f"Оглавление документации не найдено: {index_path}")

    entries = list(_parse_list_index(index_path, product_root))
    namespace_index = next(
        (entry for entry in entries if _is_namespace_index(entry.title)), None
    )
    if namespace_index is not None:
        namespace_path = (product_root / namespace_index.path).resolve()
        if namespace_path.is_file() and namespace_path.is_relative_to(product_root):
            namespace_entries = _parse_table_index(
                namespace_path, product_root, namespace_index.breadcrumb
            )
            entries.extend(namespace_entries)
            for namespace in namespace_entries:
                page = (product_root / namespace.path).resolve()
                if page.is_file() and page.is_relative_to(product_root):
                    entries.extend(
                        _parse_table_index(page, product_root, namespace.breadcrumb)
                    )

    unique_entries: dict[str, DocTopic] = {}
    for entry in entries:
        previous = unique_entries.get(entry.path)
        if previous is None or len(entry.breadcrumb) > len(previous.breadcrumb):
            unique_entries[entry.path] = entry
    catalog = list(unique_entries.values())

    documents = [
        (entry.path, f"{entry.breadcrumb}\n{entry.description}\n{entry.path}")
        for entry in catalog
    ]
    ranked = bm25_rank_documents(query, documents)
    by_path = {entry.path: entry for entry in catalog}
    relevant = [
        by_path[path] for score, path, _ in ranked if score > 0
    ][:limit]
    return relevant, len(catalog)


@lru_cache(maxsize=4)
def _parse_list_index(
    index_path: Path,
    product_root: Path,
) -> tuple[DocTopic, ...]:
    stat = index_path.stat()
    return _parse_list_index_cached(
        index_path, product_root, stat.st_mtime_ns, stat.st_size
    )


@lru_cache(maxsize=4)
def _parse_list_index_cached(
    index_path: Path,
    product_root: Path,
    modified_ns: int,
    size: int,
) -> tuple[DocTopic, ...]:
    del modified_ns, size
    stack: list[tuple[int, str]] = []
    entries: list[DocTopic] = []

    with index_path.open("r", encoding="utf-8-sig", errors="replace") as index:
        for line in index:
            match = _LINKED_ITEM.match(line.rstrip())
            if match:
                indent = len(match.group("indent").expandtabs(4))
                title = match.group("title").strip()
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                path = _resolve_index_link(
                    index_path, product_root, match.group("target")
                )
                if path is not None:
                    breadcrumb = " > ".join(
                        [ancestor for _, ancestor in stack] + [title]
                    )
                    entries.append(DocTopic(title, path, breadcrumb))
                stack.append((indent, title))
                continue

            list_item = _LIST_ITEM.match(line.rstrip())
            if list_item:
                indent = len(list_item.group("indent").expandtabs(4))
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                stack.append((indent, list_item.group("title").strip()))
            elif line.lstrip().startswith("#"):
                stack.clear()

    return tuple(entries)


@lru_cache(maxsize=512)
def _parse_table_index_cached(
    index_path: Path,
    product_root: Path,
    breadcrumb_prefix: str,
    modified_ns: int,
    size: int,
) -> tuple[DocTopic, ...]:
    del modified_ns, size
    entries: list[DocTopic] = []
    section = ""
    table_kind = ""

    with index_path.open("r", encoding="utf-8-sig", errors="replace") as index:
        for line in index:
            stripped = line.strip()
            if not stripped.startswith("|"):
                if (
                    stripped
                    and not stripped.startswith("#")
                    and not stripped.casefold().startswith("руководство по")
                    and not set(stripped) <= {"-"}
                ):
                    section = stripped
                continue

            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            normalized_cells = [_normalize(cell) for cell in cells]
            kind = next(
                (
                    candidate
                    for candidate in _TABLE_KINDS
                    if _normalize(candidate) in normalized_cells
                ),
                None,
            )
            if kind is not None:
                table_kind = kind
                continue

            for cell_index, cell in enumerate(cells):
                match = _MARKDOWN_LINK.search(cell)
                if match is None:
                    continue
                path = _resolve_index_link(
                    index_path, product_root, match.group("target")
                )
                if path is None:
                    continue
                description = next(
                    (
                        text
                        for next_cell in cells[cell_index + 1 :]
                        if (text := _MARKDOWN_LINK.sub("", next_cell).strip())
                    ),
                    "",
                )
                parts = [breadcrumb_prefix]
                if section:
                    parts.append(section)
                if table_kind:
                    parts.append(table_kind)
                parts.append(match.group("title").strip())
                entries.append(
                    DocTopic(
                        title=match.group("title").strip(),
                        path=path,
                        breadcrumb=" > ".join(parts),
                        description=description,
                    )
                )
                break

    return tuple(entries)


def _parse_table_index(
    index_path: Path, product_root: Path, breadcrumb_prefix: str
) -> tuple[DocTopic, ...]:
    stat = index_path.stat()
    return _parse_table_index_cached(
        index_path,
        product_root,
        breadcrumb_prefix,
        stat.st_mtime_ns,
        stat.st_size,
    )


def _resolve_index_link(
    index_path: Path, product_root: Path, target: str
) -> str | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    relative_path = PurePosixPath(path)
    if relative_path.suffix.lower() != ".md" or relative_path.is_absolute():
        return None
    candidate = (index_path.parent / Path(*relative_path.parts)).resolve()
    if not candidate.is_relative_to(product_root):
        return None
    return candidate.relative_to(product_root).as_posix()


def _is_namespace_index(title: str) -> bool:
    normalized = _normalize(title).replace("ё", "е")
    return "пространств" in normalized and "имен" in normalized


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()
