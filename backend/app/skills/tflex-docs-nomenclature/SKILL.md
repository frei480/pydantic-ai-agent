---
name: tflex-docs-nomenclature
description: Use for T-FLEX DOCs tasks involving the "Электронная структура изделий" (Nomenclature) reference — object type GUIDs, field database names, field GUIDs/IDs, replacement lists, and link connections.
---

# Work with the T-FLEX DOCs Nomenclature (ЭСИ) reference

This skill ships two reference data files next to this guide:

- `/skills/tflex-docs-nomenclature/Типы ЭСИ.md` — GUIDs of Nomenclature object types (for example "Резистор", "Сборочная единица").
- `/skills/tflex-docs-nomenclature/структура ЭСИ.md` — database name, GUID, and ID of every field of the Nomenclature reference: main fields, additional parameters, "Замены" and "Параметры заготовки" object lists, parameter groups (Габариты, Масса, Единица измерения, …), and the "Подключения" connection table.

If the workspace tool cannot read these files, fall back to `search_docs` / `read_file` over the documentation instead of guessing values.

## How to use the data

1. **Resolve identifiers from the files, never from memory.** Take the GUID of an object type from `Типы ЭСИ.md`; take the database name, GUID, or ID of a field from `структура ЭСИ.md`. Quote the exact value as it appears in the file.
2. **Access fields by their database name or unique identifier** from section "1. Электронная структура изделия" of `структура ЭСИ.md`; use section "2. Дополнительные параметры" for additional parameters.
3. **List links**: use section "3. Список объектов: \"Замены\"" when working with replacements and section "4. Список объектов: \"Параметры заготовки\"" for blank parameters.
4. **Connections**: configure links between objects according to the "Подключения" table.
5. **The data files are metadata, not API proof.** They tell you which GUID/field to target, but every API call that uses them (creating an object, setting a parameter value, adding a linked object) must still be verified against the `TFlexDOCs API` documentation with `search_docs` and `read_file`. Follow the editing lifecycle rules of the `tflex-docs-reference-object-editing` skill for create/change operations.

## Verified example creation flow

From `ReferenceObjectsGenerator/ReferenceObjectsGenerator.cs:178-185` (catalog «Примеры использования API»; fetch with `read_api_example`): a Nomenclature object wraps an object of the reference linked to its type.

```csharp
if (classObject is NomenclatureType && ((NomenclatureType)classObject).LinkedReference != null)
{
    Reference linkedReference = ((NomenclatureType)classObject).LinkedReference;

    var linkedObject = linkedReference.CreateReferenceObject(((NomenclatureType)classObject).LinkedClass);
    linkedObject.EndChanges();
    var nomenclatureObject = ((NomenclatureReference)reference)
        .CreateNomenclatureObject(linkedObject, parentObject as NomenclatureReferenceObject);
}
```

Namespace: `TFlex.DOCs.Model.References.Nomenclature`. Verify `CreateNomenclatureObject` and the `NomenclatureType` members in the `TFlexDOCs API` documentation before use.

## Rules

- Never invent or guess a GUID, database name, or field ID. If a field is missing from `структура ЭСИ.md`, search for it with `search_doc_topics` / `search_docs` and report it as a gap if not found.
- When creating or modifying Nomenclature objects, follow the naming and types exactly as listed in the structure file.
- Cite the documentation file and line for each API member used in generated code, and name the data file you took each identifier from.
