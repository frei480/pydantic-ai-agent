"""Search linked documentation topics in product indexes and namespace catalogs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
import unicodedata
from urllib.parse import unquote, urlsplit

from .doc_tools import bm25_rank_documents

_LINKED_ITEM = re.compile(
    r"^(?P<indent>\s*)[-*]\s+\[(?P<title>.+?)\]\((?P<target>[^)]+)\)\s*$"
)
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<title>\S.*)$")
_MARKDOWN_LINK = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<target>[^)]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>\S.*)$")
_IDENTIFIER = re.compile(
    r"(?<![\w])(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*"
)
_KEYWORD_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_COMMON_CODE_KEYWORDS = frozenset(
    "async await bool byte case catch char class const decimal default delegate "
    "double else enum event false finally float for foreach get if in int interface "
    "internal is long namespace new null object private protected public readonly "
    "return sealed set short static string struct this throw true try using var void "
    "while api assemblyresolver docs flex main md model open program tflex".split()
)
_TABLE_KINDS = ("Класс", "Интерфейс", "Перечисление", "Структура", "Делегат")
SUPPORTED_PRODUCTS = ("TFlexCAD API", "TFlexDOCs API")


@dataclass(frozen=True)
class DocTopic:
    title: str
    path: str
    breadcrumb: str
    description: str = ""


@dataclass(frozen=True)
class DocHeading:
    title: str
    line: int


@dataclass(frozen=True)
class IndexedDocPage:
    title: str
    path: str
    breadcrumb: str
    content: str
    headings: tuple[DocHeading, ...]
    keywords: tuple[str, ...]
    intro: str


@dataclass(frozen=True)
class DocSearchResult:
    page: IndexedDocPage
    excerpt: str
    excerpt_start_line: int
    excerpt_end_line: int
    section: str


def load_doc_catalog(
    product: str, docs_root: Path
) -> Mapping[str, IndexedDocPage]:
    """Load all index-linked pages and their search metadata into memory."""
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"Неизвестный продукт документации: {product}")

    product_root = (docs_root / product).resolve()
    index_path = product_root / "index.md"
    if not index_path.is_file():
        raise FileNotFoundError(f"Оглавление документации не найдено: {index_path}")
    stat = index_path.stat()
    pages = _load_doc_catalog_cached(
        index_path,
        product_root,
        stat.st_mtime_ns,
        stat.st_size,
    )
    return MappingProxyType(pages)


def preload_doc_catalogs(docs_root: Path) -> dict[str, int]:
    """Preload all supported product catalogs and return their page counts."""
    return {
        product: len(load_doc_catalog(product, docs_root))
        for product in SUPPORTED_PRODUCTS
    }


@lru_cache(maxsize=4)
def _load_doc_catalog_cached(
    index_path: Path,
    product_root: Path,
    modified_ns: int,
    size: int,
) -> dict[str, IndexedDocPage]:
    del modified_ns, size
    entries: dict[str, DocTopic] = {}
    for entry in _parse_list_index(index_path, product_root):
        previous = entries.get(entry.path)
        if previous is None or len(entry.breadcrumb) > len(previous.breadcrumb):
            entries[entry.path] = entry

    pages: dict[str, IndexedDocPage] = {}
    for entry in entries.values():
        page_path = (product_root / entry.path).resolve()
        if not page_path.is_file() or not page_path.is_relative_to(product_root):
            continue
        content = page_path.read_text(encoding="utf-8-sig", errors="replace")
        headings = _extract_headings(content)
        intro = _extract_intro(content)
        keywords = _extract_keywords(entry, headings, content)
        pages[entry.path] = IndexedDocPage(
            title=entry.title,
            path=entry.path,
            breadcrumb=entry.breadcrumb,
            content=content,
            headings=headings,
            keywords=keywords,
            intro=intro,
        )
    return pages


def search_indexed_pages(
    query: str,
    product: str,
    docs_root: Path,
    limit: int = 10,
) -> tuple[list[DocSearchResult], int]:
    """Search full page contents and return relevant excerpts with source lines."""
    if not query.strip():
        raise ValueError("query не может быть пустым")
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"Неизвестный продукт документации: {product}")
    if not 1 <= limit <= 20:
        raise ValueError("limit должен быть от 1 до 20")

    catalog = load_doc_catalog(product, docs_root)
    documents = [
        (
            path,
            f"{page.title}\n{page.breadcrumb}\n"
            f"{' '.join(page.keywords)}\n{page.content}",
        )
        for path, page in catalog.items()
    ]
    ranked = bm25_rank_documents(query, documents)
    results: list[DocSearchResult] = []
    for score, path, _ in ranked:
        if score <= 0:
            continue
        page = catalog[path]
        excerpt, start_line, end_line = _find_relevant_excerpt(page.content, query)
        section = next(
            (
                heading.title
                for heading in reversed(page.headings)
                if heading.line <= start_line
            ),
            "",
        )
        results.append(DocSearchResult(page, excerpt, start_line, end_line, section))
        if len(results) >= limit:
            break
    return results, len(catalog)


def _extract_headings(content: str) -> tuple[DocHeading, ...]:
    headings: list[DocHeading] = []
    in_code_fence = False
    for line_no, line in enumerate(content.splitlines(), start=1):
        if line.strip().startswith(("```", "~~~")):
            in_code_fence = not in_code_fence
            continue
        if not in_code_fence and (match := _HEADING.match(line)):
            headings.append(DocHeading(match.group("title").strip(), line_no))
    return tuple(headings)


def _extract_intro(content: str) -> str:
    paragraph: list[str] = []
    character_count = 0
    in_code_fence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not stripped:
            if paragraph:
                break
            continue
        if not paragraph and (
            _HEADING.match(stripped)
            or set(stripped) <= {"-", "*", "_"}
            or stripped.casefold().startswith("руководство по")
            or stripped.startswith("|")
        ):
            continue
        paragraph.append(stripped)
        character_count += len(stripped)
        if character_count >= 1200:
            break
    text = " ".join(paragraph)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = re.sub(r"[`*_~]", "", text)
    return text[:1200]


def _extract_keywords(
    topic: DocTopic,
    headings: tuple[DocHeading, ...],
    content: str,
) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}

    def add(keyword: str, weight: int = 1) -> None:
        normalized = keyword.casefold()
        if (
            normalized in _COMMON_CODE_KEYWORDS
            or len(normalized) <= 2
            or re.fullmatch(r"[0-9a-f]{4,8}", normalized)
        ):
            return
        counts[normalized] += weight
        current = labels.get(normalized)
        if current is None or (
            keyword[:1].isupper() and not current[:1].isupper()
        ):
            labels[normalized] = keyword

    for heading in headings:
        add(heading.title, 4)
        for token in _KEYWORD_TOKEN.findall(heading.title):
            add(token, 4)
    for token in _KEYWORD_TOKEN.findall(f"{topic.title} {topic.breadcrumb}"):
        add(token, 2)
    for identifier in _IDENTIFIER.findall(_extract_intro(content)):
        add(identifier, 8)
    for identifier in _IDENTIFIER.findall(content):
        parts = identifier.split(".")
        for candidate in [identifier, *parts]:
            add(candidate)
    return tuple(
        labels[key]
        for key, _ in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:64]
    )


def _find_relevant_excerpt(content: str, query: str) -> tuple[str, int, int]:
    lines = content.splitlines()
    candidates = [
        (str(line_no), line.strip())
        for line_no, line in enumerate(lines, start=1)
        if line.strip()
    ]
    ranked = bm25_rank_documents(query, candidates)
    if not ranked or ranked[0][0] <= 0:
        return "", 1, 1

    match_line = int(ranked[0][1])
    start = max(1, match_line - 2)
    end = min(len(lines), match_line + 2)
    while end - start > 1 and sum(
        len(lines[line_no - 1]) + 1 for line_no in range(start, end + 1)
    ) > 1200:
        if match_line - start > end - match_line:
            start += 1
        else:
            end -= 1
    excerpt = "\n".join(
        f"{line_no}: {lines[line_no - 1]}"
        for line_no in range(start, end + 1)
    )
    return excerpt, start, end


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
