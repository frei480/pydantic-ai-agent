---
name: tflex-docs-unit-conversion
description: Use when discovering T-FLEX DOCs measurement units or converting values between units.
---

# Work with T-FLEX DOCs units

The `UnitConverter` sample illustrates a unit lookup and conversion workflow.
Its source is `UnitConverter/UnitConverterDialog.cs`.

1. Confirm the value's physical quantity, source unit, target unit, and API
   version. Do not convert across incompatible unit classes.
2. Search `search_api_examples` for `UnitTypes`, `References.Units`,
   `Convert`, or the unit names. Read the relevant source lines.
3. Confirm the exact types, lookup rules, conversion direction, and argument
   units in the TFlexDOCs API documentation. Treat the sample's names and
   signatures as hints only.
4. Preserve precision and make the input/output units explicit. Define how
   missing units, unsupported classes, and invalid values are reported.
5. Check ownership and disposal of `ServerConnection` in the complete call
   path. The sample's use of `ServerConnection.Open()` does not by itself
   establish the correct lifecycle for another host or application.

Include a small known-value check when presenting conversion code.
