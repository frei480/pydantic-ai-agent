---
name: tflex-cad-document-workflow
description: 'Use when writing C# for T-FLEX CAD documents: open or close a document, find model objects, create/delete objects, make changes, save, or handle document state.'
---

# Write T-FLEX CAD document workflows

Use the T-FLEX CAD documentation to build a complete, minimal C# workflow around a document. The general management and object pages are navigation aids; verify the exact calls needed by the requested scenario.

## Research and implementation

1. Identify the caller context: a running T-FLEX CAD add-in/macro, an external application, or a method that receives an existing `Document`. Do not assume how a document is acquired.
2. Use `search_doc_topics` with the scenario (for example, open and save a document, find an object by name, or create a model object). Follow the returned T-FLEX CAD path and read its example. Relevant topics include document management, changing a document, creating, getting, and deleting objects.
3. Use `search_docs` for the exact member names and read the API pages when the overload, return value, or failure behavior matters. Do not invent GUID filenames or infer a method signature from an index entry.
4. For creation or mutation, verify the documented change lifecycle for that operation. The creation guide places object creation between `Document.BeginChanges(...)` and `Document.EndChanges()`. Check the relevant scenario before applying the same pattern to a different operation.
5. Handle absent documents, missing objects, failed operations, and unsaved changes explicitly. Only use cancellation/rollback APIs when the relevant documentation confirms their semantics for this state.
6. Return complete, minimal C# code for the stated context. Include required setup, validate nullable results, and identify any installation-specific assumptions.
7. Cite the exact documentation path and line numbers. Distinguish example behavior from guaranteed API behavior.

## Avoid

- Mixing T-FLEX CAD APIs with T-FLEX DOCs APIs.
- Treating an object ID as globally unique; verify its documented scope.
- Closing or saving a document the caller did not ask the code to manage.
- Reporting success when the API result was not checked.
