---
name: tflex-docs-server-file-import
description: Use for T-FLEX DOCs Open API tasks about connecting to a DOCs server from a macro or external C# application, importing a local folder into the Files reference, and listing imported files.
---

# Connect to T-FLEX DOCs and import files

Use this workflow when the requested task combines server connection with importing a folder into the T-FLEX DOCs "Файлы" reference. The source example is `TFlexDOCs API/590BF971-0256-450B-8D9D-46C870673B97.md`. Treat it as a starting point, not a complete specification.

## 1. Choose the connection context

- **Macro:** investigate obtaining `ServerConnection` from the macro context (`Context.Connection`). Do not open a second connection unless the task specifically requires one.
- **External application:** investigate `ServerConnection.Open(...)`. The source example uses the server login authentication overload, GRPC communication mode, and default serialization/compression settings.
- Keep code for these two contexts separate. Do not mix macro-only types such as `MacroProvider` and `MacroContext` into an external application's `Main`.

## 2. Establish connection and failure handling

For an external application, inspect the source example's connection validation (`IsConnected`) and `ConnectionLost` event handling before writing the flow. Preserve deterministic disposal of an opened connection. Verify exact overload parameters and event types in the linked API documentation; do not infer them from the example alone.

Never copy example credentials into generated code. Use configuration or a secure credential provider, and keep passwords out of logs and user-facing output.

## 3. Import into the Files reference

The source example demonstrates this sequence:

1. Prepare the external application's assembly resolver for the installed T-FLEX DOCs client assemblies; verify DLL names, copy-local settings, and installation path against the target installation.
2. Create `FileReference` with the active `ServerConnection`.
3. Find the destination folder by relative path and validate that the result is a `FolderObject` before import.
4. Call the documented `Import` operation with `ImportParameters`. Check the meaning of `DestinationFolder`, `Recursive`, `CreateClasses`, and `AutoCheckIn` against their API pages and the user's requirements before selecting values.
5. Handle an absent destination or failed import explicitly; do not report success unless the operation returned a folder.
6. If the task requires a summary of imported files, use the returned folder's children and verify the documented traversal behavior before recursively loading them and selecting `FileObject` values.

The sample uses a local folder path and imports its contents recursively into the "Служебные файлы" folder. Do not assume that folder exists on another server or that the same destination is appropriate for the user.

## 4. Research before producing code

1. Search `**/TFlexDOCs API/**/*.md` for the source filename and exact types: `ServerConnection.Open`, `FileReference`, `ImportParameters`, `FolderObject`, and `FileObject`.
2. Read the source example and the relevant type/method pages linked from it. Confirm overloads, nullability, ownership/disposal, required assemblies, and import option semantics.
3. Adapt only the parts required by the user's context, server, destination path, and recursion/class/check-in requirements.
4. Provide a complete code path with required `using` directives and connection/error handling appropriate to either a macro or external application.
5. Cite verified documentation paths and line numbers. Clearly state any unresolved installation-specific detail instead of guessing.
