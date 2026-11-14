---
name: tflex-docs-reference-object-editing
description: Use for T-FLEX DOCs Open API tasks that edit reference objects, parameters, links, object types, owners, or handle delete and unlock operations in C#.
---

# Edit T-FLEX DOCs reference objects safely

Use this workflow for changes to existing T-FLEX DOCs reference objects. The overview example is `TFlexDOCs API/663e0b41-ed90-4985-bdca-da4741702f3e.md`; verify each operation in the linked API documentation before generating code.

## Editing an existing object

1. Establish how the object is obtained in the requested context (for example, `Context.ReferenceObject` in a macro or a reference lookup). Check for a missing object where applicable.
2. Check `CanEdit` before starting an edit. Do not silently skip a failed check; explain the outcome or follow the caller's established error-handling pattern.
3. Call `BeginChanges()` before editing an existing object. A freshly created object does not need this step. If using the documented `BeginChanges(false)` overload, verify that avoiding a reload is valid for this object's state.
4. Perform parameter and link changes inside a `try` block. Resolve the real parameter and link GUIDs from the documentation or the target reference; never leave `Guid.Empty` from an example in executable code.
5. On success, call `EndChanges()` exactly once. On exception, cancel changes only when `Changing` is true, then rethrow the original error.

The source example demonstrates parameter access through the object's indexer and typed getters, `SetLinkedObject` for single-object links, and `AddLinkedObject` / `RemoveLinkedObject` for collection links. Confirm the link cardinality and API signatures before choosing an operation. Do not treat `GetObject` and `GetObjects` as interchangeable.

## Changing an object's type

The documented type-change overload of `BeginChanges(newType)` returns the object with the new type. Continue all edits and finish the change using that returned object, not the original reference. Check for a failed cast or missing type metadata before dereferencing it.

## Delete, unlock, and ownership

- **Delete:** check `CanDelete` first. The overview says this path applies to non-versioned objects; for versioned objects, investigate the versioned-object workflow and `CanCheckOut` before proposing a deletion.
- **Unlock:** `CanUnlock` and `Unlock()` apply to non-versioned objects. For versioned objects, investigate `UndoCheckOut()` and the versioned-object workflow instead.
- **Owner:** check whether the reference parameter group supports an owner and whether the desired user is already the owner before calling `SetOwnerUser`. For bulk assignment, research the documented batch API.

These are server mutations. Generate code that performs them only when requested, identifies the target object and intended values clearly, and handles unavailable permissions or invalid state explicitly.

## Research and answer checklist

1. Search `**/TFlexDOCs API/**/*.md` for `ReferenceObject` and the exact operation, then read its linked member and scenario documentation.
2. Confirm edit state, versioning restrictions, link cardinality, GUID source, null behavior, and whether the operation is single-object or batch.
3. Keep macro-only context types out of external-application examples; follow the user's stated execution context.
4. Return a complete minimal example with the required `using` directives, explicit failure handling, and correct commit/cancel lifecycle.
5. Cite documentation paths and line numbers for verified facts. Treat the overview page as navigation, not a substitute for exact API signatures.
