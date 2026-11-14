---
name: tflex-docs-open-api-map
description: Use as a navigation map for T-FLEX DOCs Open API questions about server connections, references, reference objects and links, filters, stages, schemes, signatures, or relationships between these types.
---

# T-FLEX DOCs Open API object map

Use this map to choose what to investigate in the T-FLEX DOCs API documentation. It summarizes the object groups and relationships in the `T-FLEX DOCs Open API — диаграмма объектов` diagram. It is a navigation aid, not an API specification.

## Object groups

- **Server connection:** `ServerConnection`, `ConnectionParameters`, `ClientView`, `SystemReferences`.
- **Reference catalog:** `ReferenceCatalog`, `ReferenceInfo`, `Reference`, `ParameterGroup`, `ClassTree`, `ClassObjectCollection`, `ClassObject`, `ReferenceObjectCollection`, `ReferenceObject`.
- **Reference-object links:** `ReferenceObjectLinks`, `AnyReferenceLink`, `OneToOneLink`, `OneToManyLink`, `OneToManyTable`, `ComplexHierarchyLink`, `Desktop`.
- **Filtering:** `Filter`, `FilterTerm`, `TermGroup`, `ReferenceObjectTerm`.
- **Stages and schemes:** `Stage`, `Scheme`, `SchemeStage`.
- **Signatures:** `Signature`, `SignatureType`, `SignatureTypes`, `SignatureCollection`.

## Relationships to investigate

- A server connection is related to `ReferenceCatalog`, `ClientView`, `SystemReferences`, `ConnectionParameters`, and `Stage`.
- A `Reference` is related to `ClassTree`, `ParameterGroup`, `ReferenceObjectCollection`, and `ReferenceInfo`.
- `ReferenceObjectLinks` is related to `AnyReferenceLink`, `OneToOneLink`, `OneToManyLink`, and `OneToManyTable`.
- `Filter` is related to `TermGroup`; investigate `FilterTerm` and `ReferenceObjectTerm` as part of the filter path.
- `Stage` and `Scheme` are related through `SchemeStage`.
- `Signature` and `SignatureCollection` are related to signature types (`SignatureType` and `SignatureTypes`).

## Research workflow

1. Use this map to identify likely neighboring types and search terms. Keep T-FLEX DOCs separate from T-FLEX CAD.
2. Search the T-FLEX DOCs documentation for the exact target type and relevant neighbors. Locate and read the diagram's Markdown companion if more context about the map is needed.
3. Read the profile documentation and examples for every member, constructor, and operation used in an answer. Do not infer direction, cardinality, ownership, or method signatures from this map alone.
4. Cite the documentation source and line numbers for verified facts. If the documentation does not establish a relationship or signature, report that uncertainty instead of guessing.
