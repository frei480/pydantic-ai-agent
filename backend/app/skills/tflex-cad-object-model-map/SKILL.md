---
name: tflex-cad-object-model-map
description: Use as a high-level map for T-FLEX CAD Open API questions about document model objects, 2D/3D type families, class inheritance, or distinguishing model objects from generated geometry; choose a document, 2D, or 3D coding skill for implementation.
---

# Navigate the T-FLEX CAD object model

Use `TFlexCAD API/055594cd-1cb5-4213-990c-1c9c4a0572ab.md` to find relevant type families. It is a navigation map, not an API specification.

## Research workflow

1. Keep the question scoped to **T-FLEX CAD Open API**; do not mix it with T-FLEX DOCs.
2. Open the object-model diagram and use its 2D, 3D, and document-level groups to identify the likely type and its base classes. Search the CAD documentation for the exact type name and read that type's page.
3. For inherited members, inspect the type declaration and the relevant base-class page. The diagram alone does not establish member availability, method signatures, object ownership, or operation order.
4. For 3D questions, distinguish objects created in the model tree (for example, operations and profiles) from generated geometry (solids, faces, edges, and vertices). Use `TFlexCAD API/165b92c0-a86f-470f-9ac7-467b59ccf9e7.md` and the specific geometry documentation to verify which one an API returns or accepts.
5. Search and read the pages for the exact operations, properties, and related types needed by the task. Confirm signatures, overloads, nullability, and side effects from those pages; do not derive them from class names or diagram arrows.
6. Cite the documentation file and line numbers for verified facts. If the documentation does not establish a behavior, state the gap rather than guessing.

## Useful routes

- **2D drawing objects:** identify whether the task concerns a node, construction, outline, text, dimension, view, or other drawing object; then inspect that concrete type and its bases.
- **3D model objects:** route profiles, paths, workplanes, operations, transformations, and camera/projection objects to their specific type pages.
- **Document-wide objects:** use the diagram's document-level branch for pages, variables, and other shared types.
- **Model object vs. geometry:** do not assume an `Object3D` is the same thing as its generated geometric representation. Verify the API type and geometry-reference behavior in the relevant documentation.

Treat the diagram as an index for finding neighboring types, not as proof that two classes have a particular runtime relationship or that a suggested API call is supported.
