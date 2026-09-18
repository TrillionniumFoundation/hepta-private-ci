# objective.compiler semantic support matrix

This matrix separates the public `ObjectiveSourceEnvelopeV1` wire language from
the explicit typed feasibility API. A capability in `RegisteredGrammarV1` is
not automatically a capability of the objective source wire protocol.

## Production admission and compile path

The product path is:

```text
bounded JSON bytes
-> decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> admit_objective_v1
   -> authenticate source/principal
   -> verify source/schema/normalization/intent/profile digests
   -> validate freshness/deadline
   -> map registered source semantics into the native bounded envelope
   -> AdmittedObjectiveV1
-> compile_admitted_objective_v1
   -> compiler::compile
      -> scalar_adapter::scalar_conflict
         -> check_feasibility_v1
-> ObjectiveAdmissionReceiptV1 + ObjectiveCompileReceipt | ObjectiveConflictReceipt
-> intelligence.control::ObjectiveProductCallerV1
   -> atomic durable publication of admission receipt, compiled objective and RunStartSnapshotV1
```

`AdmittedObjectiveV1` is opaque and has no public constructor other than
`admit_objective_v1`. The raw legacy compiler is not part of the default crate
API; qualification-only callers must explicitly opt into
`legacy-prevalidated-objective`.

## Source comparator support

| Source surface | V1 wire admission | Native representation | Feasibility behavior | Runtime objective outcome |
|---|---|---|---|---|
| predicate `eq` | supported | `ConstraintRelation::Equal` | scalar equality | compiled |
| predicate `lte` | supported | `ConstraintRelation::AtMost` | scalar upper bound | compiled |
| predicate `gte` | supported | `ConstraintRelation::AtLeast` | scalar lower bound | compiled |
| constraint `eq` | supported | `ConstraintRelation::Equal` | scalar equality | compiled or hard conflict |
| constraint `lte` | supported | `ConstraintRelation::AtMost` | scalar upper bound | compiled or hard conflict |
| constraint `gte` | supported | `ConstraintRelation::AtLeast` | scalar lower bound | compiled or hard conflict |
| `ne`, `lt`, `gt` | rejected at strict JSON ingress | none | none | no objective published |
| `in`, `not_in` | rejected at strict JSON ingress in ObjectiveSourceEnvelopeV1 | none | none through product admission | no objective published |

Programmatic construction of the broader source comparator enums remains
fail-closed in admission. It is not a compatibility promise for the V1 wire
protocol.

## Explicit typed feasibility API

`check_feasibility_v1` independently supports registered bounded atoms:

| Registered domain | Predicates |
|---|---|
| scalar | `ScalarInterval` |
| finite enumeration | `Include`, `Exclude` |
| action | `RequireAction`, `ForbidAction`, positive `Implies` |
| immutable identity | `IdentityEqual` |

Those operations are available only to callers that already possess a
`RegisteredGrammarV1` with registered axes, units, evidence sources and a
nonzero schema digest. They do not widen `ObjectiveSourceEnvelopeV1`.

## Determinism boundary

The semantic solver and canonical ordering are deterministic for identical
typed inputs. The explicit feasibility API may additionally enforce a caller
supplied wall-clock availability budget; `Exhausted` and the diagnostic
`elapsed` duration are therefore host-observed availability data, not
byte-for-byte deterministic semantic state.

The admitted compile path uses the compatibility scalar adapter with the
deterministic `n + 1` oracle-call ceiling and no host wall-clock cutoff, so
host scheduling cannot change a valid admitted objective into an exhausted
compile.
