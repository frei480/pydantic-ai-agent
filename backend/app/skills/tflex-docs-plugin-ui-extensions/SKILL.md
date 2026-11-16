---
name: tflex-docs-plugin-ui-extensions
description: Use when extending T-FLEX DOCs with plugins, special references, commands, or graph-oriented UI.
---

# Extend T-FLEX DOCs plugins and UI

The `Graphs` sample demonstrates one plugin/UI scenario. Relevant source files
include `Graphs/Graphs/PluginLibrary.cs`; use `search_api_examples` to locate
other implementation details rather than assuming this is the complete plugin.

1. Identify whether the request concerns plugin registration, a special
   reference, command generation, a view model, a custom control, or graph data.
2. Search `search_api_examples` for `IPluginLibrary`,
   `RegisterSpecialReference`, `SubscribeCommandsGeneration`, `MacroContext`,
   or the requested UI component; read only the matching source ranges.
3. Verify the applicable plugin contracts, registration lifecycle, command
   APIs, and UI framework types in the TFlexDOCs API documentation.
4. Keep host/platform UI dependencies distinct from DOCs APIs. Confirm required
   assemblies, target framework, deployment, and version compatibility for the
   user's installation.
5. Explain data sources, command enablement, and lifecycle/unsubscription where
   relevant. Do not generalize the sample's graph model or macro evaluation
   behavior to unrelated UI extensions.

Use the installed sample only as an implementation reference; cite documentation
for API claims and label any sample-only detail.
