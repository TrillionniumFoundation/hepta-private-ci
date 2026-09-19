# objective.compiler semantic support matrix

This matrix separates **wire syntax**, **authenticated admission**, **native compiler IR** and the standalone typed feasibility API. A syntax accepted by the strict JSON decoder is not necessarily a semantic operation supported by `ObjectiveSourceEnvelopeV1` admission.

| Source V1 comparator | Admission | Native representation | Result |
|---|---|---|---|
| `eq` | supported | `ConstraintRelation::Equal` | compiled |
| `lte` | supported | `ConstraintRelation::AtMost` | compiled |
| `gte` | supported | `ConstraintRelation::AtLeast` | compiled |
| `ne` | rejected | none | `OBJ-E002` |
| `lt` | rejected | none | `OBJ-E002`; never rounded to `lte` |
| `gt` | rejected | none | `OBJ-E002`; never rounded to `gte` |
| `in` | rejected in Source V1 | none | `OBJ-E002`; V1 has no bounded set payload |
| `not_in` | rejected in Source V1 | none | `OBJ-E002`; V1 has no bounded set payload |

The standalone `check_feasibility_v1` API is intentionally richer. Its registered typed grammar supports scalar intervals, finite-enum `Include`/`Exclude`, action `Require`/`Forbid`, bounded positive `Implies`, and immutable identity equality. That capability **must not be inferred to be reachable from Source V1**. A future source protocol that carries a bounded enum set can map to `Include` or `Exclude` without changing V1 meaning.

## Actual native call graph

```text
decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> canonical_objective_intent_digest_v1
-> admit_and_compile_objective_v1
-> adapt_source
-> compile                         # crate-private production core
-> scalar_conflict                 # legacy FixedQ32 compatibility adapter
-> check_feasibility_v1            # typed feasibility solver
```

The old public `compile(ObjectiveSourceEnvelope)` entrypoint is no longer part of the default public API. Qualification fixtures may opt into `qualification-legacy-compiler` and call `compile_qualification_fixture`; product consumers must enter through authenticated admission.

## Determinism boundary

`compile` is semantically deterministic: its scalar compatibility call uses an oracle call ceiling with `Duration::MAX`, so host scheduling cannot turn an otherwise valid compile into an exhaustion result.

`check_feasibility_v1` is different. For a fixed candidate set and call budget its solver and conflict-minimization order are deterministic, but callers may also supply a finite wall-clock budget. Near that deadline, host scheduling may change the **availability disposition** to `Exhausted`, and `elapsed` is observational rather than canonical semantic state. The API therefore separates deterministic semantics from time-bounded availability.

## Claim boundary

Every represented Source V1 field has a deterministic disposition: it is either mapped exactly or rejected explicitly. “Decoded successfully” and “represented by the source enum” do not mean “supported end-to-end”.
