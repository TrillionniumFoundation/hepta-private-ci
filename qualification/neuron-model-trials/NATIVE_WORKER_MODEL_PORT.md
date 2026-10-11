# Real Worker to Neuron ModelPort composition (shadow-only)

The Worker crate now implements WorkerNeuronControlPort, a synchronous
NeuronInferenceControlPort backed by the actual in-process InferenceWorker
and one **preexisting** WorkerRequest, not a self-issued resource grant.
It consumes this reservation exactly once on the first attempt, including
invalid identity, stale generation, mismatched payload, expired grant,
cancelled request, unknown terminal outcome, and backend error. The actual
Worker now also retains bounded **request-ID and reservation-ID tombstones**,
so recreating a ModelPort with an old pair cannot re-invoke the driver.

Execution follows this exact native chain:

authorized inference.control request + reserved Worker/ModelManifest
-> fsynced DurableInferenceControl::claim_dispatch
-> WorkerNeuronControlPort -> InferenceWorker::run_neuron_features_receipt_consumed
-> NeuronFeatureReceiptV1 -> InferenceControlModelPort
-> NeuronModelOutputV1 (Drive and Prediction Q24 separately)

The adapter enforces request ID, selected model ID, worker generation,
canonical feature payload versus both the lease/reservation digests, then
calls the real loaded Worker and verifies the complete typed receipt. It
never recreates a reservation or retries after a failed call. The Worker
enforces its current grant, loaded model tuple and memory envelope. Unknown
driver outcome is Indeterminate; malformed feature and identity mismatches
are rejected. This removes a previously missing source-level execution port.

The qualification tests run the actual Worker and the actual Neuron ModelPort,
with a **fixture ModelDriver** that produces deterministic Q24 vectors.
A separate integration test now composes a real AgentdNeuronOwner,
InferenceWorker, NeuronRuntime, on-disk sparse Journal and independent
on-disk FileAnchorWitnessStore. It confirms the Q24 receipt is durably
committed, a repeated reservation cannot create a successor, then destroys
the owner objects and reopens BOTH files to recover the exact checkpoint.
Additional tests reject duplicate request IDs with fresh reservations, duplicate
reservation IDs with fresh requests, a newly constructed port after success,
preflight rejection and indeterminate outcomes. A direct Worker caller cannot
bypass these in-generation tombstones. Storage uses SHA-256 identity sets
bounded to 65,536 attempts per Worker instance; exhaustion fails closed rather
than forgetting an old identity. A supervised generation rollover and an
**independently durable reservation owner** are mandatory for long-lived
throughput and restart-safe exactly-once claims; an in-memory set cannot prove
deduplication across process death.

Error classification at the actual ModelPort boundary is conservative:
provably pre-Worker failures (wrong binding, cancelled/expired request, bad
reservation model or lease payload) return Rejected. Once the Worker may have
invoked the driver, **all** backend, validation and receipt failures become
Indeterminate, even when the returned Q24 head identity was malformed; the
already consumed reservation cannot be reissued inside the same Worker.
A prior error that used Rejected for a post-driver model mismatch has been
corrected with a regression test. This does not yet give crash-durable replay
protection: that still belongs to inference.control's durable dispatch owner.

Its model driver is still a test backend rather than real Laya weights. This is
not proof of physical Laya safetensors, target CPU/GPU resources, signed
final-use or an observed NDU gain. No user text, labels or production CNS route
are used. The caller must separately authenticate and retain the resource
grant, reservation, trusted monotonic time, model-load CAS, generation fence
and selected route. Neither the presence of a syntactically valid WorkerRequest
nor the in-memory fixture grants any production authority.

The product Worker crate already depends on Agentd, which owns the Neuron
runtime. The new direct dependency on codex-hepta-neuron is downstream:
no reverse Agentd -> Worker runtime import and no second execution owner.
Shadow-only PR #1494 remains Draft. Production selection/NDU remain DENY_ALL.

## Durable inference.control assignment observation (read-only)

The existing `DurableInferenceControl` journal owns real (fsynced) Submit,
Reserve and Assign transitions. The additive
`read_neuron_durable_assignment_v1` does not create another owner or accept
caller-provided claimed state: it reads the owner handle and the actual
`InferenceWorker`, refuses every state except Assigned, verifies Worker
ID/generation, deadline and reservation expiry, checks current Worker grant
and actually loaded model, validates typed Q24 bounds, and recomputes the
entire canonical Neuron payload.

This only returns `NeuronDurableAssignmentDiagnosticV1`: a bounded, data-free,
domain-separated integrity commitment with `AuthorityPosture::DENY_ALL`.
It now also checks the actual in-process Worker's consumed request and
reservation tombstones. An Assigned record left behind after a Worker
attempt can no longer be presented as an unconsumed matched assignment
within that Worker generation. A self-rehashed stale report also fails
`revalidate_neuron_durable_assignment_v1`, which compares a fresh read from
both owners against the exact prior diagnostic. The new rejection tests cover
post-consumption, changed/currently cancelling state, expiry, and forged
prior digest. This is not a durable dispatch intent or a cross-process
replay-protection token.
The read neither consumes nor executes a reservation and **does not imply
crash-safe exactly-once or final-use authority**. In particular, reopening
a durable Assigned record after a process death does not prove the request
was never executed. Final-use requires the authoritative control owner to
durably claim/dispatch and reconcile uncertain results, independent signed
resource/route grants and a current physical model-load receipt.

Tests use the **actual** fsynced control journal, an actually loaded in-memory
Worker, then reopen the journal to verify exact source continuity. Negative
cases cover expired reservation, mismatched feature bytes, changed weights and
an owner-recorded cancellation. This is not production inference or NDU.


## Crash-durable pre-Worker execution intent (same owner, fail closed)

The existing `DurableInferenceControl` now offers an additive fsynced
`claim_dispatch` transition: Assigned -> Dispatching. A matching Worker ID,
process generation, assignment digest and reservation ID, current deadline,
and exact expected revision are mandatory before append; every rejected
preflight leaves the journal unchanged. Claim is deliberately NOT idempotent:
reopening a Dispatching request after process death cannot authorize the
same physical execution again. Cancellation after a claim enters Cancelling;
unknown terminal observations remain Indeterminate, never implied success.
Preexisting historical Assigned/Settle replay semantics stay decodable.

`claim_neuron_durable_dispatch_v1` is the strict Neuron bridge: it reads
both the actual durable inference.control owner and loaded Worker, builds
its reservation from that owner (not untrusted caller-supplied DTO), then
fsyncs the Dispatching event BEFORE releasing a `WorkerNeuronControlPort`.
A failed/unknown fsync cannot return an executable port. The Worker continues
to enforce its in-generation tombstones, model binding and resource grant.
Crash recovery from Dispatching forbids re-dispatch even when in-memory
Worker tombstones have disappeared. A regression now covers the crash window
where the pre-Worker claim is durably committed but the ModelPort is dropped
without ever invoking the driver. It must not reissue that identity on reopen.

The direct WorkerPort constructor is now **crate-private**; the two raw typed
InferenceWorker::run_neuron_features / run_neuron_features_receipt methods
are **test-only**, and are absent from the product library. Thus external
product callers cannot construct a Neuron WorkerPort from a self-authored
WorkerRequest or execute typed Neuron features without entering the durable
claim_neuron_durable_dispatch_v1 path. Existing module-local unit tests still
exercise these legacy rejection scenarios.

This is a compile-time public API hardening, not independently signed final-use
or an effect permit. The separate trusted host must still verify the actual
resource/route grant and physical model load before using the returned port.

This is **not** a signed final-use token or authoritative model activation.
The owner must still obtain independently authenticated current host time,
resource grant, selected model/route, physical CAS load, generation fence,
and reconcile terminal outcomes through the same journal. It cannot infer
that a committed claim proves the Worker actually ran. Tests use a fixture
NeuronFeatureDriver, real Worker/ModelPort, and the real on-disk control WAL;
there are no real Laya weights or selected production Cells.

## Global durable reservation uniqueness (legacy inference.control)

The same durable inference.control owner now keeps a bounded index mapping each
legacy Reservation ID to its original Request for the entire retained WAL.
Two distinct requests can no longer spend the same reservation, even after
cancellation or a restart. Replaying an older corrupted/ambiguous journal
with duplicate reservation IDs fails closed. A repeated read of the same
Request/Reservation remains idempotent. The native Codex request profile
uses a separate in-flight-slot model, not this legacy reservation ID field.
This is identity safety, not quota-authority authentication or an actual
production resource grant. Physical grants and selected-route evidence remain
independently owned.

## Harden historical inference.control WAL replay before dispatch admission

The legacy durable-control journal can retain requests from older profiles,
alongside the new fsynced `Assigned -> Dispatching` claim. On reopen it must
not accept structurally decoded but semantically impossible legacy events.
The native owner now rechecks legacy Submit/Reserve/Assign/Dispatch/Cancel/Settle
field constraints during journal recovery, without comparing historical
deadlines to the *new* process wall clock. It also enforces original request
token bounds and exact Request/Reservation/Worker/Model/Payload identity plus
terminal status/output coherence when applying a recovered Settle.

The regression tests append deliberately forged WAL records **after closing
the legitimate writer**, then assert that reopening fails closed for an
invalid request identity, an under-budget reservation, a terminal observation
for the wrong request, tokens exceeding the reserved maximum, contradictory
terminality, and a claimed completion without output.

This change intentionally preserves existing legacy journal serialization and
does not introduce a fake new owner, remote attestation or deployment grant.
It detects inconsistent event semantics; the historical text WAL is **not**
cryptographically tamper-evident. Production rollout still needs a separately
retained journal-head witness, trusted file access and full current authority
verification. On partial write/unknown sync, the writer remains poisoned and
does not allow a second physical dispatch.

## Idempotent retry after an uncertain WAL write

A failed or unknown fsync poisons the **entire** existing inference.control
owner. Legacy submit/reserve/assign/cancel/settle (and dispatch) now check
that fence **before** returning an otherwise matching idempotent receipt;
Native cancel/settle retries must do the same. Old in-memory state cannot
be interpreted as a durable acknowledgement. Only independently inspected
reopen and replay can reestablish a fresh owner. Targeted tests simulate each
legacy retry point and native late cancellation/settlement, then reopen the
actual WAL. The Worker CI now executes all inference-core unit tests, including
both legacy and Native owner regression modules.

This does not invent resource usage or stop late observed token overruns being
recorded, and does not provide production selection/final-use authority.
