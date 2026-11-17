---
name: tflex-docs-error-dictionary
description: Use when explaining, diagnosing, or handling T-FLEX DOCs API errors, server faults, or exception codes such as AccessDenied, ObjectNotFound, DatabaseError, or SessionExpired.
---

# T-FLEX DOCs error dictionary

Reference for interpreting and resolving exceptions and fault codes reported by the T-FLEX DOCs API. Most API errors surface either inside a result object (fault with a type) or as a thrown exception class; verify the exact type and its members in the documentation before relying on them.

## Common fault categories (based on `FaultType`)

| Fault | Meaning | Typical resolution |
|---|---|---|
| `AccessDenied` | The current user lacks permission for the action. | Verify the user's roles and object permissions; find the "Доступы" pages via `search_doc_topics` on the `TFlexDOCs API` product. |
| `ObjectNotFound` | The given ID does not match any existing object. | Re-check how the object ID was obtained; the object may have been deleted or moved. |
| `DatabaseError` | Internal server-side error. | Report the server-side cause; do not retry blindly. |
| `SessionExpired` | The connection to the T-FLEX DOCs server timed out. | Re-authenticate and establish a new session before repeating the operation. |

## How to verify and resolve

1. Search the documentation for the exact exception or fault name with `search_docs` (use `literal=true` for the precise identifier), then read the linked member pages; confirm the exception class name, its namespace, and its members before citing them.
2. For `AccessDenied`, check the access-rights documentation and whether the scenario requires elevated rights or a different user context.
3. For `ObjectNotFound`, retrace where the ID came from (lookup by name, prototype, link) and confirm the lookup call is correct.
4. For `SessionExpired`, confirm the connection lifecycle rules (see the `tflex-docs-server-file-import` skill) rather than inventing a reconnection call.
5. In generated code, handle faults explicitly: distinguish permission and state problems from programming errors, and never swallow an exception without a documented reason.
