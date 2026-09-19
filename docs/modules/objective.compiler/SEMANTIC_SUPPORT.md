# objective.compiler semantic support matrix

This document records the exact boundary between the registered `ObjectiveSourceEnvelopeV1`
syntax, authenticated admission, the owner-internal compiler IR and the generic typed
feasibility API. Structural decode support is not the same thing as executable compiler
support. Unsupported source semantics fail closed with `OBJ-E002`; they are never
approximated or silently dropped.

| Source V1 semantic | JSON/structure decode | Admission result | Owner-internal IR | Generic feasibility support | Runtime result |
|---|---|---|---|---|---|
| constraint `eq` | yes | admitted when registered/profile-bound | scalar `Equal` | scalar interval | compiled/conflict |
| constraint `lte` | yes | admitted when registered/profile-bound | scalar `AtMost` | scalar interval | compiled/conflict |
| constraint `gte` | yes | admitted when registered/profile-bound | scalar `AtLeast` | scalar interval | compiled/conflict |
| constraint `ne` | yes | deterministic reject | none | not represented by Source V1 adapter | `OBJ-E002` |
| constraint `lt` / `gt` | yes | deterministic reject | none | not represented by Source V1 adapter | `OBJ-E002` |
| constraint `in` / `not_in` | yes | deterministic reject | none | generic API supports finite enum Include/Exclude | `OBJ-E002` |
| success/terminal `eq/lte/gte` | yes | admitted when registered/profile-bound | scalar success predicate | downstream observation semantics | compiled |
| success/terminal `ne/lt/gt` | yes | deterministic reject | none | not represented by Source V1 adapter | `OBJ-E002` |
| legal/forbidden/confirmation actions | yes | registered action mapping required | legal action grammar + intrinsic `abstain` | action require/forbid/positive implication exists in generic API | compiled/conflict |
| resources | yes | all six fields mapped through frozen profile | hard `AtMost` constraints | scalar interval | compiled/conflict |
| risk / rollback / compensation / abstention rule | yes | frozen monotone profile mapping required | hard constraints | scalar interval | compiled/conflict |
| evidence requirements | yes | registered requirement mapping required | success predicate with confidence bound | scalar interval | compiled |
| soft dimensions | yes | registered unit/direction/baseline required | bounded soft preferences | excluded from hard feasibility | compiled |
| immutable identity / generation atoms | not expressible by this Source V1 constraint payload | n/a | n/a | supported by `check_feasibility_v1` typed API | typed-API only |
| positive Horn action implications | not expressible by this Source V1 constraint payload | n/a | n/a | supported by `check_feasibility_v1` typed API | typed-API only |

## Why `in` / `not_in` remain rejected

The registered Source V1 constraint object currently carries one `boundQ32` and has no
finite-set member payload. Interpreting that scalar as a set would invent semantics and break
canonical compatibility. The generic feasibility engine already supports bounded enum domains,
but Source V1 needs a separately registered additive or successor protocol representation before
those operators can be admitted losslessly.

## Public API boundary

Normal product code uses:

```text
ObjectiveSourceEnvelopeV1
-> admit_objective_v1(...)
-> AdmittedObjectiveV1
-> compile_admitted_objective_v1(...)
```

`AdmittedObjectiveV1` has no public raw-source constructor. The legacy
`ObjectiveSourceEnvelope -> compile` surface is no longer exported by default. It exists only
as `compile_prevalidated_legacy_objective_v1` under the explicit
`qualification-legacy-compile` Cargo feature for historical qualification fixtures.

## Feasibility determinism

The constraint solver is deterministic for a fixed validated grammar, canonical atom set and
oracle-call budget. The explicit availability API additionally accepts a wall-clock budget and
records elapsed host time; exhaustion near that deadline is host-sensitive and is not semantic
identity. The owner-internal compiler compatibility adapter uses `Duration::MAX` so host
scheduling does not alter objective semantics.