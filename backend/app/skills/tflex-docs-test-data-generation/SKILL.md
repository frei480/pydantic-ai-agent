---
name: tflex-docs-test-data-generation
description: Use when creating sample or test objects in T-FLEX DOCs references, including hierarchies, parameters, or links.
---

# Generate T-FLEX DOCs reference test data

The `ReferenceObjectsGenerator` sample demonstrates a generator for reference
objects and related data. Treat its source as a scenario example, not a normative
contract.

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
