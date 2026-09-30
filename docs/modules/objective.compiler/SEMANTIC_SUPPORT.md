# objective.compiler semantic support matrix

**Normative execution contract:** `docs/modules/objective.compiler/NORMATIVE_EXECUTION.md`

This document is a semantic-support supplement. The normative contract owns the
canonical product API, durable versions, authority boundary and qualification
order. This matrix records the exact boundary between registered
`ObjectiveSourceEnvelopeV1` syntax, authenticated admission, owner-internal IR,
the typed feasibility engine and runtime publication. Structural decode support
is not executable compiler support. Unsupported source semantics fail closed with
`OBJ-E002`; they are never approximated, silently dropped or reinterpreted.

## Source V1 matrix

| Source V1 semantic | JSON/structure decode | Authenticated admission | Owner-internal IR | Direct typed feasibility API | Product result |
|---|---|---|---|---|---|
| constraint `eq` | yes | admitted when profile-bound | scalar `Equal` | scalar interval | compiled or typed conflict |
| constraint `lte` | yes | admitted when profile-bound | scalar `AtMost` | scalar interval | compiled or typed conflict |
| constraint `gte` | yes | admitted when profile-bound | scalar `AtLeast` | scalar interval | compiled or typed conflict |
| constraint `ne` | yes | deterministic reject | none | not lowered by Source V1 | `OBJ-E002` |
| constraint `lt` / `gt` | yes | deterministic reject | none | not lowered by Source V1 | `OBJ-E002` |
| constraint `in` / `not_in` | yes | deterministic reject | none | bounded enum Include/Exclude exists | `OBJ-E002` |
| success/terminal `eq/lte/gte` | yes | admitted when profile-bound | scalar success predicate | downstream observation semantics | compiled |
| success/terminal `ne/lt/gt` | yes | deterministic reject | none | not lowered by Source V1 | `OBJ-E002` |
| legal/forbidden/confirmation actions | yes | registered action mapping required | legal-action grammar plus intrinsic `abstain` | require/forbid/positive implication | compiled or typed conflict |
| resources | yes | all six axes map through frozen profile | generated hard `AtMost` constraints | scalar interval | compiled or typed conflict |
| risk/rollback/compensation/abstention | yes | frozen monotone mapping required | generated hard constraints | scalar interval | compiled or typed conflict |
| evidence requirements | yes | registered mapping required | success predicate with confidence bound | scalar interval | compiled |
| soft dimensions | yes | registered unit/direction/baseline required | bounded soft preferences | excluded from hard feasibility | compiled |
| immutable scope/generation atoms | not expressible by Source V1 constraint payload | n/a | n/a | supported | typed-API only |
| positive Horn action implications | not expressible by Source V1 constraint payload | n/a | n/a | supported | typed-API only |

## Q32 contract

Source V1 uses exact signed Q32 raw values. It is not a Float, Decimal or implicit
set-valued protocol. The full comparator/extreme-value regression set covers
`eq/lte/gte` at `i64::MIN`, `-1`, `0`, `1` and `i64::MAX` through:

```text
Source V1 decode
-> authenticated admission
-> native constraints and predicates
-> proof-bearing protocol projection
-> strict canonical decode
-> destination-owned RunStart publication
```

Negative product-facade tests require `ne/lt/gt/in/not_in` to publish neither a
run nor a partial proof.

## Why finite-set operators remain rejected

The registered Source V1 constraint object carries one `boundQ32` value and no
finite-set member payload. Treating that scalar as a set would invent semantics
and break canonical compatibility. The generic feasibility engine already
supports bounded enumeration domains, but Source V1 requires an additive or
successor protocol with an explicit member payload, lowering rules, versioned
proof framing and independent compatibility tests before those operators may be
admitted losslessly.

## Canonical product boundary

Agentd constructs one `ValidatedAdmissionProfileV1` at
`ObjectiveRuntimeHost::open`. Each `ObjectiveRuntimeHost::submit` authenticates a
fresh signed request, samples the owner time inside the serialized publication
boundary and calls:

```text
ValidatedAdmissionProfileV1
+ ObjectiveSourceEnvelopeV1
+ fresh ObjectiveAdmissionContextV1
-> compile_authoritative_objective_v1
-> ProofBearingObjectiveCompileV1
-> encode_proof_bearing_objective_function_v1
-> compile_and_publish_validated_objective_run_v1
-> destination-owned RunStartJournal
```

The authoritative result has no public constructor and is not cloneable. Protocol
projection rebinds the complete source-envelope proof identity and exact frozen
profile before retaining native/source/receipt validation and strict canonical
wire decoding. It does not re-run authenticated admission or native feasibility.
A hard conflict follows the durable conflict path and cannot masquerade as a
compiled objective. `ExplicitAbstain` is a valid immutable publication and grants
no effect authority.

## Static reuse is not authorization reuse

The generation-local validated profile may reuse only:

- complete static profile validation;
- exact profile digest and revision;
- compiler-contract digest;
- source lookup indexes;
- semantic-identity collision proofs.

Every submission still checks signed source identity, principal scope,
intent/schema/normalization binding, locale, freshness, exact deadline and the
selected profile. Current issuer trust, revocation, generation, fence and final-use
authority remain checks of their existing owners. Changing the profile requires a
new process generation.

## Capacity closure

The source adapter reserves ten generated native constraints before accepting
caller constraints:

```text
246 caller constraints
+ 6 resource constraints
+ 4 risk/rollback/compensation/abstention constraints
= 256 native hard constraints maximum
```

Success, terminal and evidence predicates share one maximum of 128. The compiled
legal-action set has a maximum of 128 including intrinsic `abstain`; when abstain
is implicit the caller may supply at most 127 actions. The compiler never silently
truncates an input to fit these limits.

## Hard feasibility and conflict semantics

Hard feasibility is deterministic for fixed canonical grammar, atoms and
explicit solver budgets. Soft preferences are absent from the hard solver and
cannot repair infeasibility. A conflict receipt contains a deterministic
inclusion-minimal core; no minimum-cardinality guarantee is claimed.

The direct deterministic engine reads no clock. The compatibility availability
wrapper measures elapsed host time after bounded execution. Exceeding that
threshold produces an availability disposition, not an infeasibility proof and
not hard preemption.

## Native identity, wire identity and durable evidence

`ObjectiveFunction::semantic_digest` identifies compact owner-native semantics.
The canonical `ObjectiveFunctionV1` protocol digest identifies registered JSON
transport semantics. RunStart V3 binds both complete byte strings and both
digests, plus V1 admission-proof bytes and digest.

The admission proof carries source-envelope, profile, authentication-context,
compiler-contract and admitted-source digests. Persisted bytes decode only as
historical integrity evidence. They do not reconstruct the opaque compiler
capability and do not replace current authentication or final-use checks.

RunStart V1/V2 and conflict V1 records retain their historical bytes. Recovery and
compaction do not synthesize a proof for them, and Agentd refuses them at final
use. An authorized new revision is required.

## Compatibility surfaces

The following remain compatibility, diagnostics or qualification surfaces rather
than the ordinary product path:

- raw-profile publication via `compile_and_publish_objective_run_v1`;
- two-stage raw admission/compile;
- independent authenticated revalidation via
  `encode_authenticated_objective_function_v1`;
- pre-admitted legacy compilation available only under
  `qualification-legacy-compile`.

Default and compatibility tests and strict lint run separately. Source presence or
parity fixtures do not qualify the product route.

## Evidence boundary

Exact source and deterministic synthetic-merge execution must bind one immutable
commit/tree and run the same semantic, source-map, product, compatibility and
strict-lint inventory. Candidate-owned scripts may generate diagnostics but cannot
issue trusted qualification. See `DELIVERY_EVIDENCE.md` and the normative contract
for trusted-control verification, selected-host and external acceptance gates.

No statement in this matrix grants production implementation, independent
acceptance, activation, promotion or release.
