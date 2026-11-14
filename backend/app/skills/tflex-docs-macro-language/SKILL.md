---
name: tflex-docs-macro-language
description: "Use for T-FLEX DOCs macro-language and macro tasks: simplified macro commands, C# macros, MacroContext, parameters, object search/copy/hierarchy, links, events, dialogs, UI, and macro execution context."
---

# Work with T-FLEX DOCs macros

Use this workflow for questions about the T-FLEX DOCs macro language, writing or debugging macros, and choosing between macro-language commands and the C# API. The topic index is `TFlexDOCs API/index.md`; macro-language topics begin at `Макроязык` and continue through the API and macro-context entries.

## 1. Identify the macro kind and execution context

T-FLEX DOCs distinguishes:

- **Макрос:** a simplified macro that uses the system's macro-language commands, intended for short/basic operations.
- **Макрос C#:** a C# program with classes and the T-FLEX DOCs API, suited to more complex logic.

Do not silently translate simplified macro-language into C# or present C# API calls as macro-language commands. Confirm which kind the user needs; if unspecified, explain the distinction and choose the simplest form supported by the requested task.

Also identify how and where it runs: a reference event, user-dialog action, navigation button, server task, or process step. Execution may be client-side or server-side and may run as the current user or as the system. This affects UI availability, permissions, and behavior; verify the exact trigger's documentation before using UI or privileged operations.

For C# macro examples, follow the documented `MacroProvider` / `MacroContext` pattern and inspect the relevant `Context` members (current reference, object, connection, hierarchy link, event arguments). Do not assume a macro has a UI or a current object unless its context guarantees one.

## 2. Route the task to the right documentation

Start with `TFlexDOCs API/index.md`, read only its table-of-contents section, then search within `**/TFlexDOCs API/**/*.md`. Choose the narrowest applicable topic:

- **Parameters and formulas:** `Макроязык/Параметры`, `Работа с параметрами`, and the event pages for parameter changes. Verify parameter names, value types, linked-object access, and whether the macro is a parameter-change handler.
- **Find or create objects:** `Макроязык/Поиск объектов`, `Макроязык`, and `Справочники`. Check whether a lookup returns one object, a collection, or `null`; validate results before use.
- **Edit object or links:** `Работа с объектами`, `Связи`, and `Объекты списка`. Verify object state, link kind/cardinality, and the correct save/cancel operation.
- **Copy objects:** `Макроязык/Копирование объектов`. Distinguish a full, already-saved copy from a copy returned in edit state; verify which related objects and links are copied.
- **Hierarchy:** `Макроязык/Иерархия`, `Работа с иерархией`, and `Подключения`. Distinguish a simple tree (one parent) from a complex hierarchy (multiple parents and explicit connection objects).
- **Dialogs, selection, and UI:** `Контекст выполнения макроса`, `Окна, элементы управления`, `Диалоги`, and the specific type/file/folder/object selection page. Verify null/cancel results and UI-thread requirements.
- **Events and lifecycle:** `Использование`, `События`, `Обработка событий`, and the event-specific page. Confirm when the handler fires, what changed data is available, and whether changes are still cancellable.
- **Other domains:** use the index to locate dedicated pages for stages, signatures, tasks, business processes, reports, access, files, CAD documents, and other specialized APIs; do not infer their behavior from general macro examples.

Search exact Russian command names and API member names from the topic pages, then read the linked member/type pages for signatures, overloads, and restrictions. Examples are leads, not proof for undocumented cases.

## 3. Preserve object edit and save semantics

For simplified macro-language object changes:

1. Determine whether the object is new or existing. Newly created objects may already be in edit state; do not call `Изменить()` automatically.
2. For an existing object, use `Изменить()` before changing it, and pair every edit entry with exactly one `Сохранить()` or `ОтменитьИзменения()`.
3. If several macros can edit the same object, preserve the edit/save pairing across the call chain. Unmatched operations can fail when the macro finishes.
4. If using `СохранитьВсё`, verify which context objects it will save and whether the selected overload applies history changes or shows a confirmation dialog.
5. On failure, cancel only the edit state actually opened by the code; do not hide the original error.

For parameter updates, use the actual parameter names and correct value types. For links, distinguish a single linked object from a collection and verify the link's cardinality. Never leave placeholder names, `Guid.Empty`, or sample values in executable code.

## 4. Handle side effects deliberately

Object creation, edits, copying, deletion, ownership changes, process actions, and permission changes modify server data. Perform them only when requested, identify the target and intended changes, validate preconditions, and report missing permissions or invalid state explicitly. Ask for confirmation in the generated macro when the requested operation is consequential and the user has not already specified that it should proceed automatically.

Avoid unnecessary per-object queries in loops when the documentation offers batch operations. Before using a batch API, verify its filter, limits, and error behavior.

## 5. Produce a grounded answer

1. State the assumed macro kind, execution trigger, and client/server context.
2. Provide the smallest complete example in the requested language, including required namespaces or macro wrapper where applicable.
3. Handle missing objects, cancelled dialogs, edit failures, and exceptions explicitly.
4. Cite the exact documentation file and line numbers for verified signatures and behavior.
5. If the docs do not establish an overload, runtime context, permission rule, or side effect, say so and search the linked type/event page instead of guessing.
