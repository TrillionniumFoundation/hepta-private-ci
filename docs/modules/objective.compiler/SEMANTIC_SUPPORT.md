# objective.compiler semantic support matrix

This matrix is normative for the current source candidate's *implemented admission behavior*. Registry schemas remain authoritative for protocol shape. A syntax accepted by the V1 JSON decoder is not necessarily admitted into the native compiler.

| Source V1 surface | Decode | Authenticated admission | Native representation | Feasibility support | Runtime objective result |
|---|---|---|---|---|---|
| constraint `eq` | yes | yes, registered unit/id only | scalar `Equal` | scalar interval intersection | hard constraint |
| constraint `lte` | yes | yes, registered unit/id only | scalar `AtMost` | scalar interval intersection | hard constraint |
| constraint `gte` | yes | yes, registered unit/id only | scalar `AtLeast` | scalar interval intersection | hard constraint |
| constraint `ne` | yes | **rejected** (`OBJ-E002`) | none | generic grammar has no scalar disequality operator | no objective |
| constraint `lt` | yes | **rejected** (`OBJ-E002`) | none | generic grammar uses closed scalar intervals | no objective |
| constraint `gt` | yes | **rejected** (`OBJ-E002`) | none | generic grammar uses closed scalar intervals | no objective |
| constraint `in` | yes | **rejected** (`OBJ-E002`) | none | generic feasibility supports enum `Include`, but Source V1 has only `boundQ32` and therefore carries no set operand | no objective |
| constraint `not_in` | yes | **rejected** (`OBJ-E002`) | none | generic feasibility supports enum `Exclude`, but Source V1 has only `boundQ32` and therefore carries no set operand | no objective |
| success predicate `eq/lte/gte` | yes | yes, registered predicate/unit only | scalar predicate | compiled predicate | success/terminal predicate |
| strict/disequality success predicates | yes | **rejected** (`OBJ-E002`) | none | not approximated | no objective |
| legal/forbidden action classes | yes | yes, registered mapping only | `ActionClass` / forbidden id | compiler legal-set construction | bounded legal action set |
| confirmation action classes | yes | yes only when also legal | confirmation policy | compiler | confirmation-marked legal action |
| intrinsic `abstain` | implicit or explicit | cannot be forbidden/gated | intrinsic action | compiler | always present on successful compile |
| soft dimensions | yes | yes, exact registered unit/direction and bounded weight interval | `SoftPreference` | excluded from hard feasibility | utility preference |
| evidence requirements | yes | yes, registered requirement | terminal/intermediate success predicate | compiled predicate | evidence predicate |
| resource ceilings | yes | yes, profile-defined deterministic Q32 conversion | generated hard constraints | scalar feasibility | hard resource constraints |
| risk / rollback / compensation / abstention rule | yes | yes, frozen monotone profile mapping | generated hard constraints | scalar feasibility | hard risk constraints |
| generic feasibility enum `Include/Exclude` | n/a | direct feasibility API only | `ConstraintAtomV1` | supported | advisory feasibility receipt; not Source V1 compilation |
| generic action `Require/Forbid/Implies` | n/a | direct feasibility API only | `ConstraintAtomV1` | supported bounded Horn closure | advisory feasibility receipt; not Source V1 compilation |
| immutable identity equality | n/a | direct feasibility API only | `ConstraintAtomV1` | supported | advisory feasibility receipt; not Source V1 compilation |

## Current production composition

The default public compile boundary is `admit_and_compile_objective_v1`. The deterministic compiler core accepts a private `AdmittedObjectiveSource`, so raw `ObjectiveSourceEnvelope` values cannot bypass authenticated admission through the default crate API. The old native-envelope path is exposed only behind the non-default `qualification-legacy-objective-compile` feature as `compile_prevalidated_legacy_objective` for controlled qualification fixtures.

The current product-caller candidate is the Agentd signed-objective route. Agentd selects an owner-controlled admission profile from its private home, verifies the registered AuthBus issuer, derives the current generation and fence locally, compiles the structured source, materializes `RunStartSnapshotV1`, atomically persists the admission/compile/run publication, and then hands the immutable snapshot to `AgentRunCoordinator`. This composition still grants no effect authority and does not by itself establish activation, independent acceptance, promotion or release.

## Actual call graph

```text
signed structured objective
-> Agentd owner profile + AuthBus authentication
-> decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> admit_and_compile_objective_v1
   -> authenticate source/principal/profile/digests/time
   -> adapt_source (registered Source V1 -> native scalar compatibility IR)
   -> compiler::compile(AdmittedObjectiveSource)
      -> scalar_conflict
         -> check_feasibility_v1 (legacy scalar compatibility grammar)
      -> legal-action construction + canonical objective digests
-> ObjectiveRunPublicationV1 + RunStartSnapshotV1
-> fsync temporary publication + atomic rename + directory fsync
-> AgentRunCoordinator::start_run
```

The separately public `check_feasibility_v1` API is a generic bounded feasibility engine. It is not evidence that every generic atom kind is reachable from Source V1 admission.
