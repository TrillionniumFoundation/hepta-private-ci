# Objective compiler execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Bound modules:** `objective.compiler`, `intelligence.control`, `kernel.authority`, `learning.ledger`  
**Source target:** `codex-rs/hepta-objective`  
**Canonical error registry:** `docs/contracts/OBJECTIVE_ERRORS.json`

## 1. Scope and authority boundary

`objective.compiler` converts one bounded, authenticated request into an immutable objective revision. It does not infer authority from prose, relax a hard constraint, rewrite an objective during a run, select an action or execute an effect. Output remains advisory until the existing authority owner independently authorizes a concrete operation.

The complete native admission path is:

```text
bounded JSON bytes
-> decode_source_envelope_json_v1
-> ObjectiveSourceEnvelopeV1::validate_structure
-> authenticate source and principal scope
-> bind exact ObjectiveAdmissionProfileV1 digest
-> normalize and map every represented semantic field
-> check_feasibility_v1
-> compile
-> ObjectiveAdmissionReceiptV1
-> ObjectiveCompileReceiptV1 | ObjectiveConflictReceiptV1
```

No stage may silently drop a represented constraint, action, success predicate, resource ceiling, risk rule, evidence requirement or provenance field. A decoder or structural validator is not semantic admission. A profile label is not authentication. The admitted source digest binds the supplied source digest, authenticated source class and selected profile.

## 2. Input grammar and canonical IR

The accepted structured grammar is bounded and contains:

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

Free text is evidence for intent extraction, never the final authority representation. Every predicate has an identifier, unit, comparator, bound, evidence source and terminality. Arrays are stable-sorted by semantic identifier. Unicode uses the selected normalization profile; timestamps are UTC; durations are integer microseconds; numeric values use registered fixed-point profiles. Duplicate semantic keys are rejected.

The canonical IR contains no raw credentials, unrestricted external text, hidden model state or executable code. Every payload and collection has both count and encoded-byte bounds. Admission profiles are bounded to 256 constraint mappings, 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and 256 KiB of encoded profile semantics; risk and rollback levels must be monotone.

## 3. Constraint precedence and conflict resolution

Precedence is lexicographic and non-compensable:

```text
P0 constitutional authority, truth, privacy, deletion and writer ownership
P1 explicit principal scope and forbidden effects
P2 environment and adapter safety constraints
P3 task success predicates and terminal conditions
P4 soft utility preferences and resource allocation
```

A lower class cannot offset a higher-class violation. Soft atoms never participate in hard feasibility. Scalar and finite-enum atoms use deterministic intersection. Registered positive action implications use bounded graph closure. Unsupported operators, arbitrary code, unrestricted quantifiers, nonlinear arithmetic and unbounded recursion reject before solving.

For infeasible hard constraints, deterministic deletion filtering returns an **inclusion-minimal** unsatisfied set in canonical order. It does not claim minimum cardinality. A hard conflict is represented by `ObjectiveConflictReceiptV1`, not by reusing an unrelated error code. Oracle exhaustion preserves the original objective and emits unavailable; it never publishes a partial core that permits dropping a hard constraint.

## 4. Deterministic compilation algorithm

### 4.1 Legal-action grammar and intrinsic abstain

`abstain` is a compiler-intrinsic, confirmation-free safety action. It is present in every successfully compiled legal set. A caller may include it explicitly, but may not forbid it or require confirmation.

The compiled action ceiling is `128`, including the intrinsic abstain slot:

```text
caller does not include abstain: caller action ceiling = 127
caller explicitly includes abstain: caller action ceiling = 128
compiled legal action ceiling: 128
```

A requested action that is also forbidden produces an explicit conflict receipt. Removing all requested actions still leaves intrinsic abstain and yields `CompileDisposition::ExplicitAbstain`. An attempt to forbid or confirmation-gate abstain is `OBJ-E006` and publishes no objective.

### 4.2 Deterministic compilation steps

```text
validate raw byte and structural bounds
verify authenticated source context and principal scope
verify schema, normalization, source, intent and profile digests
validate locale, observation time, deadline and source freshness
map only registered constraints, predicates, actions, resources and risk rules
normalize identifiers, units, times and fixed-point values
classify constraints into P0..P4
reject duplicate or contradictory semantic identity
compute hard feasibility or inclusion-minimal conflict
construct legal action grammar with intrinsic abstain
construct success and terminal predicates
bind resource, risk, evidence and rollback profiles
stable-sort every set and encode canonical semantics
compute hard-constraint and objective semantic digests
emit deny-all admission receipt and compile/conflict outcome
```

Compilation is a pure function of the authenticated source envelope, selected admission profile and registered schema revisions. Retry with identical inputs yields identical semantic bytes. Reuse of a durable request/revision identity with different semantics is handled by the owning durable caller as conflict; the stateless compiler does not invent persistence.

## 5. State machine and persistence

The compiler owns no domain-fact store. The owning caller persists the immutable `ObjectiveFunctionV1`, `RunStartSnapshotV1` and admission/compile receipts. Publication occurs only after source, intent, profile, constraint and objective digests agree.

```text
received
-> decoded
-> structurally_validated
-> authenticated
-> profile_bound
-> normalized
-> feasibility_resolved
-> compiled | conflict | rejected | unavailable
-> published by owning caller
```

A crash before caller publication leaves no selected objective. A crash after durable publication is reconciled by an identity that includes request, principal scope, source digest, schema digest and selected profile digest. A changed success predicate, hard constraint, legal effect, evidence requirement, resource/risk rule, principal scope or rollback class creates a new objective revision and a new run snapshot.

## 6. Error taxonomy and fallback

The only canonical definitions are in `docs/contracts/OBJECTIVE_ERRORS.json`:

| Code | Stable class | Disposition |
|---|---|---|
| `OBJ-E001` | invalid bounded structure, numeric representation or arithmetic | rejected |
| `OBJ-E002` | unknown, unsupported or unrepresentable semantics | rejected |
| `OBJ-E003` | principal, trust or authenticated scope mismatch | authority rejected |
| `OBJ-E004` | source/schema/profile/normalization/intent integrity mismatch | integrity rejected |
| `OBJ-E005` | unit, direction or semantic-profile mismatch | rejected |
| `OBJ-E006` | intrinsic abstain unavailable or confirmation-gated | rejected |
| `OBJ-E007` | freshness, deadline or feasibility budget unavailable | unavailable |
| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |
| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |

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

Pilot ceilings are `<=256` constraints, `<=128` success predicates, `<=127` caller actions when abstain is implicit, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls. CPU and wall-clock budgets are frozen before evaluation. Exceeding a bound rejects or returns unavailable; input is never truncated after semantic analysis.

The p95/p99 targets apply only to a named path, fixture and host. A normal-path latency measurement cannot be reused as a conflict-extraction measurement. No network or synchronous central RPC is permitted on the deterministic compiler path.

## 9. Golden fixtures and tests

- `OBJ-GV-001`: reordered equivalent input produces identical objective semantics.
- `OBJ-GV-002`: a principal network prohibition dominates task text requesting network access.
- `OBJ-GV-003`: equivalent normalized Unicode produces identical canonical bytes under the selected profile.
- `OBJ-GV-004`: duplicate semantic identifiers reject before digest publication.
- `OBJ-GV-005`: changing a soft weight changes the objective digest but not the hard-constraint digest.
- `OBJ-GV-006`: untrusted evidence cannot create a privileged constraint or legal action.
- `OBJ-GV-007`: forbidding or confirmation-gating abstain returns `OBJ-E006`.
- `OBJ-GV-008`: 127 caller actions plus implicit abstain compile to exactly 128 actions; 128 caller actions without abstain reject.
- `OBJ-GV-009`: source, intent, schema, normalization and selected-profile digest mismatches all fail before native compile.
- `OBJ-GV-010`: unsupported or exhausted feasibility never weakens the original legal set.

Tests cover structural round trips, canonical ordering, unit conversion, conflict minimization, idempotent retry, stale/future time, deadline handling, source authentication, resource overflow, action-slot reservation, redaction and property-based permutation invariance.

## 10. Implementation sequence

Implement and maintain, in order: strict JSON decoder; owner-local source type; structural validator; authenticated admission context; frozen profile mapping; deterministic feasibility grammar; conflict minimizer; intrinsic legal-action grammar; canonical digests; deny-all receipts; durable caller adapter; faults; benchmarks; exact-source and merge-candidate qualification.

Coding entry requires a current `CanonicalSourceReceiptV1`, frozen contract/readiness/error-registry digests, a bounded work-package envelope, mandatory fixtures, deterministic fallback and zero authority delta. Source completion still does not establish a production caller, activation, independent acceptance, promotion or release.

## 11. Coding-entry checklist

- exact canonical source receipt and immutable profile digest are current;
- every profile collection and encoded profile is within its enforced bound;
- all represented source semantics map without truncation or guessing;
- intrinsic `abstain`, hard-feasibility and conflict fixtures pass;
- outputs remain deny-all and the durable caller boundary is named;
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
