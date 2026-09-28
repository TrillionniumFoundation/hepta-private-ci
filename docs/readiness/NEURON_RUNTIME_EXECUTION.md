# Neuron runtime execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Bound modules:** `neuron.runtime`, `intuition.policy`, `learning.ledger`, `learning.eval`, `learning.artifacts`
**Source target:** `codex-rs/hepta-neuron`

## 1. Scope and authority boundary

`neuron.runtime` is a bounded temporal signal engine. It does not represent a biological identity, execute tools, call providers, issue capabilities or replace the selected model or topology during a run. The selected encoder, head, inhibition graph, threshold profile and checkpoint generation are immutable inputs.

The runtime consumes `NeuronRuntimeConfigV1` and `NeuronTickInputV1`, emits `NeuronTickReceiptV1` plus canonical checkpoint and signal receipts, and may accumulate only next-snapshot plasticity sufficient statistics. Model output is advisory and cannot override the objective, authority kernel or reflex veto.

### DecisionCell host integration

The DecisionCell target extends the existing runtime with logical slots defined by
`../learning/NEURAL_BIOMIMICRY_SPEC.md`; this is not a completed durable integration.
Laya is a source-reviewed comparison baseline, not a selected backend or required
public protocol. The host supplies one exact effective base/organ/cell/head bundle
through existing inference admission; the cell does not call providers
or install a model itself. Shared workers serve many logical cells; checkpoint
ownership stays with the existing neuron owner and principal/subject scope.
Prediction, action strategy and state-successor outputs remain typed and separate.
A model's raw probability is not automatically the behavior propensity.

### Backend-neutral invocation contract target

Before inference, bind principal/purpose, subject/organ/cell, activation/operation
identity, objective/NDU/body revisions, causal source frontier, state predecessor,
complete legal-action and admitted-target sets (including canonical order), exact
backend/encoder/tokenizer/normalizer/parameter/calibration bundle, budget and deadline.
Backend replacement preserves these semantics; it cannot reinterpret a V1 record.
Outputs distinguish prediction, policy distribution, typed action/target/bounded
arguments, expected postcondition, value/cost, uncertainty/OOD, disposition and
bounded state successor. Stop, abstain, request-evidence and slow-path are explicit.
An expected postcondition is a prediction, never an observed terminal result.

Host validation owns complete-set admission, masking, exploration and the recorded
behavior propensity. Missing candidates, stale target generations, unknown output
fields or incompatible bundles reject before choice publication. The backend cannot
emit authority or dispatch effects. Action serialization belongs to its versioned
deterministic codec and consumer; this contract does not register ComputerActionIR.

## 2. Runtime state layout

One shard owns state for a bounded set of subject IDs. The DecisionCell target partitions state into scoped logical cell slots beneath that owner; it does not add independent global writers or reinterpret the existing V1 key. For the current subject profile, the canonical state is:

```text
generation and logical sequence
encoder/head/runtime tuple digests
bounded temporal state h[d_h] in signed Q24
previous sparse activation a[d_z] or sparse index/value form
adaptive thresholds theta[d_z or groups]
activation moving averages
bounded eligibility summary or exact trace digest
OOD/calibration state
checkpoint predecessor and expiry
```

Pilot bounds are `d_h<=256`, `d_z<=512`, top-k ratio `1%..20%`, modulator dimension `<=8`, state range `[-8,8]`, eligibility norm `<=4` and checkpoint bytes `<=1 MiB`. Raw prompts, credentials, unrestricted media and authority tokens are forbidden state.

## 3. Tick ordering and fixed-point semantics

Every tick executes exactly this order:

```text
validate config, generation, sequence, clock and feature dimensions
verify input/objective/NDU/body digests
update recurrent temporal state with checked wide intermediates
compute pre-competition activation
subtract registered lateral inhibition and thresholds
apply deterministic top-k-positive selection
update activation moving average and bounded homeostatic threshold
update eligibility from registered local pre/post rule
compute prediction error, confidence, OOD and abstention
canonicalize receipt and checkpoint
commit checkpoint and append signal receipt atomically
```

Signed Q24 conversion uses round-to-nearest, ties-to-even. Overflow is rejection; saturation occurs only at named projections and increments a counter. Equal activation is broken by canonical unit ID. Competition is first per registered population, then global. No unbounded convergence loop is allowed.

## 4. Concurrency, clock and checkpoint model

A subject has exactly one checkpoint writer. Routing may shard subjects, but two workers cannot advance the same predecessor revision. The compare-and-swap key is `(subject_id, generation, logical_sequence, checkpoint_digest)`. A duplicate tick with identical semantics returns the committed receipt; a reused tick ID with different semantics is conflict.

`monotonicTimeMicros` must increase within a process generation. A bounded reordering window may buffer observations only when declared; otherwise out-of-order input is rejected. Wall-clock time is evidence metadata, not update order. Generation rollover drains old writers before selecting a new config.

The checkpoint and receipt share one transaction or an outbox-backed atomic boundary. Crash before commit preserves the predecessor. Crash after commit but before acknowledgement is reconciled by tick ID and digest. Partial state mixing is forbidden.

### Cell execution sequence and coherent bundles

A future cell adapter uses the existing owner transaction pattern: validate scoped
cell/organ identity and public port; freeze objective, complete candidate set and
compatible parameter bundle; reserve budget before queue entry; perform bounded
inference; validate exact model/input identity and current source/grant constraints;
compute the state successor and policy; CAS checkpoint and receipt; send only an
advisory result to the existing action owner. Expired queued work must not mutate
state. Cancellation and acknowledgement loss reconcile by operation identity.

The cell slot extends owner-local addressing; it is not silently appended to a V1
wire record. Register incompatible serialized versions with consumers first.
Adapter/base replacement must invalidate or migrate feature caches, normalizers,
calibration and recurrent state. Check current revocation even for a cached bundle.
A compatible bundle is published at a future snapshot; unrelated organs need not
restart. Never mutate selected tensors through a training optimizer or clear old
writer fences merely to reuse a logical name.

### V2 durable DecisionCell migration target and failure matrix

Current source separates V1 `NeuronRuntime`/`SparseJournal` persistence from the
pure `PopulationSparse*V2` mechanism. The journal's `HPTNSJ02` successor-segment
header is not a DecisionCell V2 schema or migration. No migration completion is
inferred from a V2 type, replay fixture or existing package source-complete status.
The following states are design labels, not newly registered wire enum values.

| State | Required evidence before the next transition |
|---|---|
| V1 retained | Inventory actual readers/writers and retained anchors; preserve exact historical V1 decoding and digests. |
| Prepared | Register V2 config/input/checkpoint/result/receipt codecs, hash domains, bounds and consumer dispatch; freeze mapping, compatibility/reset policy and rollback predecessor. |
| Fenced | Drain or reconcile admitted work; record final V1 checkpoint and independently retained acknowledged frontier; fence every old writer. |
| Transformed | Write a separate V2 candidate with scoped cell key, source anchor, effective bundle, state mapping and migration digest; verify reopen and bounded parity without editing V1 history. |
| Published | Atomically publish the owner selection pointer only after candidate data and its independent witness are durable; allow one writer generation. |
| Observed | Reopen through actual readers, exercise duplicate/lost-ack/fault cases and preserve committed choices; record exact host/source evidence. |

V2 durable results must retain commitments to the exact admitted input, legal set,
order and bundle, post-mask policy/assignment evidence, chosen outcome and state successor
so recovery reads the committed choice without rerunning a model. Scope includes
principal/purpose/subject/organ/cell; operation identity is independent of retry count.
State may reset only through an explicit admitted reset transition with no unresolved
dependent choice/effect; it may not silently drop acknowledged history. Compatibility
must cover encoder, shapes, normalizer, calibration, caches and deletion lineage.

| Failure or interruption | Required disposition |
|---|---|
| Unknown version, missing consumer or incompatible transform | Keep current selection; reject candidate without coercing it into V1. |
| Crash before candidate/witness durability | Recover the fenced predecessor or retry the same migration identity; do not publish. |
| Crash during publication or lost acknowledgement | Read owner pointer and retained witness; reconcile the exact migration/result, never select by newest filename. |
| Two writers or same operation with changed semantics | Reject stale fence or semantic conflict; exactly one predecessor may advance. |
| Truncated acknowledged history, witness mismatch or uncertain sync | Quarantine/poison the affected handle and withhold publication; partial-tail repair cannot fabricate acknowledged success. |
| Expiry, cancellation or revocation before choice commit | Emit the declared rejection/fallback without advancing the cell; recheck current source rights on retry. |
| Cancellation or downstream acknowledgement loss after choice commit | Return/reconcile the retained choice; the action owner resolves any indeterminate effect without resampling. |
| Rollback after V2 writes | Fence V2; retain its committed choices and outcomes; use a tested reverse transform or admitted new-generation reset, never resume V1 behind acknowledged progress. |

Fault injection is required at each data/witness/pointer write and synchronization
boundary, including restart, deletion and wrong-principal replay. Passing this future
suite demonstrates only the tested migration profile, not production activation.

### Neural Circuit call and result handoff

The circuit adapter passes a scoped activation/round, frozen definition/policy,
legal candidate set, causal inputs, exact budget and parameter bundle to the cell
owner through existing inference admission. Cell state commits under its own CAS;
the run owner records the exact returned receipt and selected branch before any
downstream effect. Cross-owner acknowledgment loss reconciles the same activation;
it is not an atomic transaction across owners or permission to update twice.
Committed historical choices are read back, not recomputed with a new Laya version.
Reusable cell implementations do not imply shared mutable run state. The full
execution contract is in `../modules/automation.taskflow/TECHNICAL.md`.

## 5. Failure detection and fallback

Failures include encoder/head/tokenizer mismatch, stale generation, sequence gap, clock regression, dimension drift, state explosion or collapse, all-active or dead-unit collapse, threshold saturation, eligibility overflow, untrusted modulator, OOD false acceptance and attempted current-artifact mutation.

Fallback order is valid temporal checkpoint, stateless selected head, deterministic calibrated rule, then slow-path/abstain. A corrupt checkpoint is quarantined and rebuilt from the last valid checkpoint plus ordered events when replay bounds permit. Rebuild may not consume deleted or revoked rows.

## 6. Security and privacy

Features are purpose- and principal-scoped. Runtime logs expose digests and bounded summaries, not source payloads. The modulator contains only registered low-dimensional outcome, prediction, resource and safety signals. Authority, credentials and secret material are rejected at admission.

Negative tests cover adversarial activation flooding, poisoned feature manifests, model identity drift, checkpoint replay across principals, hidden prompt text, oversized sparse indices and a candidate attempting to select its own weights.

## 7. Performance envelope

The sparse path is bounded by `O(d_h*k_f + |E_I| + k log k)` under registered fan-in and inhibition edges. Pilot signal latency is p95 `<=3 ms`, p99 `<=8 ms`, transient allocation `<=512 KiB`, active checkpoint `<=1 MiB` and checkpoint write amplification `<=4x`. No dense `d_h^2` path is allowed above `d_h=256` without a separate qualification profile.

Backpressure rejects ticks before mutation. A missed optional consolidation window is recorded degradation and does not create an unbounded catch-up queue.

### Laya and training capacity are separate measured profiles

Sparse-tick timing above excludes full Laya inference, adapter misses and training.
Measure those end to end through the real inference owner. Use bounded shared
workers, per-scope queue fairness and explicit foreground/training reservations.
Logical cell count and simultaneously active cells are separate variables. Shared
weights do not remove question-conditioned encoder computation. No-data, rejected
admission, expired deadline, incompatible artifact and unavailable backend produce
their declared no-update/fallback results, not silent full-model reloads or CPU
fallback that violates the current budget. Scaling experiment points and metrics
are owned by `../learning/EXPERIMENTS.json`, not copied runtime capacity claims.

### Meta-network capacity profile admission target

A future backend profile declares its input encoding/domain, target class, local
parameter freedoms, representation and action output schemas, state/horizon,
precision and error budget. A type-correct Laya result is not evidence of universal
approximation. Preserve high-information non-authorizing outputs where required;
handle message exhaustion through declared compression/reread/abstain semantics.
Report actual model computation separately from Cell depth and gradient reach.
Selected artifacts and fixed Q24 pilot bounds remain unchanged; richer profiles
require explicit versioned compatibility and measured admission, not a prose
exemption. Use MN-01..MN-08 in `../learning/REFERENCE_CONFORMANCE_SPEC.md` as future
reference cases, retaining all prior runtime/fault tests.

## 8. Lesion, ablation and golden fixtures

`BIO-GV-001` remains the fixed-point tie, inhibition, threshold and eligibility reference. Additional fixtures are:

- `NEU-GV-002`: tick replay after process restart produces the same receipt digest.
- `NEU-GV-003`: two writers race on one predecessor; exactly one commits and the other conflicts.
- `NEU-GV-004`: clock regression and generation mismatch reject before state update.
- `NEU-GV-005`: all-unit activation triggers collapse detection and stateless fallback.
- `NEU-GV-006`: deleted-row replay is excluded and cannot reproduce a revoked checkpoint.

Ablations remove inhibition, homeostasis, eligibility, replay, temporal state or the true modulator. Lesions remove registered units or edges. Evaluation measures utility, stability, calibration, OOD, forgetting and resources; functional-biomimicry claims remain withheld unless the full mechanism beats preregistered ablations on future windows.

## 9. Implementation sequence

Implement config and tick types, scalar fixed-point primitives, checkpoint CAS, deterministic temporal cell, inhibition/top-k, homeostasis, eligibility, calibration/OOD, replay recovery, resource benchmarks and ablation fixtures. Attach a real local model only after exact weights, tokenizer, preprocessor, quantization, license/SBOM, runtime and device manifests are qualified.

## 10. Coding-entry checklist

Coding may start when the three readiness protocols and canonical Neuron protocols are generated, the Q24 profile and tie order are frozen, checkpoint ownership is exclusive, fault injection points are enumerated, benchmark host/profile is named, local-model use has a deterministic fallback, and every package preserves zero current-run parameter or topology mutation.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `NeuronRuntimeConfigV1`
- `NeuronTickInputV1`
- `NeuronTickReceiptV1`

Closed documentation gaps:

- `RDY-GAP-NEU-001`
- `RDY-GAP-NEU-002`
- `RDY-GAP-NEU-003`
- `RDY-GAP-NEU-004`
- `RDY-GAP-NEU-005`
- `RDY-GAP-NEU-006`

Bound work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `BIO-1-ELIGIBILITY-HOMEOSTASIS`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `INT-1-CALIBRATED-INTUITION-POLICY`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `LRN-2-CAUSAL-EVALUATION`
- `NEU-1-LOCAL-MODEL-BAKEOFF`
- `NEU-2-TEMPORAL-SIGNAL-RUNTIME`
