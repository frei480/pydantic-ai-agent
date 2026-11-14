"""Focused tests for domain-aware search through documentation indexes."""

import tempfile
from pathlib import Path

import sys

sys.path.insert(0, "backend")

from app.doc_catalog import (
    load_doc_catalog,
    preload_doc_catalogs,
    search_doc_topics,
    search_indexed_pages,
)


def check_nested_index_search():
    with tempfile.TemporaryDirectory() as directory:
        docs_root = Path(directory)
        product_root = docs_root / "TFlexDOCs API"
        product_root.mkdir()
        (product_root / "index.md").write_text(
            "  * [Макроязык](macro.md)\n"
            "    * [Параметры](parameters.md)\n"
            "      * [Объект.Параметр](A1B2C3D4-1234-5678-90AB-CDEF12345678.md)\n"
            "    * [Поиск объектов](search.md)\n"
            "  * [Фильтры](filters.md)\n"
            "  * [Внешняя ссылка](https://example.com/api.md)\n"
            "  * [Выход из каталога](../outside.md)\n",
            encoding="utf-8",
        )

        topics, total = search_doc_topics(
            "поиск объектов", "TFlexDOCs API", docs_root
        )
        macro_topics, _ = search_doc_topics(
            "макроязык", "TFlexDOCs API", docs_root
        )

    assert total == 5
    assert topics[0].path == "search.md"
    breadcrumbs = {topic.path: topic.breadcrumb for topic in macro_topics}
    assert breadcrumbs["search.md"] == "Макроязык > Поиск объектов"
    assert breadcrumbs["parameters.md"] == "Макроязык > Параметры"
    assert breadcrumbs["A1B2C3D4-1234-5678-90AB-CDEF12345678.md"] == (
        "Макроязык > Параметры > Объект.Параметр"
    )


def check_validation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        product_root = root / "TFlexDOCs API"
        product_root.mkdir()
        (product_root / "index.md").write_text("* [API](api.md)\n", encoding="utf-8")

        invalid_queries = (
            ("", "TFlexDOCs API", root, 10),
            ("API", "unknown", root, 10),
            ("API", "TFlexDOCs API", root, 0),
        )
        for search in (search_doc_topics, search_indexed_pages):
            for args in invalid_queries:
                try:
                    search(*args)
                except ValueError:
                    continue
                raise AssertionError(
                    f"invalid catalog query was accepted by {search.__name__}: {args}"
                )


def check_namespace_tables():
    with tempfile.TemporaryDirectory() as directory:
        docs_root = Path(directory)
        product_root = docs_root / "TFlexDOCs API"
        product_root.mkdir()
        (product_root / "index.md").write_text(
            "* [Пространства имен](namespaces.md)\n", encoding="utf-8"
        )
        (product_root / "namespaces.md").write_text(
            "# Пространства имен\n"
            "| Пространство | Описание |\n"
            "| --- | --- |\n"
            "| [TFlex.DOCs.Model.Macros](macros.md) | Макросы |\n",
            encoding="utf-8",
        )
        (product_root / "macros.md").write_text(
            "# TFlex.DOCs.Model.Macros\n"
            "Макросы\n"
            "| | Класс | Описание |\n"
            "| --- | --- | --- |\n"
            "| | [MacroProvider](A1B2C3D4.md) | Базовый тип макроса |\n",
            encoding="utf-8",
        )

        topics, total = search_doc_topics(
            "базовый тип макроса", "TFlexDOCs API", docs_root
        )

    assert total == 3
    assert topics[0].path == "A1B2C3D4.md"
    assert topics[0].breadcrumb == (
        "Пространства имен > TFlex.DOCs.Model.Macros > Макросы > Класс > MacroProvider"
    )


def check_full_page_search_builds_metadata_and_finds_examples():
    with tempfile.TemporaryDirectory() as directory:
        docs_root = Path(directory)
        product_root = docs_root / "TFlexDOCs API"
        product_root.mkdir()
        (product_root / "index.md").write_text(
            "* [API](api.md)\n"
            "* [Другое руководство](other.md)\n",
            encoding="utf-8",
        )
        (product_root / "api.md").write_text(
            "Руководство по API\n\n"
            "# Соединение с сервером\n\n"
            "---\n\n"
            "В макросах соединение ServerConnection можно получить из контекста. "
            "[Пример подключения](api.htm#ServerConnectionFromMacro).\n\n"
            "```cs\nignored ServerConnection sample\n```\n",
            encoding="utf-8",
        )
        (product_root / "other.md").write_text(
            "# Отчёты\n\nСоздание и настройка отчётов.\n",
            encoding="utf-8",
        )
        cad_root = docs_root / "TFlexCAD API"
        cad_root.mkdir()
        (cad_root / "index.md").write_text(
            "* [Документы](document.md)\n",
            encoding="utf-8",
        )
        (cad_root / "document.md").write_text(
            "# Документы\n\nОткрытие и сохранение CAD-документов.\n",
            encoding="utf-8",
        )

        catalog = load_doc_catalog("TFlexDOCs API", docs_root)
        catalog_counts = preload_doc_catalogs(docs_root)
        results, total = search_indexed_pages(
            "ServerConnection пример подключения из макроса",
            "TFlexDOCs API",
            docs_root,
        )
        code_results, _ = search_indexed_pages(
            "ignored sample", "TFlexDOCs API", docs_root
        )

    page = catalog["api.md"]
    assert total == 2
    assert catalog_counts == {"TFlexCAD API": 1, "TFlexDOCs API": 2}
    assert results[0].page.path == "api.md"
    assert "ServerConnection" in page.keywords
    assert page.headings[0].title == "Соединение с сервером"
    assert "ServerConnection" in page.content
    assert "ignored" not in page.intro
    assert "ServerConnection" in results[0].excerpt
    assert results[0].section == "Соединение с сервером"
    assert code_results[0].page.path == "api.md"
    assert "ignored" in code_results[0].excerpt


check_nested_index_search()
check_validation()
check_namespace_tables()
check_full_page_search_builds_metadata_and_finds_examples()
print("DOC-CATALOG-OK")
