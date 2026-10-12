# Real Worker to Neuron ModelPort composition (shadow-only)

The Worker crate now implements WorkerNeuronControlPort, a synchronous
NeuronInferenceControlPort backed by the actual in-process InferenceWorker
and one **preexisting** WorkerRequest, not a self-issued resource grant.
It consumes this reservation exactly once on the first attempt, including
invalid identity, stale generation, mismatched payload, expired grant,
cancelled request, unknown terminal outcome, and backend error. The actual
Worker now also retains bounded **request-ID and reservation-ID tombstones**,
so recreating a ModelPort with an old pair cannot re-invoke the driver.

A durable Dispatching claim also captures its **pre-fsync monotonic instant**.
At actual ModelPort use, the port adds elapsed monotonic milliseconds to the
host-authenticated claim timestamp and rechecks both the request deadline and
Worker ResourceGrant. Storing the port until the lease expires therefore cannot
reuse an earlier claim-time timestamp; the reservation is still tombstoned
before any rejection. Overflow fails closed. The host must authenticate the
absolute time supplied at claim; process elapsed time does **not** replace
trusted wall-clock attestation. Unit regressions age a claimed port without
sleeping and verify zero physical driver calls and no replay.

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

The Agentd product host now exposes `tick_with_observation_v1`, which consumes
the actual Worker/ModelPort once and checks the separately acknowledged
Journal/Witness after the call. It emits a compact, recomputable
`AgentdNeuronTickObservationV1` binding the exact input feature digest,
tick ID, objective/NDU context, model runtime tuple, output signals, observed
resource costs, committed checkpoint and complete local model configuration.
It never exports Q24 features, activation vectors, raw observations or labels.
The actual Worker-to-Agentd recovery test exercises this method and refuses
tampered input, output and stale witness observations. This is NOT yet a
selected production no-change baseline; the independent evaluator must map the
event to the authoritative selected-route/cell identity and Ledger Episode,
retain a historical signed receipt, and revalidate source/route final-use.

The qualification tests run the actual Worker and the actual Neuron ModelPort,
with a **fixture ModelDriver** that produces deterministic Q24 vectors.
A separate integration test now composes a real AgentdNeuronOwner,
InferenceWorker, NeuronRuntime, on-disk sparse Journal and independent
on-disk FileAnchorWitnessStore. It confirms the Q24 receipt is durably
committed, a repeated reservation cannot create a successor, then destroys
the owner objects and reopens BOTH files to recover the exact checkpoint.

The end-to-end Neuron tick/recovery test now also opens the actual
`DurableInferenceControl` WAL, fsyncs Submit/Reserve/Assign and its
non-idempotent Dispatching claim *before* obtaining the Worker ModelPort,
and then runs the actual Agentd tick. When the Neuron Journal has committed
but its independent witness temporarily rejects acknowledgement, retrying
the same tick only reconciles the witness; it does not spend a second Worker
reservation. After dropping both owners, the test separately reopens the
inference.control WAL and Neuron Journal/Witness and checks that a fresh Worker
cannot reuse the old Dispatching identity. These are fixture-model tests on
real durable owners, not real Laya inference or a signed deployment.

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


## Independent reservation resource-unit accounting

The native legacy inference.control journal now rejects a terminal outcome
whose observed usage_units exceeds the durable Reservation.quota_units, in
addition to checking consumed_tokens against maximum_tokens. The same helper
checks live settlements **before fsync** and all recovered historical WAL
events. A terminal outcome marked unknown/Indeterminate is not exempt.
Rejected settlement does not modify the WAL or advance its revision.

Tests exercise full-fsynced Dispatching records with over-budget terminal
and unknown observations, legal exact-budget settlements and clean reopen,
and externally appended WAL records with forged over-budget resource units.
This is a quota-consistency gate, not an independent physical metering proof.

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

## Canonical semantic identity enforced before durable Neuron dispatch

The strict Neuron bridge now requires the actual fsynced
\`InferenceRequest.semantic_digest\` to equal
\`neuron_feature_request_digest_v1(&NeuronFeatureRequestV1)\` for the
exact typed request. The feature-payload digest alone does not commit
request ID, Worker generation and selected model ID, so it cannot
substitute for that semantic identity. The existing generic inference.control
WAL format remains unchanged for legacy/non-Neuron callers.

A new native regression preserves a valid worker, assigned reservation and
correct feature payload but supplies a different, structurally valid semantic
digest. Both diagnostic revalidation and \`claim_neuron_durable_dispatch_v1\`
must reject it **before** appending Dispatching or invoking the model driver.
The test closes and reopens the actual journal to verify that persistent
mismatch is not converted into a replayable grant. The existing deliberately
out-of-Q24-range fixture still tests typed request validation and is never
mistaken for a valid semantic identity.

This closes an identity-binding gap but is not host-authenticated production
selection, a signed physical model-load receipt or an NDU advancement.

## Failed model-load / unload containment and aggregate resident budget

The actual \`InferenceWorker\` now treats a successful \`ModelDriver::load\`
as a resource admission candidate, **not** as authority to keep the handle.
Every loaded model's driver-observed resident bytes contribute to the SAME
\`ResourceGrant.maximum_memory_bytes\` total; checking only one handle's
size would otherwise allow multiple Cells to exceed the reservation.
This is a bounded O(MAX_MODELS <= 8) scan only on load, not per inference.

- Unknown driver load errors permanently quarantine that Worker generation;
  a failed load might have allocated resources before reporting failure.
- Invalid/zero-memory/over-budget handles require a successful driver
  unload before returning a recoverable rejection. Unknown cleanup leaves
  the Worker quarantined.
- Opaque handle reuse across different loaded Model IDs is rejected and
  quarantines the Worker. The duplicate is NOT unloaded because its handle
  may alias a live model and destroy the predecessor.
- Unload no longer forgets the live handle before observing a successful
  driver unload. An unknown result keeps the occupied handle in the Worker
  and permanently fences new model loads, inference and unloads until the
  Supervisor separately retires that generation.
- Model/registration tests inject bad handles, oversized/zero memory,
  aggregate memory overrun, ambiguous loads, failed cleanup, unload failure
  and aliasing. No fixture result is a signed or physical GPU memory attestation.

The observed resident byte counts come from the local \`ModelDriver\` and
are not independently authenticated RSS, GPU allocations, shared Encoder
buffer sizes or whole-process peaks. The Supervisor and actual runtime
still own physical process retirement and quota reclamation; the Worker
must not claim that dropping a Rust handle proves physical cleanup.
Crash recovery, current signed resource grants, actual CAS load and CNS
selection remain separate gates. This code never changes production
selection, release, final-use permission, model rankings or NDU.



The typed Neuron driver now additionally reports `consumed_tokens` observed
**after** real execution. The Worker rejects post-driver token use beyond
*any* of the request, reservation or loaded-model limits, matching ordinary
Worker accounting. The ModelPort treats this as **Indeterminate**, retains
the already-consumed attempt tombstone, and must not retry the durable
Dispatching claim. The raw observation includes the token count for local
resource diagnostics; the existing `NeuronFeatureReceiptV1` wire contract
does **not yet** export it, so this is not end-to-end token cost accounting.
Tests use a fixture driver consuming 17 tokens against a limit of 16 and
verify no replay; they do not prove third-party GPU/CPU driver metering.

## Defense-in-depth: enforce typed Neuron token quotas inside the Worker

The durable inference.control assignment already bounds the requested tokens
against its approved reservation and loaded model. The Worker also validates
the two limits again immediately before a typed `NeuronFeatureDriver` call,
matching the ordinary `InferenceWorker::run` budget check. This does not
change any grant, permit more tokens or create another admission owner.

The native regression confirms that both an over-manifest limit and an
over-reservation limit fail without calling the physical driver, that the
first rejected request cannot be replayed, and that a fresh valid token
reservation still succeeds. This is a fixture driver test, not a production
throughput or model-quality result.

## Independent model and Worker lifecycle generations

The typed `NeuronFeatureRequestV1.generation` identifies the frozen Neuron
Cell/model generation and is committed by the fsynced inference.control
`InferenceRequest.semantic_digest`; its `NeuronFeatureReceiptV1` must bind
that same model generation. The `Assignment.worker_generation` independently
identifies the current Worker process. These are different lifecycle domains:
a supervised Worker restart does not force a deployed Cell to change model.

The durable assignment read now checks `assignment.worker_generation` against
the **actual** `InferenceWorker.worker_generation()`, while separately
comparing the entire typed semantic request hash (including model generation)
to its durable record. The crate-private `WorkerNeuronControlPort` pins that
Neuron generation at claim time and rejects request drift before the driver;
the Worker converts it to the typed receipt without substituting its process
generation. The test-only direct Worker constructor also pins the declared
Neuron generation explicitly. No public typed contract bytes are changed.

A real WAL/Worker integration test uses Neuron model generation 7 and Worker
process generation 3, then proves signed-reservation-style durable claim,
actual fixture driver execution, and no dispatch replay after restarting the
Worker and reopening the WAL. A changed model generation under the original
fsynced request remains invalid before invoking the driver. These are fixture
identities and **not** real production keys, CNS routing, or a physical Laya
load; all authority and NDU promotion remain disabled.
