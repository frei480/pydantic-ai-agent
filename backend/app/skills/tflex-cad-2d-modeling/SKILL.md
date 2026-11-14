---
name: tflex-cad-2d-modeling
description: 'Use when writing C# for T-FLEX CAD 2D geometry and drawings: nodes, construction lines, outlines, dimensions, text, views, fragments, copies, layers, or annotations.'
---

# Write T-FLEX CAD 2D model code

Use this workflow for 2D model objects and drawing automation. The index and class diagram help locate types; they do not prove constructor signatures or behavior.

## Research and implementation

1. Confirm the request is about the **2D model** rather than generated 3D geometry, drawing display, or T-FLEX DOCs.
2. Use `search_doc_topics` with the requested object and action. The CAD index groups 2D examples under lines of construction, drawing lines, nodes, dimensions, formatting, fragments, copies, views, and 2D graphics.
3. Read the closest end-to-end example first. For example, the object-creation guide constructs two `FreeNode` objects and a `ConstructionOutline` inside a document change block. Adapt only the pattern that the example actually supports.
4. Search the exact concrete type and members in `TFlexCAD API`. Verify constructors, coordinate systems, referenced-object requirements, units, return values, and overloads from the corresponding API pages before writing code.
5. For edits, copies, dimensions, fragments, and views, identify the required source objects and document state. Do not substitute construction geometry for drawing outlines or assume a displayed projection is an editable model object.
6. Keep creation and mutation inside the documented document change lifecycle. Confirm the applicable commit/cancel behavior for the selected operation instead of inventing exception cleanup.
7. Provide a complete, minimal C# example for the caller's context, handle missing references or selections, and cite documentation paths and line numbers.

## Routing hints

- Free, intersection, and object nodes: inspect the node-specific example and type.
- Lines, circles, splines, and paths: distinguish construction geometry from drawing outlines.
- Dimensions, text, roughness, hatching, and leaders: verify required geometry references and annotation-specific parameters.
- Views, sections, fragments, and copies: verify source document/object requirements and the operation's side effects.
