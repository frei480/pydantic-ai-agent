---
name: tflex-docs-test-data-generation
description: Use when creating sample or test objects in T-FLEX DOCs references, including hierarchies, parameters, or links.
---

# Generate T-FLEX DOCs reference test data

The `ReferenceObjectsGenerator` sample demonstrates a generator for reference
objects and related data. Treat its source as a scenario example, not a normative
contract.

## Verified example shapes

Working sequences from `ReferenceObjectsGenerator/ReferenceObjectsGenerator.cs` (catalog «Примеры использования API»; fetch with `read_api_example`):

```csharp
// Precondition and parent-aware creation (:175, :188):
if (!reference.CanCreateReferenceObject(null, parentObject, classObject))
    return null;
ReferenceObject newObject = reference.CreateReferenceObject(parentObject, classObject);

// Edit lifecycle with guard and rollback (:195-215):
if (!newObject.Changing)
    newObject.BeginChanges();
try
{
    // fill parameters, links...
    newObject.EndChanges();
}
catch
{
    newObject.CancelChanges();
    return null;
}

// Fill parameters (:286-297):
foreach (var parameter in changingObject.ParameterValues)
{
    if (parameter.IsReadOnly)
        continue;
    parameter.Value = GenerateValueByType(parameter.ParameterInfo.Type, length)
                      ?? parameter.ParameterInfo.DefaultValue;
}

// Load existing objects of a reference (:107-112):
_fileReference = new FileReference(Connection);
_fileReference.Objects.Load();
if (_fileReference.Objects.CountLoaded > 0)
    parent = _fileReference.Objects[0];
```

Hierarchy choice uses `reference.ParameterGroup.HasHierarchy` (:75); generation checks `_token.IsCancellationRequested` between objects (:89, :145); the value generator switches on `ParameterType.Id` (:306-385).

1. Confirm the target product/version and whether the data is disposable test
   data or production data.
2. Search `search_api_examples` for `CanCreateReferenceObject`,
   `CreateReferenceObject`, `BeginChanges`, and the requested relationship or
   parameter type. Read the relevant source range with `read_api_example`.
3. Verify the needed API members, constraints, and edit lifecycle in the
   TFlexDOCs API documentation. Do not infer signatures or parameter semantics
   from the sample alone.
4. Plan the object hierarchy, parameter groups, values, and links before
   generation. Bound the number of generated objects and support cancellation
   for long-running work.
5. Make partial failures visible. The sample contains broad exception handling
   and may skip unsuccessful object creation; do not reproduce that behavior
   without an explicit requirement and a clear report of skipped records.
6. Verify cleanup/rollback behavior and the effect of `EndChanges` or
   `CancelChanges` for the actual operation before promising atomicity.

Prefer a small dry run and explicit test reference over generating data in a
production reference.
