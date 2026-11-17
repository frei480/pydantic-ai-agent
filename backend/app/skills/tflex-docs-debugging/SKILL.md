---
name: tflex-docs-debugging
description: Use when diagnosing why a T-FLEX DOCs macro, extension module, or external application fails — logging, exception types, debugger attachment, or common runtime errors.
---

# Debugging T-FLEX DOCs macros and applications

Guide for explaining failures and building diagnosable code for the T-FLEX DOCs API. Verify every class and member named below in the `TFlexDOCs API` documentation with `search_docs` / `read_file` before putting it into code — treat this guide as a search map, not a specification.

## C# macros and external applications

1. Locate the "Отладка макросов" documentation via `search_doc_topics` (product `TFlexDOCs API`) and follow its setup steps: compile in Debug mode and attach the debugger to the T-FLEX DOCs process or use the built-in debugging tools.
2. For logging, search for `LogWriter` and `AsyncLogWriterLight` with `search_indexed_pages`, then read the class pages to confirm the write methods and their signatures before using them in an example.
3. Confirm the exception classes actually used by the macro infrastructure (search for `MacroException`, `MacroCompileException`, `InnerMacroException`): distinguish compile-time errors from runtime faults, and keep `InnerMacroException` in mind when a macro runs other macros.

## Simplified macros

- Use the step-by-step execution mode of the T-FLEX DOCs macro editor when available; document the diagnostic output tools of the editor instead of assuming they exist.
- Insert diagnostic messages through the editor's output window tools as described in the documentation.

## Common failure patterns

| Symptom | First checks |
|---|---|
| `NullReferenceException` | Object lookup returned nothing (wrong filter, deleted object) or the session/connection is gone; verify the lookup call and its preconditions. |
| `AccessDenied` | The user lacks rights on the object or action; see the "Доступы" documentation and the `tflex-docs-error-dictionary` skill. |
| `SessionExpired` | The server connection timed out; confirm the documented reconnection flow and connection lifetime rules. |
| Edit/commit failures | Editing was started without `CanEdit`/`BeginChanges`, or state assumptions (freshly created object, open transaction) were wrong; see the `tflex-docs-reference-object-editing` skill. |

## Checklist before answering

1. Classify the failure: syntax, compilation, runtime, or server fault.
2. Name the documentation page(s) that describe the failing mechanism, with paths and line numbers.
3. Propose the minimal change that fixes the root cause, not just the symptom.
4. Add logging or explicit failure handling only where the documentation confirms the API; mark anything unverified as such.
