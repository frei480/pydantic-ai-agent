---
name: tflex-docs-plugin-ui-extensions
description: Use when extending T-FLEX DOCs with plugins, special references, commands, or graph-oriented UI.
---

# Extend T-FLEX DOCs plugins and UI

The `Graphs` sample demonstrates one plugin/UI scenario. Relevant source files
include `Graphs/Graphs/PluginLibrary.cs`; use `search_api_examples` to locate
other implementation details rather than assuming this is the complete plugin.

## Verified example shapes

Plugin entry point from `Graphs/Graphs/PluginLibrary.cs` (catalog «Примеры использования API»; fetch with `read_api_example`):

```csharp
public class PluginLibrary : IPluginLibrary   // TFlex.DOCs.Model.Plugins
{
    public void RegisterPlugin()
    {
        // Resolve client assemblies (TFlex.PdmFramework.Resolve, :28):
        AssemblyResolver.Instance.AddDirectory(@"C:\Program Files (x86)\T-FLEX DOCs 17\Program");
        // Register special references created by the API generator (:35-36):
        ReferenceCatalog.RegisterSpecialReference(GraphsReference.GraphsReferenceGuid,
            new GraphsReference.Factory());
    }

    // UI hook for reference-bound views (:39-46):
    public void OnCreatingReferenceVisualRepresentation(Reference reference,
        IModelVisualRepresentation visualRepresentation)
    {
        if (visualRepresentation is LayoutViewModel lvm)
            lvm.SubscribeCommandsGeneration(new CommandsProvider(lvm));
    }

    // Hook for views without references: working pages, mail, object
    // property dialogs and panels (:57-79).
    public void OnCreatingVisualRepresentation(IModelVisualRepresentation visualRepresentation) { ... }
}
```

Special reference objects derive from `SpecialReferenceObject<T>` (`Graphs/Graphs/Model/Graphs/GraphsReferenceObject.cs:8`).

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
