# Neuron V2: operation lifecycle, recovery and diagnostics

This is the current developer entry point for `NeuronRuntimeV2`. The original
`TECHNICAL.md` remains the Sparse Q24 mechanism reference. This document describes
implemented candidate semantics, not production activation or an executed pass.
The starting source is `c8c6e9d64de35b24210906ef72487011a1e0dafd`; qualification
must identify the actual subsequent source commit and fixed integration base.

## Owner and responsibilities

The product path is `AgentdNeuronOwnerV2` -> `DurableInferenceControlModelPort` ->
`DurableNeuronFeaturePortV1` -> its durable provider backend. The runtime owns the
HPTNGS02 result store and HPTNGI02 admission/discovery index. The independent
`AnchorWitnessStore` owns accepted checkpoint frontiers. A trait implementation
is a protocol obligation, not a cryptographic certificate or production test.
No status or diagnostic object grants execution, selection or release authority.

## Lifecycle

1. Verify the current admission guard, input digest, body generation and historical
   identity. For a new transition, verify predecessor, subject/objective scope,
   increasing sequence/time, calibration window, model input dimension and budgets.
   Perform these deterministic checks before creating a reservation.
2. Reserve space for the complete index lifecycle and generation-store witness
   acknowledgement. Sync `Reserved` before physical work.
3. Recheck admission. Sync `DispatchStarted` before calling the durable model port.
4. A returned, validated model output can become one atomic HPTNGS02 result:
   operation key, replay transition, full receipt, disposition and witness outbox.
5. Complete the index from that authoritative record, then reconcile the witness
   CAS and acknowledge its observation locally. Final admission is checked before
   exposing the result through the guarded execution path.

A failure before reservation is not recorded and cannot occupy the queue. A
verified model rejection, rejected output, invalid deterministic transition,
post-observation admission denial or oversized result becomes a durable `Failed`
tombstone while HPTNGS02 is healthy and proves no local result exists. That clears
the single pending slot without advancing the checkpoint sequence. The key cannot
be resurrected or reused with changed input; another key may use the same next
sequence. Failure histories consume the configured index record budget.

`Unavailable`, `Indeterminate`, poisoned storage, incomplete commit acknowledgement
and unknown provider outcomes are NOT negative results. They retain the operation
identity for recovery and never authorize a blind second execution.

## Status and error interpretation

Call `query_operation(tick_id, input_semantic_digest)`:

| Status | Meaning |
| --- | --- |
| `NotRecorded` | Healthy local stores contain no record for this exact operation. |
| `NotExecuted` | A new-format reservation exists without a dispatch fence. |
| `OutcomeUnknown` | Execution might have crossed the boundary; query the durable owner. |
| `Failed(reason)` | A durable negative Neuron transition; no successful state result. |
| `Committed { commit, witness_acknowledged }` | The exact local result is durable; the flag reports local acknowledgement of the independent witness. |

Errors are not statuses: authorization can fail even AFTER a local commit.
Read/poisoning/corruption errors must never be converted to `NotRecorded`.
`query_operation` repairs a locally discoverable commit but does not require a
reachable remote witness just to report that the local commit exists. It is an
administrative API, not an alternative authorization or consumer delivery path.
The compatibility `query_result` reports pending/failed operations as errors,
rather than collapsing them into `None`.

## Query-only recovery

`DurableNeuronModelPort::reconcile` and
`DurableNeuronInferenceControlPort::reconcile_feature` default to `Unknown`.
The concrete worker-host port queries its existing feature execution ledger.
`Dispatched` records may only query the backend; `Reserved` or genuinely absent
records may report `NotStarted` under the still-exclusive, healthy owner.
A missing/corrupt history file is not a no-dispatch proof.

Only that authoritative `NotStarted` result permits resuming the SAME operation,
with a fresh admission check. Otherwise retrying `tick_guarded` invokes query-only
reconciliation, not `execute`. A malformed backend receipt is indeterminate, not
a forged terminal rejection. Verified Failed/Cancelled receipts may reject.

## Compatibility and rollback

HPTNGS02 encoding and checkpoint/full-receipt payload equality are unchanged.
The large checkpoint/receipt clone is intentionally retained until a separately
versioned migration proves forward and backward recovery. Witness reconciliation
now borrows the outbox record and copies only key/anchors, avoiding two large
payload clones without changing persisted bytes.

HPTNGI02 adds `Reserved`, `DispatchStarted` and `Failed` event kinds. Legacy
`Prepared` records are readable but conservatively treated as possibly dispatched.
Old binaries will fail closed on new event kinds; do not downgrade after writing
them. Preserve the source binary and all generation/index/witness histories.
Never remove failed-operation tombstones or clear the directory to restore service.

The independent checkpoint witness does not authenticate every admission event.
A malicious rollback of BOTH local admission history and provider history at an
unchanged checkpoint is not solved by the current witness. Recovery/backup policy
must preserve those histories. Extending independently anchored admission history
is an outstanding security/retention requirement, not an already passed property.

## Filesystem boundary

Existing stores open using a non-following, non-blocking descriptor on Unix and
must be regular single-link files. Identity is rechecked against the bound inode
under the file owner; actual opened length is checked against replay limits.
A raced-in FIFO must not hang startup, and a raced-in symlink is not followed.
The store, index and V2 file witness share measured sync/identity handling.
Parent directories remain trusted, host-owned namespaces; these checks do not
claim protection from an equally privileged actor replacing every ancestor.
Platform-specific behavior needs its own executed qualification.

## Capacity and long-running service

`capacity_snapshot` reports retained operation counts, effective byte/replay
limits, reserved completion/acknowledgement bytes and optional witness capacity.
`near_limit()` gives an advisory 80% warning. Actual key/payload-dependent admission
is authoritative and can reject sooner. Surface watermarks before backpressure.
Historical result lookup and recovery must remain possible at capacity.

Unified V2 segment rollover/compaction and generation reload are NOT implemented
by this change. Do not infer them from the existing segmented witness or V1
manifest. Until a lossless, owner-fenced V2 segment manifest preserves failure
history, original results and witness lineage, the correct behavior at capacity
is explicit backpressure, not deletion or generation reset. This remains an open
long-running-service acceptance item.

## Measurements

`last_measurement()` is a process-local observation separate from every immutable
receipt. It covers complete guarded calls, including admission, reconciliation,
model execution/query, local persistence, witness and final authorization, for
both success and error returns. Each file reports actual sync calls/errors/time
and observed file size before/after. These are not physical block-device writes.
Unknown witness metrics are `None`, never invented zeros. Legacy receipt
`execution_micros` and logical byte estimates retain their old meanings.

The ignored `runtime_v2_diagnostic_measurements` test emits 64 executed samples
using the actual runtime/store/index/file witness and an explicitly deterministic
model fixture. Samples bind a source SHA and executable digest. The summarizer
rejects mismatched identity, duplicate/insufficient samples, missing witness data,
wrong sync counts and failed requests. It reports nearest-rank p50/p95/p99 request
latency, recovery, summed sync latency per request and retained-file growth.
Linux VmHWM is process high-water RSS, not per-request allocation; other platforms
may report it unmeasured. These diagnostics are not a production-model benchmark,
quality qualification, independent acceptance, target-host SLA or activation.

## Regression and exact-source qualification

The added tests cover preflight rejection without reservation; terminal failure
idempotence and conflict; reserved versus dispatched recovery; unresolved model
query-only behavior; poisoned storage; lost failure acknowledgement; receipt
identity preservation; capacity due to retained failures; file replacement,
symlink/hardlink/FIFO races; and explicit worker-host query-only reconciliation.

The actual V2 subprocess matrix exits after reservation, dispatch fence, model
observation, generation commit, index completion and witness acknowledgement.
Each case is recovered and retried in fresh processes against the file witness.
The deterministic provider fixture rejects duplicate physical execution. This
complements, rather than replaces, existing partial-write/sync corruption tests.

Qualification must compile the unchanged committed source and a deterministic
merge with a fixed main SHA on Linux and macOS. Run related Neuron, worker-host,
Agentd and intelligence suites, strict Clippy, committed-format checks, diagnostic
sampling and evidence-parser tests. Retain command logs, actual step outcomes,
source/base/candidate/tree identities and toolchain metadata. A writer/formatter
may prepare a source commit, but no rewritten clone or its historical parent may
be reported as passing that commit's read-only qualification.

No native result is asserted by this document. Only the corresponding completed
exact-source workflow evidence can establish which commands actually passed.

## Typed DecisionCell operation identity

`tick_decision_cell_guarded` binds the complete validated DecisionCell request,
including the action/target sets, observation frontier and deadline, together with
the canonical tick digest before durable admission. The key is domain separated
from ordinary Neuron ticks. `query_decision_cell_operation` derives the same key;
ordinary `query_input_operation` is not a typed-Cell lookup shortcut. Existing
non-Cell V1/V2 record bytes and tick keys are unchanged.

Changing candidates or a target generation under a used tick ID is a conflict,
including after a dispatched/unknown attempt. It cannot call a reconciler with
replacement context or reinterpret an old choice. Historical unregistered Cell
prototypes with tick-only keys are not silently replayed through the new path;
retain them for explicit reconciliation/migration rather than clearing identity.

A deterministically rejected or malformed typed receipt becomes a durable
`InvalidModelOutput` terminal failure. Unknown provider or I/O outcomes remain
unknown. Receipt construction never obtains permission to rerun a consumed model
invocation or dispatch a computer action.

## Backend qualification and immutable upstream snapshots

The [package-local DecisionCell panel](../../../codex-rs/hepta-neuron/qualification/README.md)
trains real organ/cell adapters and typed heads over frozen encoder features. It
keeps tuning, calibration and evaluation separate and labels its generated data as
synthetic. Its output is not a selected artifact or prospective efficacy evidence.

Every consumed model/tokenizer/custom-code file must match the pinned upstream
Git/LFS manifest before an online qualification run. A locally modified tokenizer
under the same revision directory is rejected. Diagnostic offline receipts do not
forge upstream verification; later audits remain separate records. Source identity
does not imply code review, licensing, independent calibration or product authority.
The guarded V2 owner and its existing state/operation/witness stores remain unchanged.

## Concrete DecisionCell encoder process: source scope

The inference-worker Python package contains a frozen, manifest-bound mDeBERTa
encoder and the shared trained organ/cell/typed-head graph. Its resident process
protocol supports exact observed-result reuse, query-only lookup, bounded pipe I/O,
physical child cancellation and owner-side private-snapshot cleanup. Detailed
commands and limits are in the
[qualification guide](../../../codex-rs/hepta-neuron/qualification/README.md#private-resident-encoder-process-and-bounded-interruption).
The local IPC frame is package-private; it does not replace ComputerActionIR or
change the registered DecisionCell request/receipt schema.

This four-target CPU profile is stateless, has no parameter-value head, and is not
installed by ordinary Agentd startup. The Python model observation, the Rust
`DecisionCellModelPortV2` adapter, the durable Neuron commit, and a platform effect
are distinct boundaries. A production composition still has to bind raw text and
target projections to the admitted Rust request, select the exact parameter and
calibration/OOD bundle through current artifact-owner trust, define clock-domain
conversion and supply measured feature/state semantics. Do not fabricate a
learned state successor or treat a Python response hash as that complete bridge.

Transport/model lifecycle tests and a real isolated clipboard qualification do
not, individually or together, prove a normal product model-to-action chain.
Synthetic-corpus backend runs and actual adapter/head optimization remain bounded
experiments, not independently accepted OOD calibration or prospective efficacy.
The developer/operator's permission to run experiments is not a third-party
provider's contractual training/distribution permission or an independent review.
