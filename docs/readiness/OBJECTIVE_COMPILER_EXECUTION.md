# Objective compiler execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Bound modules:** `objective.compiler`, `intelligence.control`, `kernel.authority`, `learning.ledger`  
**Source target:** `codex-rs/hepta-objective`  
**Canonical error registry:** `docs/contracts/OBJECTIVE_ERRORS.json`

## 1. Scope and authority boundary

`objective.compiler` converts one bounded, authenticated request into an immutable objective revision. It does not infer authority from prose, relax a hard constraint, rewrite an objective during a run, select an action or execute an effect. Output remains advisory until the existing authority owner independently authorizes a concrete operation.

The current native admission call graph is:

```text
bounded JSON bytes
-> decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> authenticate source and principal scope
-> bind exact ObjectiveAdmissionProfileV1 digest
-> normalize/map V1-executable source semantics into ObjectiveSourceEnvelope
-> compile
   -> native_feasibility::check_native_feasibility_v1
      -> check_feasibility_v1(RegisteredGrammarV1, ConstraintAtomV1, bounded budget)
   -> freeze legal actions, predicates, digests and native objective receipt
-> ObjectiveAdmissionReceiptV1
-> ObjectiveCompileReceipt | ObjectiveConflictReceipt
```

This ordering is intentional: `compile` owns the mandatory feasibility stage for the native IR. Documentation must not describe `admit_and_compile_objective_v1` as independently invoking a second rich-feasibility pass before `compile`.

No stage may silently drop a represented constraint, action, success predicate, resource ceiling, risk rule, evidence requirement or provenance field. A decoder or structural validator is not semantic admission. A profile label is not authentication. The admitted source digest binds the supplied source digest, authenticated source class and selected profile.

## 2. Input grammar and canonical IR

The bounded source grammar contains:

```text
identity: request, principal scope, locale, source trust and observed time
success: predicates, terminal conditions and evidence requirements
actions: legal classes, forbidden classes and required-confirmation classes
constraints: constitutional, principal, environment and task constraints
preferences: soft dimensions with units, direction and bounded weight range
resources: time, token, compute, memory, network and effect ceilings
risk: risk class, abstention rule, rollback and compensation requirements
provenance: exact source and normalization-profile digests
```

Free text is evidence for intent extraction, never the final authority representation. Arrays are stable-sorted by semantic identifier. Unicode uses the selected normalization profile; timestamps are UTC; durations are integer microseconds; numeric values use registered fixed-point profiles. Duplicate semantic keys are rejected.

### 2.1 V1 capability boundary

The general feasibility API is richer than `ObjectiveSourceEnvelopeV1`. `check_feasibility_v1` supports registered scalar intervals, finite-enum include/exclude sets, positive action implications and immutable identity equality. The current source constraint payload, however, carries a single scalar `boundQ32`; it has no bounded enum-set payload and no action-implication payload.

Therefore current canonical admission executes only scalar constraint/predicate relations that can be represented without approximation: `eq`, `lte` and `gte`. `ne`, strict `<`/`>`, `in`, `not_in` and terminal hard constraints fail closed as unsupported/unrepresentable semantics. Finite-enum intersection and positive action implications are capabilities of the registered feasibility API, **not** claims about the complete `ObjectiveSourceEnvelopeV1 -> ObjectiveFunction` path. A future source-contract revision must add bounded typed payloads before those operators may become executable admission semantics.

### 2.2 Admission-safe structural ceilings

Bounds are enforced against the final native aggregate, not only against each source array in isolation:

```text
native hard-constraint ceiling: 256
fixed generated resource constraints: 6
fixed generated risk/rollback/compensation/abstention constraints: 4
source constraint ceiling: 246

native success-predicate ceiling: 128
successPredicates + terminalConditions + evidenceRequirements: <=128 aggregate

source action-array ceiling: 128
caller legal-action ceiling when abstain is implicit: 127
compiled legal-action ceiling: 128 including intrinsic abstain
```

Admission profiles remain bounded to 256 constraint mappings, 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and a 256 KiB profile guard. Risk and rollback levels must be monotone.

## 3. Constraint precedence and conflict resolution

Precedence is lexicographic and non-compensable:

```text
P0 constitutional authority, truth, privacy, deletion and writer ownership
P1 explicit principal scope and forbidden effects
P2 environment and adapter safety constraints
P3 task success predicates and terminal conditions
P4 soft utility preferences and resource allocation
```

A lower class cannot offset a higher-class violation. Soft atoms never participate in hard feasibility. The registered feasibility engine deterministically intersects scalar and finite-enum domains and performs bounded positive-action implication closure when such atoms are supplied through its direct typed API. The V1 source-admission path currently projects its executable hard constraints as scalar atoms only. Unsupported operators, arbitrary code, unrestricted quantifiers, nonlinear arithmetic and unbounded recursion reject before solving.

For infeasible hard constraints, deterministic deletion filtering returns an **inclusion-minimal** unsatisfied set in canonical order. It does not claim minimum cardinality. A hard conflict is represented by `ObjectiveConflictReceipt`, not by reusing an unrelated error code. Oracle exhaustion preserves the original objective and emits unavailable; it never publishes a partial core that permits dropping a hard constraint.

## 4. Deterministic compilation algorithm

### 4.1 Legal-action grammar and intrinsic abstain

`abstain` is a compiler-intrinsic, confirmation-free safety action. It is present in every successfully compiled legal set. A caller may include it explicitly, but may not forbid it or require confirmation.

The bounded JSON path permits an empty caller legal-action set. The compiler then injects intrinsic abstain and returns `CompileDisposition::ExplicitAbstain`; this is a successful non-error outcome.

The compiled action ceiling is `128`, including the intrinsic abstain slot:

```text
caller omits abstain: caller action ceiling = 127
caller includes abstain explicitly: source action ceiling = 128
compiled legal action ceiling: 128
```

A requested action that is also forbidden produces an explicit conflict receipt. An attempt to forbid or confirmation-gate abstain is `OBJ-E006` and publishes no objective.

### 4.2 Deterministic compilation steps

```text
validate raw byte and admission-safe structural bounds
verify authenticated source context and principal scope
verify schema, normalization, source, intent and profile digests
validate locale, observation time, deadline and source freshness
map only registered V1-executable constraints, predicates, actions, resources and risk rules
normalize identifiers, units, times and fixed-point values
reject duplicate semantic identity
project native hard constraints into RegisteredGrammarV1 / ConstraintAtomV1
run check_feasibility_v1 under the n+1 oracle-call ceiling
return inclusion-minimal conflict or continue only on Feasible
construct legal action grammar with intrinsic abstain
construct native success/terminal/evidence predicate representation
bind resource, risk, evidence and rollback semantics into the admitted/native digest scope
stable-sort every set and compute hard-constraint/objective semantic digests
emit deny-all admission receipt and compile/conflict outcome
```

Compilation is a pure function of the authenticated source envelope, selected admission profile and registered schema revisions. Retry with identical semantic inputs yields identical objective semantics. Reuse of a durable request/revision identity with different semantics is handled by the owning durable caller as conflict; the stateless compiler does not invent persistence.

## 5. State machine and persistence

### 5.1 Native output versus canonical product contract

The current Rust source candidate emits native `ObjectiveFunction`, `ObjectiveCompileReceipt` and `ObjectiveConflictReceipt` types. Admission preserves represented source meaning through profile mapping and digest binding, but the native objective intentionally flattens several canonical categories into `constraints` and `success_predicates`:

- terminal conditions and evidence requirements are represented as typed native success predicates with terminality/evidence bindings;
- resource and risk policy are represented as generated hard constraints;
- legal actions are represented directly; forbidden actions participate in compilation/conflict handling rather than being retained as a separate canonical output field.

That native representation is **not yet the canonical `ObjectiveFunctionV1` wire/output adapter** declared by the control-plane contract. Materializing the canonical wire shape, including explicit immutable-core/adaptive-surface fields and `ObjectiveCompileReceiptV1`, remains a product-integration gap. Digest binding is not a substitute for that adapter, and documentation/readiness must not claim otherwise.

### 5.2 Publication state machine

The compiler owns no domain-fact store. The owning product caller must atomically persist/publish the canonical `ObjectiveFunctionV1`, `RunStartSnapshotV1` and admission/compile receipts only after source, intent, profile, constraint and objective digests agree.

```text
received
-> decoded
-> structurally_validated
-> authenticated
-> profile_bound
-> normalized
-> compile(feasibility_resolved -> frozen)
-> compiled | explicit_abstain | conflict | rejected | unavailable
-> canonicalized and published atomically by owning caller
```

The current read-only intelligence vertical is an integration harness, not proof of that durable product writer. Its typed outcome API preserves `ExplicitAbstain` as a non-error result; the older receipt-only wrapper remains compatibility behavior. A crash before caller publication leaves no selected objective. A crash after durable publication must be reconciled by an identity that includes request, principal scope, source digest, schema digest and selected profile digest. A changed success predicate, hard constraint, legal effect, evidence requirement, resource/risk rule, principal scope or rollback class creates a new objective revision and run snapshot.

## 6. Error taxonomy and fallback

The canonical definitions are in `docs/contracts/OBJECTIVE_ERRORS.json`:

| Code | Stable class | Disposition |
|---|---|---|
| `OBJ-E001` | invalid bounded structure, numeric representation or arithmetic | rejected |
| `OBJ-E002` | unknown, unsupported or unrepresentable semantics | rejected |
| `OBJ-E003` | principal, trust or authenticated scope mismatch | authority rejected |
| `OBJ-E004` | source/schema/profile/normalization/intent integrity mismatch | integrity rejected |
| `OBJ-E005` | unit, direction or semantic-profile mismatch | rejected |
| `OBJ-E006` | intrinsic abstain unavailable or confirmation-gated | rejected |
| `OBJ-E007` | time-state, deadline or feasibility availability | unavailable, variant-specific retry |
| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |
| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |

`OBJ-E007` is a stable code family, not a blanket retry instruction. `ObjectiveError::FeasibilityBudgetExhausted` and `ObjectiveAdmissionError::SourceFromFuture` are retryable for the same semantic input after transient state changes. Locale rejection, stale source, missing/before-observation/expired deadlines require new input or configuration and must not be blindly replayed. Rust callers use the variant-level `retryable()` policy.

`ObjectiveConflictReceipt` and `CompileDisposition::ExplicitAbstain` are typed non-error outcomes. External adapters may use versioned canonical names, but they must not turn safe abstention into a system-failure/retry signal.

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

Pilot ceilings are `<=246` source constraints plus exactly ten generated resource/risk constraints for `<=256` native hard constraints, `<=128` aggregate success/terminal/evidence predicates, source action arrays `<=128`, `<=127` caller legal actions when abstain is implicit, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls. Exceeding a bound rejects or returns unavailable; input is never truncated after semantic analysis.

The admission profile's current 256 KiB guard uses `profile_encoded_size()`, a conservative parallel estimator rather than byte-for-byte canonical serialized length. If the profile byte ceiling is promoted to a protocol-hard canonical encoding boundary, actual canonical encoded bytes must replace that estimator.

## 9. Golden fixtures and tests

- `OBJ-GV-001`: reordered equivalent input produces identical objective semantics.
- `OBJ-GV-002`: a principal network prohibition dominates task text requesting network access.
- `OBJ-GV-003`: equivalent normalized Unicode produces identical canonical bytes under the selected profile.
- `OBJ-GV-004`: duplicate semantic identifiers reject before digest publication.
- `OBJ-GV-005`: changing a soft weight changes the objective digest but not the hard-constraint digest.
- `OBJ-GV-006`: untrusted evidence cannot create a privileged constraint or legal action.
- `OBJ-GV-007`: forbidding or confirmation-gating abstain returns `OBJ-E006`.
- `OBJ-GV-008`: 127 caller actions plus implicit abstain compile to exactly 128 actions; zero caller actions produce `ExplicitAbstain`.
- `OBJ-GV-009`: source, intent, schema, normalization and selected-profile digest mismatches all fail before native compile.
- `OBJ-GV-010`: unsupported or exhausted feasibility never weakens the original legal set.
- `OBJ-GV-011`: 247 source constraints reject structurally because ten generated slots are reserved.
- `OBJ-GV-012`: success predicates, terminal conditions and evidence requirements reject when their aggregate exceeds 128.
- `OBJ-GV-013`: `LocaleNotAllowed`, stale source and expired/missing deadline are non-retryable for the same semantic input.

Tests cover structural round trips, canonical ordering, unit conversion, conflict minimization, stale/future time, deadline handling, source authentication, resource overflow, action-slot reservation, aggregate-bound hostility, retry classification, redaction and property-based permutation invariance.

## 10. Implementation sequence

Implement and maintain, in order: strict JSON decoder; owner-local source type; admission-safe structural validator; authenticated admission context; frozen profile mapping; deterministic feasibility grammar; native feasibility projection; conflict minimizer; intrinsic legal-action grammar; native digests/receipts; canonical output adapter; durable caller adapter; faults; benchmarks; exact-source and merge-candidate qualification.

Coding entry requires a current `CanonicalSourceReceiptV1`, frozen contract/readiness/error-registry digests, a bounded work-package envelope, mandatory fixtures, deterministic fallback and zero authority delta. Source candidate completion still does not establish a production caller, canonical durable writer, activation, independent acceptance, promotion or release.

## 11. Coding-entry checklist

- exact canonical source receipt and immutable profile digest are current;
- every profile collection and admission aggregate is within its enforced bound;
- unsupported V1 source semantics fail closed without approximation;
- intrinsic `abstain`, hard-feasibility and conflict fixtures pass;
- outputs remain deny-all and the durable caller boundary is named;
- canonical output adapter/product writer gaps are not represented as source-complete;
- exact-head and synthetic-merge checks pass before source completion is claimed.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier remains normative in `READINESS.json`, `PROTOCOLS.json`, `GAPS.json` or `OBJECTIVE_ERRORS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `ObjectiveSourceEnvelopeV1`
- `ObjectiveConstraintSetV1`
- `ObjectiveConflictReceiptV1`
- `ObjectiveCompileReceiptV1`

Closed documentation gaps:

- `RDY-GAP-OBJ-001`
- `RDY-GAP-OBJ-002`
- `RDY-GAP-OBJ-003`
- `RDY-GAP-OBJ-004`
- `RDY-GAP-OBJ-005`
- `RDY-GAP-OBJ-006`

Bound work packages:

- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `INT-2-AGENTD-CODEX-COMPOSITION`
- `INTELLIGENCE-A0-Q0.63`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`
- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B2-TOOL-NET-FS`
- `P0.7B-B3-BOUNDARIES`
- `P0.7B-B4-CALLSITE-PROOF`
- `P0.8A-AST-RATCHET`
