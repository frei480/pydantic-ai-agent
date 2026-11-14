---
name: tflex-cad-3d-modeling
description: 'Use when writing C# for T-FLEX CAD 3D models: 3D nodes, profiles, paths, workplanes, operations, fragments, transformations, and generated geometry.'
---

# Write T-FLEX CAD 3D model code

Use this workflow for 3D modeling tasks. Class diagrams help locate related types but are not proof of API signatures, operation order, or geometry ownership.

## Research and implementation

1. Identify whether the task concerns a model-tree object (such as a profile, workplane, path, or operation) or generated geometry (such as a body, face, edge, or vertex). Do not treat these as interchangeable.
2. Use `search_doc_topics` with the concrete operation and input geometry. The CAD index groups 3D examples around nodes, profiles, workplanes/surfaces, coordinate systems, paths, operations, fragments, and transformations.
3. Read the closest complete example and follow its documented construction order. Then search the exact type and API members; verify constructors, source object types, units, coordinate systems, regeneration behavior, return values, and overloads.
4. Trace dependent objects only as far as the requested operation requires. Do not infer that a profile is valid, a path is closed, or an operation has regenerated successfully from its class name or diagram relationships.
5. When selecting generated geometry, confirm the expected geometry type and how the API exposes it. Distinguish a 3D model object from its geometric representation and topology references.
6. Verify the document change lifecycle and failure/cancel semantics for the exact operation. Produce the smallest complete C# example for the stated add-in, macro, or external-application context.
7. Cite the relevant T-FLEX CAD documentation paths and line numbers; state unresolved assumptions instead of guessing.

## Routing hints

- 3D nodes and coordinate systems: verify reference geometry and coordinate-system semantics.
- Profiles, workplanes, and paths: verify required inputs and whether source objects are 2D, 3D, or generated geometry.
- Extrusion, rotation, sweep, loft, Boolean, and blending: use the matching operation example and inspect its exact API pages.
- Transformations and fragments: verify source/target coordinate systems, ownership, and whether the operation mutates or creates an object.
