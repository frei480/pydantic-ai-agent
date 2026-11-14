"""Focused tests for domain-aware search through documentation indexes."""

import tempfile
from pathlib import Path

import sys

sys.path.insert(0, "backend")

from app.doc_catalog import search_doc_topics


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

        for args in (
            ("", "TFlexDOCs API", root, 10),
            ("API", "unknown", root, 10),
            ("API", "TFlexDOCs API", root, 0),
        ):
            try:
                search_doc_topics(*args)
            except ValueError:
                continue
            raise AssertionError(f"invalid catalog query was accepted: {args}")


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


check_nested_index_search()
check_validation()
check_namespace_tables()
print("DOC-CATALOG-OK")
