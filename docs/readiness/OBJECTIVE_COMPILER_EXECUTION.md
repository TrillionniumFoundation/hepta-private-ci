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
-> canonical_objective_intent_digest_v1
-> admit_objective_v1
   -> authenticate source and principal scope
   -> bind exact ObjectiveAdmissionProfileV1 digest
   -> normalize and map every losslessly representable semantic field
   -> produce opaque AdmittedObjectiveV1
-> compile_admitted_objective_v1
   -> compiler::compile (owner-internal legacy scalar IR)
      -> scalar_adapter::scalar_conflict
         -> check_feasibility_v1
-> ObjectiveAdmissionReceiptV1
-> ObjectiveCompileReceiptV1 | ObjectiveConflictReceiptV1
-> for compiled/abstain: encode_authenticated_objective_function_v1(...)
   -> canonical ObjectiveFunctionV1 JSON bytes
   -> ObjectiveFunctionV1 protocol-wire digest
-> durable RunStart v2 record
   -> native semantic bytes + native semantic digest
   -> canonical ObjectiveFunctionV1 bytes + protocol-wire digest
-> for compiled compatibility-path admission: ObjectiveRunExecutionBinding
   -> exact daemon-owned request/objective/body/artifact/authority/generation/fence/deadline identity
   -> trusted context attachment
   -> current final-use authorization and durable physical dispatch
   -> exactly one App Server turn and observed terminal publication
```

No stage may silently drop a represented constraint, action, success predicate, resource ceiling, risk rule, evidence requirement or provenance field. A represented Source-V1 operator without a lossless native mapping is rejected deterministically; see `docs/modules/objective.compiler/SEMANTIC_SUPPORT.md`. A decoder or structural validator is not semantic admission. A profile label is not authentication. The admitted source digest binds the supplied source digest, authenticated source class and selected profile.

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

The canonical IR contains no raw credentials, unrestricted external text, hidden model state or executable code. The owner-native IR digest and registered `ObjectiveFunctionV1` wire digest are distinct identities: native execution never treats the wire digest as the compiler semantic digest, and durable publication never drops either binding. Bounds are enforced against the **final native aggregate**, not just each source array: Source V1 admits at most **246 source constraints** because admission deterministically adds six resource constraints and four risk/rollback/compensation/abstention constraints before the native 256-constraint ceiling. `successPredicates + terminalConditions + evidenceRequirements` share one aggregate ceiling of **128**. Source legal-action arrays may contain 128 entries only when the intrinsic `abstain` slot is explicit; when it is omitted the compiler reserves one slot and accepts at most 127 caller legal actions. Admission profiles remain bounded to 256 constraint mappings, 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and a 256 KiB encoded-profile guard; risk and rollback levels must be monotone.

## 3. Constraint precedence and conflict resolution

Precedence is lexicographic and non-compensable:

```text
P0 constitutional authority, truth, privacy, deletion and writer ownership
P1 explicit principal scope and forbidden effects
P2 environment and adapter safety constraints
P3 task success predicates and terminal conditions
P4 soft utility preferences and resource allocation
```

A lower class cannot offset a higher-class violation. Soft atoms never participate in hard feasibility. The direct typed `check_feasibility_v1` API supports deterministic scalar and finite-enum intersection, bounded positive-action implication closure and immutable-identity equality. The Source V1 admission path is narrower: its scalar `boundQ32` payload losslessly maps only `eq/lte/gte`; `ne/lt/gt/in/not_in` are deterministic `OBJ-E002` rejection until a versioned source payload can carry the missing semantics. Generic feasibility support therefore must not be reported as Source V1 end-to-end support.

For infeasible hard constraints, deterministic deletion filtering returns an **inclusion-minimal** unsatisfied set in canonical order. It does not claim minimum cardinality. A hard conflict is represented by `ObjectiveConflictReceiptV1`, not by reusing an unrelated error code. Oracle exhaustion preserves the original objective and emits unavailable; it never publishes a partial core that permits dropping a hard constraint.

## 4. Deterministic compilation algorithm

### 4.1 Legal-action grammar and intrinsic abstain

`abstain` is a compiler-intrinsic, confirmation-free safety action. It is present in every successfully compiled legal set. A caller may include it explicitly, may omit all other legal actions, but may not forbid it or require confirmation. An empty caller legal-action set is structurally valid and compiles to `CompileDisposition::ExplicitAbstain`.

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

Compilation semantics are a pure function of the authenticated source envelope, selected admission profile and registered schema revisions. The owner-internal compiler path uses an effectively unbounded wall-time budget so host scheduling cannot change a valid semantic result into `Exhausted`. The explicit `check_feasibility_v1` availability API is different: its caller-supplied wall-clock budget and observational `elapsed` field are host-sensitive and are not semantic identity. Retry with identical admitted inputs yields identical semantic objective bytes and digests; time-bounded availability receipts need not be byte-identical. Reuse of a durable request/revision identity with different semantics is handled by the owning durable caller as conflict; the stateless compiler does not invent persistence.

## 5. State machine and persistence

The compiler owns no domain-fact store. `ObjectiveAdmissionContextV1` is an owner-local trust carrier for the pure library boundary, not a standalone cryptographic authentication proof; a test or arbitrary downstream crate constructing that value does not establish a product caller. The canonical product-source caller is Agentd's signed objective ingress: current AuthBus trust authenticates the exact signed body before Agentd decodes the embedded source and constructs the owner-local admission context. `compile_and_publish_objective_run_v1` uses `encode_authenticated_objective_function_v1`, which recomputes admission and native compilation from that exact source/profile/context and rejects any source, profile, receipt or native-result drift before projection. It then appends the signed-ingress authentication fields, admission binding, owner-native objective semantic bytes/digest, canonical `ObjectiveFunctionV1` bytes/protocol digest and `RunStartSnapshotV1` to the destination-owned segmented `DurableRunStartStore` before a non-abstain run reaches `AgentRunCoordinator`. Every append and compacted-prefix transition advances an independent monotonic checkpoint outside the Agent-home rollback domain. Exact replay is idempotent; same-run native or protocol semantic drift and predecessor drift conflict; restart recovery revalidates checkpoint history and retained authentication against current trust. Legacy v1 records are readable for recovery/migration inspection but fail closed at Agentd final use because they lack canonical protocol identity. For a compiled fallback run, the `ObjectiveStart` receipt carries an optional `ObjectiveRunExecutionBinding` copied from the exact durable record. The binding grants no effect authority; it only lets a trusted execution owner construct the exact `AgentContextAttachment`. `AppServerModelDriver::run_intelligence` then requires that same run to be `ContextAttached`, claims current final-use authority, commits durable dispatch before the physical send, marks the Agentd run dispatched, performs one App Server turn and writes the observed terminal state back to the same run. An exact durable retry returns the stored observation before any new authority claim or provider send. This is source composition, not deployment activation. Publication occurs only after source, intent, profile, constraint, native-objective and protocol-wire digests agree.

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
-> compiled execution identity returned without effect authority
-> context_attached
-> final_use_authorized
-> dispatched
-> terminal_observed | indeterminate
```

A crash before caller publication leaves no selected objective. A partial unacknowledged active-segment tail is truncated only to the last complete validated frame; acknowledged missing history, a removed sealed segment, a missing external checkpoint for existing local history, or a checkpoint ahead of local history is never repaired as empty success. Rotation preserves one global predecessor chain. Compaction replaces only a complete expired sealed prefix with a replay index that retains run identity, authentication frontier, record and chain digests; the pending summary is written first, checkpointed by CAS second, committed third, and old segments removed last. A crash or acknowledgement loss at any of those cuts is reconciled without resurrecting an older frontier. Reusing the run identity with changed native or canonical-protocol semantics conflicts. At runtime final use, current trust, generation, fence, exact admitted deadline and canonical protocol identity are revalidated. `ObjectiveFunctionV1` floors the exact microsecond deadline to milliseconds, and Agentd uses the same conservative floor so the wire cannot extend authority. A changed success predicate, hard constraint, legal effect, evidence requirement, resource/risk rule, principal scope or rollback class creates a new objective revision and a new run snapshot.

### Process lease versus runtime dispatch generation

The worker configuration names the Agentd process spawn lease; the persisted
RunStart and AgentRunReceipt carry the run's runtime generation. These identities
must not be compared as if they were the same counter. The worker captures the
complete `ContextAttached` receipt, rechecks that unchanged owner receipt before
preparation is committed, and accepts a new `Dispatched` acknowledgement only
when its run, successor revision, runtime generation, fence, authority epoch,
deadline, context and compilation digest all match that handoff. An idempotent
acknowledgement is recovery evidence, never a second physical-send permit.
The signed product-process fixture exercises distinct process/runtime counters;
independent receipt-mutation regressions reject generation, fence, authority,
deadline, revision, context, terminal and replay substitutions.

### Store writer continuity and bounded recovery decoding

`DurableRunStartStore` holds a stable `.writer.lock` lease for its entire
lifetime, including recovery, active-segment rotation, checkpoint publication
and prefix compaction. The lease is acquired before inspecting or mutating
history and released only after the segment and checkpoint handles close.
The lock file is never renamed or removed during normal operation. A competing
instance or process must receive `Busy` even at the cut where the active segment
has been closed and its successor does not yet exist.

The compacted replay-index decoder checks the encoded entry count against both
the registered count ceiling and the remaining frame bytes before reserving
memory. Encoding preflights the count and complete encoded length against the
same ceiling before constructing a summary. Reaching the replay-index ceiling
remains an explicit capacity limit, not permission to discard deduplication or
authentication history. A selected deployment still needs an acknowledged
archive/retirement policy before exceeding that limit.

The regression suite includes cross-process writer takeover at rotation,
normal handoff after owner drop, malformed-count recovery with a valid checksum,
49 independent source-field mutations with recomputed intent digests, genuine
multi-entry source permutations, and inclusive action/soft-weight boundaries.
These source tests do not establish independent deployment acceptance.

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
| `OBJ-E007` | time-state, deadline or feasibility availability | unavailable; variant-specific retry |
| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |
| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |

`OBJ-E007` is a stable error-code family, **not** a blanket retry instruction. `ObjectiveError::FeasibilityBudgetExhausted` and `ObjectiveAdmissionError::SourceFromFuture` may succeed after transient state changes; `LocaleNotAllowed`, stale source, missing/before-observation/expired deadline require changed input or configuration. Rust callers use the variant-level `retryable()` policy. `ObjectiveConflictReceiptV1` and `CompileDisposition::ExplicitAbstain` are typed non-error outcomes. Rust variants, documentation and external adapters must be checked against the canonical registry; no component may assign a local alternate meaning to a code.

Fallback may reuse a previously selected immutable objective only when the owning caller proves equal request identity, principal scope, compatibility and current revocation frontier. Otherwise it asks for clarification or abstains. It never substitutes an easier goal.

## 7. Security and adversarial inputs

Untrusted pages, emails, files, tool output and model prose remain evidence. They cannot create P0-P2 constraints, legalize an effect, change principal scope or weaken evidence requirements. Negative fixtures include prompt injection, hidden HTML instructions, homograph identifiers, duplicate JSON keys, oversized arrays, NaN/infinity equivalents, conflicting time units, path traversal, embedded secrets, forged trust labels and stale/future observations.

The compiler records safe identifiers and digests rather than unrestricted source text. It has no model, tool, network, filesystem, secret, Matrix, fleet or external-effect authority. Every admission receipt embeds `AuthorityPosture::DENY_ALL`.

## 8. Performance envelope

The following paths are measured separately:

| Path | Bound/complexity |
|---|---|
| generic raw JSON guard and structural decode | `<=256 KiB`, bounded field and collection counts |
| normal Agentd signed product ingress | source JSON `<=32 KiB`; canonical signed body `<=48 KiB` |
| normalization and canonical sorting | `O(n log n)` |
| one ordinary feasibility oracle call | profile-specific `C(n)` |
| inclusion-minimal conflict extraction | at most `n+1` oracle calls and `O(n C(n))` |
| legal-action construction | `O(a log a)` with compiled `a<=128` |

Pilot ceilings are `<=246` source constraints plus exactly ten generated resource/risk constraints for `<=256` native hard constraints, `<=128` aggregate success/terminal/evidence predicates, source action arrays `<=128`, `<=127` caller legal actions when abstain is implicit, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls. Semantic compilation is call-budget bounded and deterministic; the direct feasibility API's wall-clock budget is an availability control and its measured `elapsed` field is operational evidence. Exceeding a semantic bound rejects or returns unavailable; input is never truncated after semantic analysis.

The repository-owned measurement harness is `scripts/hepta-objective-target-measure.py` with procedure `docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md`. It records exact commit/tree and separately measures authenticated admission+ordinary compile versus maximum conflict extraction. A GitHub runner is development evidence only; closing the target-host gate still requires the selected host profile. A normal-path latency measurement cannot be reused as conflict-extraction latency. No network or synchronous central RPC is permitted on the deterministic compiler path.

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
- `OBJ-GV-011`: 247 source constraints reject structurally because ten native slots are reserved for generated resource/risk constraints.
- `OBJ-GV-012`: success predicates, terminal conditions and evidence requirements reject when their aggregate exceeds 128.
- `OBJ-GV-013`: locale rejection, stale source and invalid/expired/missing deadlines are non-retryable for the same semantic input.

Tests cover structural round trips, authenticated source/profile/context/native-result rebinding, canonical ordering and semantic uniqueness, unit conversion, conflict minimization, idempotent durable replay, segment rotation and compaction, checkpoint acknowledgement loss and rollback detection, stale/future time, conservative microsecond deadline projection/final use, source authentication, product ingress capacities, resource overflow, aggregate-bound hostility, action-slot reservation, variant-specific retry policy, redaction, property-based permutation invariance, exact compiled execution binding, context attachment, current final-use authorization, one physical App Server send, terminal publication, exact retry without resend and restart non-resurrection.


### Replay lookup and measurement evidence boundaries

Authenticated `ObjectiveStart` retries resolve the destination-owned exact
publication index before fresh-source admission. The complete persisted AuthBus
identity, including the signed body digest, must match. Live retries return the
original run/conflict publication without recompiling against a later clock or
appending again. New operations still obey source freshness. The replay clock is
sampled after acquiring the writer lock; current authentication, deadline,
generation, fence and checkpoint checks are retained. Publication lookup is not
an effect permit, and runtime final-use authorization remains separate.


`DurableRunStartStore::index_entry` resolves exact authenticated run identity from
the existing BTreeMap index, including compacted entries, without allocating or
scanning the full authentication history for every retry. Unknown IDs remain
absent and indeterminate checkpoint state rejects lookup; compaction never turns
a mismatched request into an exact replay.

Compaction bounds active/retained payload segments, not lifetime metadata: the
replay summary retains historical identities and has a 1 GiB admission bound.
Capacity exhaustion remains explicit; unlimited retention is not claimed. The
external checkpoint must be outside the actual backup/rollback domain, not merely
in a different directory. A whole-host rollback of both copies is not protected by
filesystem path separation alone.

The process fixture uses the configured compiled-objective compatibility host,
a trusted context fixture and a controlled HTTP/SSE provider. Its physical-send
and terminal evidence must not be described as automatic seven-owner product
composition or live-provider deployment qualification.

## 10. Implementation sequence

Implement and maintain, in order: strict JSON decoder; owner-local source type; admission-safe structural validator; authenticated product ingress; frozen profile mapping; opaque admitted-objective boundary; deterministic feasibility grammar; conflict minimizer; intrinsic legal-action grammar; authenticated canonical projection; deny-all receipts; destination-owned segmented run-start store; independent monotonic checkpoint; rotation/compaction/recovery; daemon restart qualification; target-host measurement harness; exact-source and merge-candidate qualification.

Coding entry requires a current `CanonicalSourceReceiptV1`, frozen contract/readiness/error-registry digests, a bounded work-package envelope, mandatory fixtures, deterministic fallback and zero authority delta. Source completion still does not establish a production caller, activation, independent acceptance, promotion or release.

## 11. Coding-entry checklist

- exact canonical source receipt and immutable profile digest are current;
- every profile collection and source/native aggregate is within its enforced bound;
- all supported represented source semantics map without truncation or guessing and unsupported V1 operators fail closed;
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
