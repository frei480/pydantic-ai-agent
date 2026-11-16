---
name: tflex-docs-reference-import
description: Use when designing an import into T-FLEX DOCs references from Excel, Access, or another external source.
---

# Import data into a T-FLEX DOCs reference

Use the `ImportReference` sample as an implementation lead, not as the API
specification. Its source is `ImportReference/ReferenceImporter.cs`.

1. Confirm the target is T-FLEX DOCs and identify the installed DOCs/API version.
2. Search `search_api_examples` for `ReferenceBuilder`, `ParameterInfoBuilder`,
   `EndChanges`, or the user's source format. Read only the relevant source lines.
3. Verify every DOCs API type, member, and change lifecycle in the TFlexDOCs API
   documentation with `search_doc_topics`, `search_indexed_pages`, and
   `search_docs`/`read_file`. Cite documentation separately from the sample.
4. Design and validate the source-to-reference mapping before creating data:
   required fields, types, nulls, duplicate keys, encoding, and invalid rows.
5. Keep source access (OleDb, Excel, Access, files, or network) separate from
   T-FLEX DOCs operations. The sample's Jet/OleDb provider and 32-bit/.NET
   Framework requirements are environment-specific, not DOCs API requirements.
6. Describe how failures and partial imports are reported. Do not copy silent
   row skipping or assume a multi-row import is transactional; verify supported
   rollback and cleanup behavior before claiming it.

Do not present code from the sample as drop-in code for another DOCs version.
