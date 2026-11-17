---
name: tflex-docs-parameters
description: Use when reading, writing, checking, or enumerating T-FLEX DOCs object parameters — ParameterContainer indexers, ParameterValues, parameter groups, and edit-state rules.
---

# Work with T-FLEX DOCs object parameters

Use this skill for tasks that read or change parameter values, check that a parameter exists, enumerate an object's parameters, or work with parameter groups (`ParameterGroup`). The members and code shapes below are verified against the `TFlexDOCs API` documentation (T-FLEX DOCs 17.6); re-verify in the current documentation when targeting another version.

## Key classes and members

- `ParameterContainer` — base class for objects that carry parameters (`TFlex.DOCs.Model.References`).
- Indexers, read-only, all return `Parameter`: `this[Guid]`, `this[Int32]`, `this[ParameterInfo]`. **There is no string indexer** — resolve the parameter's GUID/ID or `ParameterInfo` first (for example from a parameter group).
- `ParameterValues` — `public abstract ParameterCollection ParameterValues { get; }`.
- `ParameterCollection.Contains(Guid)` / `Contains(Int32)` / `Contains(ParameterInfo)` — existence checks.
- `GetEnumerator()` — `public IEnumerator<Parameter> GetEnumerator()`; `foreach` works directly on the container.
- `Parameter` (`TFlex.DOCs.Model.Parameters`): `ParameterInfo` (описание параметра; `ParameterInfo.Name` — наименование), `Value` (get/set), state checks `IsReadOnly` / `IsNull` / `IsEmpty` / `IsModified`, typed getters `GetString()` / `GetGuid()` / `GetInt32()` / … and explicit conversions.

## Verified code shapes

```csharp
// Read a parameter by GUID / ID / ParameterInfo (no string indexer):
Parameter param = obj[parameterGuid];
object value = param.Value;

// Check existence before access:
if (obj.ParameterValues.Contains(parameterGuid))
{
    Parameter param = obj[parameterGuid];
}

// Write a parameter value — the object must be in edit state first
// (see the tflex-docs-reference-object-editing skill):
param.Value = newValue;

// Enumerate all parameters:
foreach (Parameter param in obj)
{
    string name = param.ParameterInfo.Name;
    object value = param.Value;
}
```

Example-verified write and enumeration patterns (catalog «Примеры использования API»):

```csharp
// Write via the values collection (ImportReference/ReferenceImporter.cs:181):
newObject.ParameterValues[info].Value = value;   // info is a ParameterInfo

// Enumerate writable parameters (ReferenceObjectsGenerator/ReferenceObjectsGenerator.cs:286-297):
foreach (var parameter in changingObject.ParameterValues)
{
    if (parameter.IsReadOnly)
        continue;
    parameter.Value = GenerateValueByType(parameter.ParameterInfo.Type, length)
                      ?? parameter.ParameterInfo.DefaultValue;
}
```

`ParameterInfo` members exercised there: `Group` (main vs. connected parameter group), `Length`, `Type`, `DefaultValue`.

Verified against: `TFlexDOCs API/ParameterContainer.md` (member table), `TFlexDOCs API/ParameterContainerItem(Guid) - свойство.md`, `TFlexDOCs API/B144C36A.md` (`ParameterValues`), `TFlexDOCs API/ParameterCollection.md` (`Contains` overloads), `TFlexDOCs API/829D941E.md` (`GetEnumerator`), `TFlexDOCs API/Parameter.md`, `TFlexDOCs API/B742F7EF.md` (`ParameterInfo.Name`).

## Workflow patterns

1. **Read a parameter:** resolve the parameter by GUID, ID, or `ParameterInfo`, then read its `Value`; validate that the lookup succeeded before use.
2. **Write a parameter:** follow the lifecycle rules of the `tflex-docs-reference-object-editing` skill (`BeginChanges()` / `CheckIn(...)` or the macro-context equivalent) and save after the change.
3. **Check existence:** call `ParameterValues.Contains(...)` before reading a parameter that may be absent; report a missing parameter instead of guessing its name.
4. **Enumerate:** iterate the container with `foreach`, using `param.ParameterInfo.Name` and `param.Value`.

## Rules

- Never write parameter values outside a confirmed edit/save lifecycle.
- Check `IsReadOnly` before changing a value: some parameters are system parameters and not writable.
- Prefer the typed getters (`GetString()`, `GetGuid()`, …) when the target type is known; do not infer conversions.

## Documentation entry points

- `TFlexDOCs API/ParameterContainer.md` and `TFlexDOCs API/ParameterCollection.md`
- `TFlexDOCs API/Parameter.md` and `TFlexDOCs API/ParameterInfo.md`
- `TFlexDOCs API/71837294-B2E3-4AC0-A540-716B78185C1E.md`
- Search `**/TFlexDOCs API/**/*.md` for the `TFlex.DOCs.Model.Parameters` namespace page and for `ParameterGroup` when working with parameter groups.
