# Objective compiler execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Bound modules:** `objective.compiler`, `intelligence.control`, `kernel.authority`, `learning.ledger`  
**Source target:** `codex-rs/hepta-objective`  
**Canonical error registry:** `docs/contracts/OBJECTIVE_ERRORS.json`  
**Retry-policy companion:** `docs/contracts/OBJECTIVE_RETRY_POLICY.json`

## 1. Scope and authority boundary

`objective.compiler` converts one bounded, authenticated request into an immutable native objective revision. It does not infer authority from prose, relax a hard constraint, rewrite an objective during a run, select an action or execute an effect. Output remains advisory until the existing authority owner independently authorizes a concrete operation.

The public V1 admission path is:

```text
bounded JSON bytes
-> decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> authenticate source and principal scope
-> bind exact ObjectiveAdmissionProfileV1 digest
-> validate/map every represented V1 semantic field
-> check_feasibility_v1 over the complete mapped V1 scalar hard-constraint set
-> native compile
-> ObjectiveAdmissionReceiptV1
-> ObjectiveCompileReceiptV1 | ObjectiveConflictReceiptV1
```

The native compiler intentionally retains its historical scalar feasibility check as a defense-in-depth compatibility recheck. It is not the sole feasibility gate on the public V1 admission path. No stage may silently drop a represented constraint, action, success predicate, resource ceiling, risk rule, evidence requirement or provenance field. A decoder or structural validator is not semantic admission. A profile label is not authentication. The admitted source digest binds the supplied source digest, authenticated source class and selected profile.

`check_feasibility_v1` is a richer general solver than the V1 source dialect. The solver supports scalar intervals, finite-enum include/exclude atoms, positive action implications and immutable identity atoms. `ObjectiveSourceEnvelopeV1`, however, carries only one Q32 hard-constraint bound and no enum-set or action-implication payload. Therefore the canonical V1 source-to-objective path uses the **scalar subset** of the general solver. Finite-enum intersection and positive action implication are solver capabilities, not claims that V1 bounded JSON can express them.

## 2. Input grammar and canonical/native IR boundary

The accepted V1 structured grammar is bounded and contains:

```text
identity: request, principal scope, locale, source trust and observed time
success: predicates, terminal conditions and evidence requirements
actions: legal classes, forbidden classes and required-confirmation classes
constraints: constitutional, principal, environment and task scalar constraints
preferences: soft dimensions with units, direction and bounded weight range
resources: time, token, compute, memory, network and effect ceilings
risk: risk class, abstention rule, rollback and compensation requirements
provenance: exact source and normalization-profile digests
```

Free text is evidence for intent extraction, never the final authority representation. Every predicate has an identifier, unit, comparator, bound, evidence source and terminality. Arrays are stable-sorted by semantic identifier. Unicode uses the selected normalization profile; timestamps are UTC; durations are integer microseconds; numeric values use registered fixed-point profiles. Duplicate semantic keys are rejected.

`ObjectiveConstraintComparatorV1` preserves protocol spellings `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in` and `not_in` so unknown/unrepresentable semantics fail closed instead of being rewritten. The V1 row has only `bound_q32`; it has no set payload. The native V1 adapter therefore accepts only `eq`, `lte` and `gte`. `ne`, strict inequalities, `in` and `not_in` return `UnsupportedComparator`. A terminal hard constraint remains unrepresentable by the native `Constraint` type and returns `TerminalConstraintUnsupported`.

The owner-local native `ObjectiveFunction` deliberately remains smaller than the canonical `ObjectiveFunctionV1` wire contract. Success predicates, terminal conditions, evidence requirements and resource/risk fields are lowered into the native owner IR for deterministic compilation, then `project_objective_function_v1` validates the admitted source/IR binding and emits the exact canonical JSON projection. `RunStartSnapshotV1::bind` binds its digest to the frozen run identity. The crate exports `ObjectiveCompileReceiptV1` as a stable alias for the native receipt; the public product path must use authenticated admission and the canonical projection rather than treating the internal IR as the wire object.

Admission profiles are bounded to 256 constraint mappings, 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and a nominal 256 KiB profile-size guard. V1 source bounds are intentionally tighter where admission adds native rows:

```text
source hard constraints: <=246
admission-generated resource constraints: exactly 6
admission-generated risk constraints: exactly 4
native hard-constraint aggregate: <=256

successPredicates + terminalConditions + evidenceRequirements: <=128 aggregate
caller legalActionClasses when abstain is implicit: 0..=127
compiled legal actions including intrinsic abstain: <=128
```

These are semantic-capacity bounds, not post-hoc truncation rules. The canonical readiness protocol registry now matches these enforced V1 source bounds: caller legal actions are 0..=127, source hard constraints are <=246 before the ten generated resource/risk rows, and the success/terminal/evidence aggregate is <=128. Any future widening requires a versioned protocol or a matching implementation change.

## 3. Constraint precedence and conflict resolution

Precedence is lexicographic and non-compensable:

```text
P0 constitutional authority, truth, privacy, deletion and writer ownership
P1 explicit principal scope and forbidden effects
P2 environment and adapter safety constraints
P3 task success predicates and terminal conditions
P4 soft utility preferences and resource allocation
```

A lower class cannot offset a higher-class violation. Soft atoms never participate in hard feasibility. The general feasibility API deterministically intersects registered scalar and finite-enum atoms and closes registered positive action implications. The V1 bounded source path currently emits only scalar hard atoms because its wire row cannot carry enum sets or implications. Unsupported operators, arbitrary code, unrestricted quantifiers, nonlinear arithmetic and unbounded recursion reject before solving.

For infeasible hard constraints, deterministic deletion filtering returns an **inclusion-minimal** unsatisfied set in canonical order. It does not claim minimum cardinality. A hard conflict is represented by `ObjectiveConflictReceiptV1`, not by reusing an unrelated error code. Oracle exhaustion preserves the original objective and emits unavailable; it never publishes a partial core that permits dropping a hard constraint.

## 4. Deterministic compilation algorithm

### 4.1 Legal-action grammar and intrinsic abstain

`abstain` is a compiler-intrinsic, confirmation-free safety action. It is present in every successfully compiled legal set. A caller may include it explicitly in the lower-level native compiler API, but bounded V1 admission reserves one slot for intrinsic abstain and therefore accepts `0..=127` caller legal action classes.

```text
bounded V1 caller legalActionClasses: 0..=127
native direct compiler with explicit abstain: <=128
compiled legal action ceiling: 128
```

A requested action that is also forbidden produces an explicit conflict receipt. Zero requested legal actions still leaves intrinsic abstain and yields `CompileDisposition::ExplicitAbstain`. An attempt to forbid or confirmation-gate abstain is `OBJ-E006` and publishes no objective.

`CompileDisposition::ExplicitAbstain` is a successful non-error objective outcome. The legacy read-only vertical facade historically translated it to `ReadOnlyVerticalError::ObjectiveExplicitAbstain`; new callers should use `run_read_only_vertical_outcome_v1`, which exposes `ReadOnlyVerticalOutcomeV1::ExplicitAbstain` as a non-error control outcome for metrics/retry/telemetry compatibility.

### 4.2 Deterministic compilation steps

```text
validate raw byte and structural/aggregate bounds
verify authenticated source context and principal scope
verify schema, normalization, source, intent and profile digests
validate locale, observation time, deadline and source freshness
validate all represented predicate/action/preference/evidence mappings
map registered V1 hard constraints plus generated resource/risk constraints
normalize identifiers, units, times and fixed-point values
classify constraints into P0..P4
reject duplicate or contradictory semantic identity
run profile-bound general feasibility over mapped V1 scalar hard atoms
construct legal action grammar with intrinsic abstain
construct native success/terminal/evidence predicates
stable-sort every native set and encode native canonical semantics
compute hard-constraint and objective semantic digests
emit deny-all admission receipt and compile/conflict outcome
```

Compilation is a pure function of the authenticated source envelope, selected admission profile and registered schema revisions. Retry with identical inputs yields identical semantic bytes. Reuse of a durable request/revision identity with different semantics is handled by the owning durable caller as conflict; the stateless compiler does not invent persistence.

## 5. State machine and persistence

The compiler owns no domain-fact store. The target product contract requires the owning caller to persist the canonical `ObjectiveFunctionV1`, `RunStartSnapshotV1` and admission/compile receipts atomically enough that no run can observe an objective revision without its matching run-start snapshot.

```text
received
-> decoded
-> structurally_validated
-> authenticated
-> profile_bound
-> normalized/mapped
-> feasibility_resolved
-> compiled | conflict | rejected | unavailable
-> canonical projection + durable publication by owning caller
```

The current source candidate closes the in-crate admission/feasibility boundary but **does not establish** the production caller, canonical `ObjectiveFunctionV1` wire projection, owner store, atomic `RunStartSnapshotV1` publication or reconciliation loop. The read-only intelligence vertical remains an integration harness, not proof of production persistence. Those items stay qualification/product-composition gaps until a named authenticated consumer and owner store exist.

A crash before caller publication leaves no selected objective. A crash after durable publication must be reconciled by an identity that includes request, principal scope, source digest, schema digest and selected profile digest. A changed success predicate, hard constraint, legal effect, evidence requirement, resource/risk rule, principal scope or rollback class creates a new objective revision and a new run snapshot.

## 6. Error taxonomy and retry policy

The canonical code definitions remain in `docs/contracts/OBJECTIVE_ERRORS.json`:

| Code | Stable class | Disposition |
|---|---|---|
| `OBJ-E001` | invalid bounded structure, numeric representation or arithmetic | rejected |
| `OBJ-E002` | unknown, unsupported or unrepresentable semantics | rejected |
| `OBJ-E003` | principal, trust or authenticated scope mismatch | authority rejected |
| `OBJ-E004` | source/schema/profile/normalization/intent integrity mismatch | integrity rejected |
| `OBJ-E005` | unit, direction or semantic-profile mismatch | rejected |
| `OBJ-E006` | intrinsic abstain unavailable or confirmation-gated | rejected |
| `OBJ-E007` | locale/freshness/deadline or feasibility availability condition | unavailable/requires caller policy |
| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |
| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |

`OBJ-E007` remains one stable code for compatibility, but **is not uniformly safe for blind retry**. `docs/contracts/OBJECTIVE_RETRY_POLICY.json` and the Rust `ObjectiveRetryDirectiveV1` classifier distinguish:

- feasibility-budget exhaustion: same-input retry may be appropriate;
- future-dated source: retry only after time advances into the allowed skew window;
- stale source: refresh the source;
- locale rejection or missing/invalid/expired deadline: correct/new request required.

`ObjectiveConflictReceiptV1` and `CompileDisposition::ExplicitAbstain` are typed non-error outcomes. Rust variants, documentation and external adapters must be checked against the canonical registry; no component may assign a local alternate meaning to a code.

Fallback may reuse a previously selected immutable objective only when the owning caller proves equal request identity, principal scope, compatibility and current revocation frontier. Otherwise it asks for clarification or abstains. It never substitutes an easier goal.

## 7. Security and adversarial inputs

Untrusted pages, emails, files, tool output and model prose remain evidence. They cannot create P0-P2 constraints, legalize an effect, change principal scope or weaken evidence requirements. Negative fixtures include prompt injection, hidden HTML instructions, homograph identifiers, duplicate JSON keys, oversized arrays, NaN/infinity equivalents, conflicting time units, path traversal, embedded secrets, forged trust labels and stale/future observations.

The compiler records safe identifiers and digests rather than unrestricted source text. It has no model, tool, network, filesystem, secret, Matrix, fleet or external-effect authority. Every admission receipt embeds `AuthorityPosture::DENY_ALL`.

## 8. Performance envelope

The following paths are measured separately:

| Path | Bound/complexity |
|---|---|
| raw JSON guard and structural decode | `<=256 KiB`, bounded field and collection counts |
| normalization and canonical sorting | `O(n log n)` |
| one ordinary feasibility oracle call | profile-specific `C(n)` |
| inclusion-minimal conflict extraction | at most `n+1` oracle calls and `O(n C(n))` |
| legal-action construction | `O(a log a)` with compiled `a<=128` |

Pilot ceilings for bounded V1 admission are `<=246` source hard constraints plus exactly ten generated hard constraints, `<=128` aggregate success/terminal/evidence predicates, `<=127` caller legal actions, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls. The in-crate canonical gate uses the deterministic call budget with wall-clock cancellation disabled; host latency budgets and measurements belong to product composition and must not alter semantic results.

The p95/p99 targets apply only to a named path, fixture and host. A normal-path latency measurement cannot be reused as a conflict-extraction measurement. No network or synchronous central RPC is permitted on the deterministic compiler path. The target-host execution procedure is `docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md`, with recorder `scripts/hepta-objective-target-measure.py`.

The current `profile_encoded_size()` guard is owner-local manual byte accounting rather than measurement of an exact canonical profile wire encoding. If 256 KiB remains a protocol-hard profile boundary, the exact canonical encoding must be defined and its actual byte length enforced before that boundary is called canonical.

## 9. Golden fixtures and tests

- `OBJ-GV-001`: reordered equivalent input produces identical objective semantics.
- `OBJ-GV-002`: a principal network prohibition dominates task text requesting network access.
- `OBJ-GV-003`: equivalent normalized Unicode produces identical canonical bytes under the selected profile.
- `OBJ-GV-004`: duplicate semantic identifiers reject before digest publication.
- `OBJ-GV-005`: changing a soft weight changes the objective digest but not the hard-constraint digest.
- `OBJ-GV-006`: untrusted evidence cannot create a privileged constraint or legal action.
- `OBJ-GV-007`: forbidding or confirmation-gating abstain returns `OBJ-E006`.
- `OBJ-GV-008`: zero caller actions admit successfully as `ExplicitAbstain`; 127 caller actions reserve the intrinsic abstain slot; 128 caller actions reject at the bounded source boundary.
- `OBJ-GV-009`: source, intent, schema, normalization and selected-profile digest mismatches fail before feasibility/compile publication.
- `OBJ-GV-010`: unsupported or exhausted feasibility never weakens the original legal set.
- `OBJ-GV-011`: 247 source constraints reject structurally because admission must reserve ten generated hard-constraint slots.
- `OBJ-GV-012`: individually valid success/terminal/evidence arrays reject when their native aggregate exceeds 128.
- `OBJ-GV-013`: a profile-bound contradictory scalar pair returns an inclusion-minimal typed conflict at the public admission boundary.

Tests cover structural decoding, canonical ordering, unit conversion, conflict minimization, stale/future time, deadline handling, source authentication, resource overflow, aggregate hostile bounds, action-slot reservation, zero-action abstention, redaction and retry classification.

## 10. Implementation sequence and remaining architecture work

Implemented/maintained V1 sequence: strict JSON decoder; owner-local source type; structural and aggregate validator; authenticated admission context; frozen profile mapping; profile-bound general-feasibility gate for all V1 hard scalar atoms; conflict minimizer; intrinsic legal-action grammar; native canonical digests; deny-all receipts.

Remaining work must be kept separate instead of implied by source composition:

1. keep `PROTOCOLS.json` and generated protocol projections aligned with the enforced V1 source/aggregate bounds;
2. define a versioned source grammar that actually carries finite-enum set payloads and positive action implications before routing those domains from source to the general solver;
3. replace manual profile-size estimation with an exact canonical encoded-byte bound if 256 KiB remains protocol-hard;
4. remove or explicitly deprecate the success-path `removed_action_ids` field if no future successful disposition can populate it;
5. obtain terminal exact-head and deterministic synthetic-merge evidence for the current combined candidate;
6. qualify `admit_publish_and_start_objective_run_v1` on the named target host for crash/restart, concurrent publication, backpressure, ordinary-admission latency and conflict-extraction latency;
7. keep independent acceptance, activation, promotion and release external to source qualification.

Coding entry still requires a current `CanonicalSourceReceiptV1`, frozen contract/readiness/error-registry digests, bounded work-package scope, mandatory fixtures, deterministic fallback and zero authority delta. Source completion does not establish activation, independent acceptance, promotion or release.

## 11. Coding-entry checklist

- exact canonical source receipt and immutable profile digest are current;
- source arrays and their lowered aggregates remain within the actual native ceilings;
- every V1-representable source semantic maps without truncation or guessing;
- unsupported V1 comparators fail closed instead of being described as implemented rich wire semantics;
- intrinsic `abstain`, hard-feasibility, aggregate-bound and conflict fixtures pass;
- `PROTOCOLS.json` matches the enforced V1 source/aggregate bounds;
- outputs remain deny-all and the durable caller boundary is named rather than inferred;
- canonical wire projection and caller-owned run-start publication remain source-implemented and are requalified on the exact candidate;
- exact-head and synthetic-merge checks pass before source completion is claimed.

## Appendix A. Closed gap and protocol mapping

This appendix is a traceability projection. Normative identifiers remain in `READINESS.json`, `PROTOCOLS.json`, `GAPS.json` and `OBJECTIVE_ERRORS.json`; this Markdown file does not override a registry record.

Readiness protocols bound to this work include:

- `ObjectiveSourceEnvelopeV1`
- `ObjectiveConstraintSetV1`
- `ObjectiveConflictReceiptV1`
- `ObjectiveCompileReceiptV1`

Documentation/readiness gap identifiers already represented in the canonical readiness registries include:

- `RDY-GAP-OBJ-001`
- `RDY-GAP-OBJ-002`
- `RDY-GAP-OBJ-003`
- `RDY-GAP-OBJ-004`
- `RDY-GAP-OBJ-005`
- `RDY-GAP-OBJ-006`

Bound work packages include `OBJ-0-OBJECTIVE-CONTRACTS` and `OBJ-1-OBJECTIVE-COMPILER`. This candidate does not convert their documentation closure into production caller, independent acceptance, activation, promotion or release authority.
