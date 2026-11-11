"""Focused tests for documentation search and reading helpers."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "backend")

from app import doc_tools  # noqa: E402


def check_search_pagination():
    original_root = doc_tools.DOCS_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        docs = root / "TFlexDOCs API"
        docs.mkdir()
        (docs / "example.md").write_text(
            "\n".join(["intro"] * 100 + ["rich first", "rich second", "rich third"])
            + "\n",
            encoding="utf-8",
        )
        doc_tools.DOCS_ROOT = root
        try:
            first_page, has_more = asyncio.run(
                doc_tools.ripgrep_search(
                    "rich", glob="**/TFlexDOCs API/**/*.md", max_results=2
                )
            )
            second_page, has_more_after = asyncio.run(
                doc_tools.ripgrep_search(
                    "rich",
                    glob="**/TFlexDOCs API/**/*.md",
                    max_results=2,
                    offset=2,
                )
            )
            text, start, end, _ = asyncio.run(
                doc_tools.read_lines(
                    docs / "example.md",
                    start_line=first_page[0][1] - 1,
                    line_limit=3,
                )
            )
        finally:
            doc_tools.DOCS_ROOT = original_root

    assert [line for _, line, _ in first_page] == [101, 102]
    assert has_more
    assert [line for _, line, _ in second_page] == [103]
    assert not has_more_after
    assert (start, end) == (100, 102)
    assert "rich first" in text
    assert "rich second" in text


def check_absolute_windows_path_resolution():
    original_root = doc_tools.DOCS_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        docs = root / "TFlexDOCs API"
        docs.mkdir()
        expected = docs / "71837294-B2E3-4AC0-A540-716B78185C1E.md"
        expected.write_text("RTF content\n", encoding="utf-8")
        doc_tools.DOCS_ROOT = root
        try:
            resolved = doc_tools.safe_resolve(
                r"D:\work\Obsidian\TFlexDOCs API"
                r"\71837294-B2E3-4AC0-A540-716B78185C1E.md"
            )
            text, _, _, _ = asyncio.run(doc_tools.read_lines(resolved))
        finally:
            doc_tools.DOCS_ROOT = original_root

    assert resolved == expected
    assert text == "RTF content\n"


def check_conservative_russian_read_budget():
    original_root = doc_tools.DOCS_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        source = root / "russian.md"
        source.write_text("текст документации\n" * 100, encoding="utf-8")
        doc_tools.DOCS_ROOT = root
        try:
            text, _, _, _ = asyncio.run(
                doc_tools.read_lines(source, token_budget=10)
            )
        finally:
            doc_tools.DOCS_ROOT = original_root

    assert len(text) <= 20
    assert doc_tools.estimate_tokens(text) <= 11


def check_search_case_sensitivity():
    original_root = doc_tools.DOCS_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        docs = root / "TFlexDOCs API"
        docs.mkdir()
        (docs / "case.md").write_text("RTF\nrtf\nRtf\n", encoding="utf-8")
        doc_tools.DOCS_ROOT = root
        try:
            insensitive, _ = asyncio.run(
                doc_tools.ripgrep_search(
                    "rtf", literal=True
                )
            )
            sensitive, _ = asyncio.run(
                doc_tools.ripgrep_search(
                    "rtf",
                    literal=True,
                    case_sensitive=True,
                )
            )
        finally:
            doc_tools.DOCS_ROOT = original_root

    assert [line for _, line, _ in insensitive] == [1, 2, 3]
    assert [line for _, line, _ in sensitive] == [2]


def check_tool_call_budget():
    budget = doc_tools.ToolOutputBudget(25_600)
    key = ("read_file", "TFlexDOCs API/example.md", 1, 0)

    assert budget.read_token_limit == 1_280
    assert not budget.is_duplicate_call(key)
    assert budget.is_duplicate_call(key)
    assert all(budget.allow_tool_call() for _ in range(16))
    assert not budget.allow_tool_call()


def check_bm25_ranking():
    original_root = doc_tools.DOCS_ROOT
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        docs = root / "TFlexDOCs API"
        docs.mkdir()
        (docs / "unrelated.md").write_text(
            "RTF is used in mail format configuration.\n" * 4,
            encoding="utf-8",
        )
        expected = docs / "parameter-rtf-guide.md"
        expected.write_text(
            "Работа с параметрами.\n"
            "Значение текстового параметра содержит RTF.\n"
            "RichEditDocumentServer загружает RTF для редактирования.\n",
            encoding="utf-8",
        )
        doc_tools.DOCS_ROOT = root
        try:
            results, has_more = asyncio.run(
                doc_tools.ripgrep_search(
                    "rtf",
                    glob="**/TFlexDOCs API/**/*.md",
                    rank_query=(
                        "найди информацию о работе с параметрами в DOCs "
                        "содержащими текст в формате rtf"
                    ),
                    max_results=5,
                )
            )
        finally:
            doc_tools.DOCS_ROOT = original_root

    assert results
    assert results[0][0] == "TFlexDOCs API/parameter-rtf-guide.md"
    assert not has_more


check_search_pagination()
check_absolute_windows_path_resolution()
check_conservative_russian_read_budget()
check_search_case_sensitivity()
check_tool_call_budget()
check_bm25_ranking()
print("DOC-TOOLS-OK")
