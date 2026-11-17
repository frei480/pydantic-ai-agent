---
name: tflex-docs-stages-signatures
description: Use for T-FLEX DOCs object stages and signatures — changing an object's stage, listing signatures, checking sign status, and working with stage and signature types.
---

# Work with T-FLEX DOCs stages and signatures

Use this skill when the task changes an object's stage, lists or checks an object's signatures, or works with stage schemes and signature types. The members and code shapes below are verified against the `TFlexDOCs API` documentation (T-FLEX DOCs 17.6); re-verify in the current documentation when targeting another version.

## Key classes and members

- `ServerConnection.Stages` — `public List<Stage> Stages { get; }`, all stages of the server.
- `ServerConnection.SignatureTypes` — `public List<SignatureType> SignatureTypes { get; }`, all signature types of the server.
- `ReferenceObject.ObjectStages` — `public ObjectStageInfo ObjectStages { get; }`, typed stage information of the object.
- `ReferenceObject.Signatures` — `public SignatureCollection Signatures { get; }`, the object's signatures; `SignatureCollection.Object` returns the signed reference object.
- `MacroProvider.ChangeStageObjects(RefObjList, String, Boolean)` — macro-context stage change; the flag is `ignoreSchemeStage` (`true` — ignore the stage transition scheme). A four-argument overload `ChangeStageObjects(RefObjList, String, String, Boolean)` also exists.
- `SignatureCollection.AddAndSign(SignatureType, String)` — signs the object with a signature of the given type; overloads `AddAndSign(SignatureType, UserReferenceObject, String)` and `AddAndSign(SignatureType, UserReferenceObject, String, Byte, String)` sign on behalf of a given user and can install a digital signature.
- `Stage`, `Scheme`, `SchemeStage` — stages and stage-transition schemes; see the `tflex-docs-open-api-map` skill for neighboring types.
- Macro language: `ТекущийОбъект.ИзменитьСтадию("имя стадии", "комментарий")` changes the current object's stage in a simplified macro.

## Verified code shapes

```csharp
// Server-wide stage and signature-type lists:
List<Stage> stages = connection.Stages;
List<SignatureType> types = connection.SignatureTypes;

// Per-object stage information and signatures:
ObjectStageInfo stageInfo = obj.ObjectStages;
SignatureCollection signatures = obj.Signatures;
ReferenceObject signedObject = signatures.Object;

// In a macro context (MacroProvider, TFlex.DOCs.Model.Macros):
// stageName is the stage name or its Guid; the optional flag
// ignoreSchemeStage=true skips the stage transition scheme.
ChangeStageObjects(objects, "Имя стадии", ignoreSchemeStage: false);
```

Verified against: `TFlexDOCs API/8F6BF156.md` (`Stages`), `TFlexDOCs API/8B0F0931.md` (`SignatureTypes`), `TFlexDOCs API/5520CF76.md` (`ObjectStages`), `TFlexDOCs API/20F11F49.md` (`Signatures`), `TFlexDOCs API/SignatureCollection.md` (`AddAndSign` overloads, `Object`), `TFlexDOCs API/C4FFC4D1.md` (`ChangeStageObjects`), `TFlexDOCs API/07EFB6BB-9CE0-45EA-B3DF-F06352B57CAC.md` (macro stage-change example).

## Workflow patterns

1. **List stages:** read `connection.Stages`; for an object's stage information, read `ReferenceObject.ObjectStages`.
2. **Change a stage:** in a C# macro use `ChangeStageObjects` on `MacroProvider`; in a simplified macro use `ТекущийОбъект.ИзменитьСтадию(...)`. Confirm the target stage exists and whether the transition scheme applies.
3. **List signatures:** read `obj.Signatures` and inspect the `SignatureCollection`.
4. **Sign an object:** pick a `SignatureType` from `connection.SignatureTypes` and call `AddAndSign`; choose the overload that matches whether signing happens on behalf of another user or with a digital signature.

## Rules

- Stage changes and signing modify server data: confirm permissions, the target stage's scheme, and the operation's confirmation behavior first.
- Do not assume an object is signed or that a stage change is allowed; verify the documented preconditions.

## Documentation entry points

- `TFlexDOCs API/EAA7893.md` (ServerConnection member table)
- `TFlexDOCs API/ReferenceObject.md` (member table)
- `TFlexDOCs API/SignatureCollection.md`, `TFlexDOCs API/Stage.md`, `TFlexDOCs API/SignatureType.md`
- `TFlexDOCs API/db4db38c-988c-4547-95e7-4de07a9cbec5.md`
