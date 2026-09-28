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

The existing Agentd product route calls the intelligence facade
`compile_and_publish_objective_run_v1`. Its compiler/publication sequence is:

```text
ObjectiveSourceEnvelopeV1 + current authenticated ObjectiveAdmissionContextV1
+ ValidatedAdmissionProfileV1
-> compile_authoritative_objective_v1(...)
-> ProofBearingObjectiveCompileV1
-> encode_proof_bearing_objective_function_v1(&outcome, &source, &profile)
-> destination-owner RunStartJournal
```

The proof-bearing value has no public constructor or mutable outcome access. Encoding
checks the complete source-envelope proof identity and the exact frozen profile, then
retains the existing native/source/admission/protocol validation and strict canonical
wire decoder. It does not repeat authenticated admission or native feasibility solving.
A hard conflict follows the existing conflict-journal path and cannot be projected into
a compiled run. `ExplicitAbstain` remains a valid immutable publication with no effect authority.

The lower-level `admit_objective_v1 -> AdmittedObjectiveV1 -> compile_admitted_objective_v1`
API remains available; it is not the recommended product publication composition.
`encode_authenticated_objective_function_v1` remains the compatibility/revalidation
entrypoint for callers holding separate receipts and the original authenticated context.
It independently repeats admission and compilation. `encode_objective_function_v1` is
crate-private, not a public product bypass.

`AdmittedObjectiveV1` has no public raw-source constructor. The legacy
`ObjectiveSourceEnvelope -> compile` surface is no longer exported by default. It exists only
as `compile_prevalidated_legacy_objective_v1` under the explicit
`qualification-legacy-compile` Cargo feature for historical qualification fixtures.

### Static reuse is not authorization reuse

The current facade still constructs a validated profile from the raw profile on each
request, and the strict projection still validates its raw profile. Full process-generation
profile caching is not claimed by this change. A future reuse key must bind profile digest,
revision and compiler-contract identity. Current issuer trust, source identity, time,
revocation, generation, fence and final-use authority must continue to be checked by the
existing owners for every applicable request/use; none are cacheable grants.

## Canonical ObjectiveFunctionV1 publication

After authoritative compilation, product publication uses
`encode_proof_bearing_objective_function_v1` in `hepta-objective/src/proof_projection.rs`.
The artifact retains the registered canonical JSON representation, strict projection
checks, re-decoding of exact bytes, and a protocol-wire digest. The parity regression
compares this artifact with the compatibility encoder's independent recompilation;
metadata, supplied-intent and profile substitutions have dedicated rejection tests.
Test source presence is not an execution pass receipt.

The protocol-wire digest is intentionally **not** the native
`ObjectiveFunction::semantic_digest`. The native digest identifies the compact compiler
semantics used by `RunStartSnapshotV1.objectiveDigest`; the protocol digest identifies the
registered JSON transport including explicit evidence requirements, legal/forbidden actions,
resource endowment and deadline. The durable run-start v2 record binds both identities.
Legacy v1 records may be decoded for migration/recovery inspection but cannot be admitted
to Agentd runtime final use without the canonical protocol identity. The facade's returned
admission-proof digest is distinct from durable proof persistence; the latter requires its
own versioned storage/recovery closure and is not established by an in-memory proof alone.

## Feasibility determinism

The constraint solver is deterministic for a fixed validated grammar, canonical atom set and
oracle-call budget. The explicit availability API additionally accepts a wall-clock budget and
records elapsed host time; exhaustion near that deadline is host-sensitive and is not semantic
identity. The owner-internal compiler compatibility adapter uses `Duration::MAX` so host
scheduling does not alter objective semantics.

## Exact-candidate evidence

See [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md) for the read-only source/merge execution
recorder, interpretation of missing or failed commands, and the remaining independent
and selected-target-host gates. No source declaration in this matrix grants acceptance,
activation, promotion or release.
