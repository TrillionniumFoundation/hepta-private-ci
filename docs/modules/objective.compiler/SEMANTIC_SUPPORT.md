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

Evidence `minimumConfidencePpm` lowers to
`ceil(ppm * 2^32 / 1_000_000)` so the native minimum never falls below the
registered ppm threshold. The canonical wire preserves the original ppm value.
The resulting `conservative-q32-confidence` compiler-contract revision invalidates
predecessor proof bindings at current Agentd final use; it does not rewrite
historical records. A newly authorized objective revision/request is required,
as specified in the [normative migration contract](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md#6-proof-and-protocol-projection).

## Why `in` / `not_in` remain rejected

The registered Source V1 constraint object currently carries one `boundQ32` and has no
finite-set member payload. Interpreting that scalar as a set would invent semantics and break
canonical compatibility. The generic feasibility engine already supports bounded enum domains,
but Source V1 needs a separately registered additive or successor protocol representation before
those operators can be admitted losslessly.

## Public API boundary

The existing Agentd product route validates and freezes its owner-local profile once in
`ObjectiveRuntimeHost::open`. Each `ObjectiveRuntimeHost::submit` then constructs a fresh
authenticated admission context and calls the intelligence façade
`compile_and_publish_validated_objective_run_v1`. Its compiler/publication sequence is:

```text
process-generation ValidatedAdmissionProfileV1
+ ObjectiveSourceEnvelopeV1
+ current authenticated ObjectiveAdmissionContextV1
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

The raw-profile façade `compile_and_publish_objective_run_v1` remains a compatibility entrypoint:
it validates one raw profile and delegates to the validated-profile publication function. The
lower-level `admit_objective_v1 -> AdmittedObjectiveV1 -> compile_admitted_objective_v1`
API also remains available; neither is the normal Agentd product composition.
`encode_authenticated_objective_function_v1` remains the compatibility/revalidation
entrypoint for callers holding separate receipts and the original authenticated context.
It independently repeats admission and compilation. `encode_objective_function_v1` is
crate-private, not a public product bypass.

`AdmittedObjectiveV1` has no public raw-source constructor. The legacy
`ObjectiveSourceEnvelope -> compile` surface is no longer exported by default. It exists only
as `compile_prevalidated_legacy_objective_v1` under the explicit
`qualification-legacy-compile` Cargo feature for historical qualification fixtures.

### Static reuse is not authorization reuse

`ObjectiveRuntimeHost::open` constructs one opaque `ValidatedAdmissionProfileV1` for the
process generation. Reuse is bound to the exact profile digest, profile revision and
compiler-contract digest and covers only static profile validation, indexes and collision
proofs. The host does not expose a caller-controlled cache key or skip-validation flag.

Every submission still authenticates the signed source and checks source identity, principal
scope, intent/schema/normalization binding, locale, freshness, deadline and exact selected
profile. Current issuer trust, revocation, generation, fence and final-use authority remain
checks of their existing owners for every applicable request/use; none are cached grants.
Changing the owner-local profile requires a new process generation rather than mutating the
frozen profile in place.

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
resource endowment and deadline. The durable run-start v3 record binds both identities
and the complete versioned admission-proof evidence. Historical v1/v2 records retain
their original byte identities when decoded for migration/recovery inspection; they do
not acquire a fabricated proof. Agentd runtime admission requires the canonical protocol
identity, the persisted proof and the current frozen-profile/compiler-contract binding.
The façade persists this evidence in the same destination-owner transaction before
returning its proof digest; decoding it does not reconstruct an opaque compiler capability
or replace current authentication and final-use checks.

## Feasibility determinism

The constraint solver is deterministic for a fixed validated grammar, canonical atom set and
oracle-call budget. The explicit availability API additionally accepts a wall-clock budget and
records elapsed host time; exhaustion near that deadline is host-sensitive and is not semantic
identity. The owner-internal compiler scalar adapter calls
`check_feasibility_deterministic_v1` directly, so host scheduling does not alter objective
semantics or add wall-clock observations to that path.

## Exact-candidate evidence

See [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md) for the read-only source/merge execution
recorder, interpretation of missing or failed commands, and the remaining independent
and selected-target-host gates. No source declaration in this matrix grants acceptance,
activation, promotion or release.

## 2026-09-29 bounded Source V1 closure

Source V1 continues to use exact signed Q32 raw values, not Float/Decimal or
set-valued operands. The new regression cross-product checks `eq/lte/gte` at
`i64::MIN`, -1, 0, 1 and `i64::MAX` through authoritative admission, native
constraints, proof-bound protocol encoding, strict canonical decoding and the
real intelligence-to-RunStart publication facade. Negative facade tests ensure
`ne/lt/gt/in/not_in` publish neither a run nor a partial proof. This completes
coverage of the existing scalar contract rather than silently broadening V1.

Source-envelope proof framing now has one crate-owned implementation shared by
issuance and proof projection. The seven-owner preflight uses the validated
admission entrypoint. The separate authenticated-recompilation encoder remains
an independent parity/reference and compatibility check for callers holding
separate receipts; it is not substituted into the ordinary single-compilation
publication path. Broader typed semantics still require an explicit new source
contract, lowering, verifier and versioned evidence; their absence does not
justify implicit coercion of V1 inputs.
