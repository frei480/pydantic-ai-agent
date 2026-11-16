"""Verify confined search and bounded reads over DOCs API examples."""

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, "backend")

from app.api_examples import read_api_example, search_api_examples  # noqa: E402


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    sample = root / "ImportReference" / "ReferenceImporter.cs"
    sample.parent.mkdir()
    sample.write_text(
        "using System;\nvar builder = new ReferenceBuilder();\nbuilder.EndChanges();\n",
        encoding="utf-8",
    )
    (root / "UnitConverter").mkdir()
    (root / "UnitConverter" / "Converter.cs").write_text(
        "private bool BlockConvert = false;\n"
        "var output = target.Convert(value, source);\n",
        encoding="utf-8",
    )
    (root / "UnitConverter" / "UnitConverterDialog.Designer.cs").write_text(
        "ReferenceBuilder\n",
        encoding="utf-8",
    )

    results = search_api_examples("ReferenceBuilder", root)
    assert results[0] == (
        "ImportReference/ReferenceImporter.cs",
        2,
        "var builder = new ReferenceBuilder();",
    )
    assert search_api_examples("ReferenceBuilder", root, project="UnitConverter") == []
    convert_results = search_api_examples("Convert", root, project="UnitConverter")
    assert convert_results[0] == (
        "UnitConverter/Converter.cs",
        2,
        "var output = target.Convert(value, source);",
    )

    text, first, last, total = read_api_example(
        "ImportReference/ReferenceImporter.cs", root, start_line=2, line_limit=2
    )
    assert (first, last, total) == (2, 3, 3)
    assert "2: var builder" in text
    assert "3: builder.EndChanges()" in text

    try:
        read_api_example("../outside.cs", root)
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal must be rejected")

print("API-EXAMPLES-OK")
