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

## Physical model weight-file SHA-256 versus the actual loaded Worker manifest

`model_worker::inspect_loaded_neuron_weight_file_v1` now accepts a host-opened
**regular File** and the actual `InferenceWorker` instance (not a caller-authored
model tuple). It first checks that this Worker has an unquarantined, currently
authorized ResourceGrant and that the model identity is actually loaded, then
streams the full file through the native `Digest32::of_reader` SHA-256
implementation using fixed 32 KiB scratch space. The maximum is 2 GiB (not
the 64 MiB Artifact Registry payload cap), sufficient for the frozen Laya
644–843 MB single safetensors files. It requires the **full file hash** to
equal the weights digest already retained by the loaded ModelManifest.

Regular-file type, nonzero byte size, maximum bound and before/after file
metadata are checked. The caller's file cursor is restored. The diagnostic
binds current Worker ID/process generation, observed loaded handle identity
and memory bytes, manifest/model/weight digests and exact file length.
Invalid/nonregular/oversized/changed files, hash mismatch, expired/revoked
grant, absent loaded model or Worker quarantine fail closed. Tests actually
write/read/tamper regular files, test sparse size rejection without reading
2 GiB, and test grant expiry and revocation.

**Scope restriction:** this is a physical **source-file hash observation**,
NOT proof that an opaque ModelDriver handle was created by loading this same
file, nor evidence of a signed CAS or selected CNS/Cell route. The input File
must originate from the independently approved immutable model-storage owner;
its path/open provenance is not authenticated by this method. In-place writes
after verification or a driver loading different bytes remain possible until
the real host pins the same immutable handle through load and final-use.
This never dispatches a model, changes a route, or grants production use.
All returned receipts are `DENY_ALL` and cannot satisfy NDU/promotion.

## Preopened-FD, hash-before-driver model load (diagnostic)

New `NeuronPreopenedWeightModelDriver` is opt-in with NO fallback to
`ModelDriver::load`. `InferenceWorker::load_model_from_preopened_weight_file_v1`
takes a host-opened `File` by ownership, validates the grant and manifest,
streams the COMPLETE file (2 GiB ceiling) into a SHA-256 comparison with
that manifest, rejects digest/size/mutation differences, rewinds the SAME
File and MOVES it into the specialized driver's loading method.

The ordinary Worker admission remains shared: handle uniqueness, cumulative
resident-memory budget, quarantine before the driver call and cleanup of
rejected handles. An indeterminate physical load quarantines the Worker
instance. The diagnostic receipt binds actual preloaded file digest, length,
model and handle identity, Worker generation, and `DENY_ALL` authority.

A separate handle cloned from the SAME open file is retained before invoking
the driver. After the driver returns a live model handle, the Worker rechecks
the source file metadata and **streams a second full SHA-256 over the same
inode**. A failed/changed read (including in-driver mutation) permanently
quarantines the Worker generation and withholds the successful load receipt.
No subsequent model run, unload or new load can use this poisoned Worker.
This deliberate double hash is a slow-path model-load cost only, not per Cell
or per inference. The source-hash check is still a diagnostic, not trusted
CAS immutability, loader-code attestation, a signed load receipt or CNS route.

Tests use a real preopened temporary file and a driver that reads ONLY that
file; wrong bytes are rejected before driver entry while unknown driver
outcomes quarantine the Worker. No synthetic throughput is presented as real
Laya inference.

**Limit:** an opaque malicious driver could ignore the passed descriptor,
and a concurrently writable file could change after hashing. A trusted host
must guarantee immutable CAS file provenance, actual loader behavior,
current signed Final-use, generation fences and an independently verified
physical ArtifactLoadReceipt. This is not evidence of serving CNS selection,
Neuron learning gains, or authority to promote a production model.

## Worker-issued file-load receipt freshness (in-process only)

The physical preopened-file loader now returns a diagnostic with **private
fields**; ordinary external Rust callers cannot assemble a fake successful
\`NeuronFileBoundModelLoadV1\` from self-reported model-load values. The actual
Worker assigns a checked monotonic \`load_revision\` before each driver
invocation, and stores that same revision on the admitted loaded handle.

\`InferenceWorker::revalidate_file_bound_model_load_v1\` reads the live Worker
grant and model map. It rejects unloading, quarantine, manifest drift, handle
replacement, incorrect Worker identity/generation, or reuse of an old receipt
after unload/reload of the same Model ID, weights and opaque handle. The
single-process load ordinal does **not** survive a Worker process restart;
the independent Supervisor's process-incarnation and generation-fence
evidence are still mandatory before any serving use. Successful validation
does not attest that an opaque loader consumed the bytes, authorize CNS
selection or issue final-use permission.

The regression physically writes and loads a file twice through the
preopened-FD trait, reuses the same handle identity, proves the old ticket
fails, and refuses a caller-rehashed load ordinal and a revoked grant. The
strict Worker CI still executes all previous file rehash, full-Cargo and
durable inference-control checks.

## File-bound model ticket + fsynced single-use Neuron dispatch

The product-oriented **opt-in strict pre-dispatch seam**
\`claim_neuron_file_bound_durable_dispatch_v1\` joins two actual owner states
*before* consuming a durable inference.control reservation:

1. Require a private-field \`NeuronFileBoundModelLoadV1\` previously issued by
   this exact Worker after streaming and rehashing its preopened weight file.
2. Revalidate that ticket against the Worker's live grant, generation,
   loaded model handle, identity, weights digest and **load revision**.
3. Check that the typed Neuron feature request names that exact model and
   those same weights, then call the existing
   \`claim_neuron_durable_dispatch_v1\` to fsync a single-use Dispatching intent.
4. Return the existing \`WorkerNeuronControlPort\` holding an exclusive mutable
   reference to the same Worker, forbidding an unload/reload before execution.

A stale ticket, reloaded same-ID model, different weights or expired grant
**never appends** the Dispatching record. The previous lower-level claim API
remains for compatibility/diagnostics; it does not guarantee a file-bound load.
Neither entrypoint grants CNS route selection, physical loader attestation,
CAS immutability, a signed Final-use token or NDU promotion.

Native tests create real local File objects and exercise the specialized
preopened model Driver, two physical loads of identical bytes, rejection of
the old ordinal before WAL mutation, wrong-weight and expired-grant rejection,
the one fsynced accepted dispatch, Worker ModelPort execution and WAL reopen.
Only synthetic fixture inputs are used, never actual Laya weights or
production evidence.


## Exact in-process Worker instance fence on file-load receipts

The file-bound ModelLoad diagnostic previously bound the public Worker ID,
generation, model, driver handle and monotonically increasing load ordinal.
A reconstructed Worker could reuse *all* those names and start its ordinal at
one. Consequently, an old in-memory load ticket was not distinguishable from
the next instance's own ticket when passed to file-bound dispatch.

Each \`InferenceWorker\` now owns a private, nonserializable allocation-backed
instance identity. \`NeuronFileBoundModelLoadV1\` retains a clone of that
identity, and the original Worker's exact pointer identity must match before
any fsynced \`claim_neuron_file_bound_durable_dispatch_v1\` is allowed.
The receipt's Rust equality uses the same pointer semantics. This has no
cryptographic signature or false claim of cross-process durability: the
portable diagnostic hash intentionally excludes the private instance token.
It is solely a stricter SAME-PROCESS load-ticket validation; the external
process incarnation, authoritative model routing, signed load, and final-use
remain mandatory. Existing durable inference.control claim replay prevention
is unchanged.

Two tests reconstruct a Worker with identical public generation, model and
driver-handle labels plus load ordinal, then reject its predecessor ticket.
The dispatch test also checks the durable Assigned revision remains unchanged
before a fresh, same-instance receipt can claim and execute exactly once.
Fixture weights and drivers, not Laya production models, are used.

## Additive per-execution typed Neuron token-cost diagnostic

The Worker retains one optional WorkerNeuronTokenCostV1 directly from its
real NeuronFeatureDriver observation after a verified NeuronFeatureReceiptV1.
It binds the exact typed request digest, receipt digest, consumed reservation
ID, worker instance ID and generation, observed token count and terminal
status. The receipt is SELF-CONSISTENT, not a physical independent meter.
WorkerNeuronControlPort::take_cost_diagnostic is single-use; a repeated
or rejected call deletes the previous cost rather than double-crediting it.
An unknown post-driver outcome with no validated typed receipt produces NO
numeric cost claim. Even a structurally valid Indeterminate or Cancelled V1
receipt never generates a token-cost diagnostic: unknown consumption cannot
be scored as zero. Overage still permanently quarantines the Worker.

This is additive; the frozen NeuronFeatureReceiptV1 wire bytes and Q24 math
have not changed. Future NDU may evaluate the diagnostic only after an
independent, trusted metering Owner correlates it with resource grants,
actual route/fence and Ledger outcomes. Current experiments provide NO
signed total token/CPU cost evidence and no production promotion authority.


## Read-only cost/Dispatching correlation and Worker incarnation fence

The physical Worker now binds each known-terminal token-cost observation to an
opaque **in-process Worker incarnation identity** AND the exact monotonic
`model_load_revision` of the physical model actually loaded in that Worker.
A process identity alone cannot make a stale cost current after unloading and
reloading the SAME model/weights/driver handle. An actual Worker regression
tests this exact failure mode. Two Worker instances may
present the same public ID, generation and ModelManifest after a restart, yet
cannot inherit one another's prior observed cost. The opaque token is never
serialized, hashed by pointer address, treated as a host attestation or accepted
as a persistent generation fence.

The additive read-only
read_neuron_observed_cost_source_v1 / revalidate_neuron_observed_cost_source_v1
functions compare one verified typed NeuronFeatureReceiptV1 and one
WorkerNeuronTokenCostV1 against the **current real inference.control durable
Dispatching WAL** and the exact in-memory Worker. Checks include original
typed request digest, reservation/assignment and revision, worker incarnation,
selected loaded model/weights/tokenizer/runtime tuple plus model-load ordinal,
typed receipt digest and known-terminal observed token count within
request/reservation token caps.

The returned NeuronObservedCostSourceV1 has DENY_ALL and one recomputable
diagnostic digest. It does NOT invoke the Worker, settle a WAL entry, charge
resource quota units, assign monetary costs, infer NDU utility or let a
request rerun. A self-rehashed report is rejected by an independent fresh read.
Cancelling/settled/unknown requests, Worker restart, model unload and missing
current resource grant block revalidation. A known failure can have actual
observed token use; Indeterminate/Cancelled cannot produce a numeric cost
in this profile. The separate quota_units field is not tokens and cannot be
converted without an authenticated independent usage schedule.

These diagnostics are transient. Future cross-process settlement requires the
existing durable owner to append independently authenticated terminal facts
and reconcile unknown physical effects; no opaque process incarnation pointer
is a substitute for an external boot/session identity. Unit tests use a
fixture ModelDriver with real fsynced Dispatching, current Worker, actual typed
ModelPort, WAL reopen, stale/cancelled and replacement-Worker refusals. No
real Laya training or selected production CNS route is established here.


## Read-only historical Neuron token-settlement audit

A successful known-terminal Worker execution has a short-lived
\`NeuronObservedCostSourceV1\` tied to its original in-process Worker, load
revision and fsynced Dispatching record. After the authorized settlement owner
fsyncs a terminal observation, the original current-Worker read is correctly
rejected. The new \`read_neuron_settled_cost_diagnostic_v1\` instead compares
that previously validated, retained diagnostic with the **real reopened durable
inference.control WAL**, requiring:

- a Completed status for a Succeeded typed feature receipt, or Failed/Failed;
  never Cancellation/Indeterminate;
- the exact request semantic digest, model manifest, reservation/assignment,
  Worker identity/generation and immediate Dispatching -> settlement revision;
- the **persisted** consumed token count exactly equal to previously observed
  tokens, within both request and reservation ceilings;
- the separately supplied persisted \`usage_units\` within quota, with
  **no conversion from tokens to quota units**.

It returns a separate DENY_ALL, domain-separated historical checksum and
rejects caller-rehashed token/usage changes against a fresh WAL read. Tests
perform a real fsynced settlement, verify same-WAL and crash-reopened results,
and reject altered token claims, charged units and receipt bytes.

This is a historical reconciliation diagnostic, **not** independent
authentication of the physical meter or of terminal output bytes: the WAL
persists the supplied terminal observation digest, status and token count,
not the full independently signed terminal observation. The physical Worker
incarnation is NOT persistent proof after restart. The host must originally
retain the source observation while the live Worker exists and must obtain
independent real provider/Observer, quota tariff, CNS/Fence and NDU evidence
before treating anything as a production cost or learning improvement.

## Strict historical Neuron feature-payload binding

The V1 historical token-settlement reader now reconstructs the entire
canonical typed Neuron feature payload from the **reopened durable WAL**
(request/reservation, model/weights, Q24 features, dimensions and deadline).
It refuses a generic legacy WAL record containing the correct typed semantic
digest and terminal token count but a different actual execution payload.
The same exact payload check already existed before Dispatching; it must
also apply to post-restart historical correlation. This prevents combining
two separately valid, nonmatching request identities into an apparent cost.

An adversarial test actually fsyncs a generic Completed WAL record with an
unrelated payload digest and otherwise matching Worker/request labels, then
rejects historical scoring both before and after crash-style reopen. The
positive unchanged typed-execution settlement and token accounting tests
remain separate. No WAL format, token-price conversion, promotion authority,
physical model loader or serving route is introduced.

## Crash-replayed output identity in historical Neuron token settlement

The existing durable inference.control WAL already stores a terminal
\`output_digest\` in every complete Settle event, but previously discarded that
field when rebuilding its in-memory \`RequestRecord\`. The same native owner now
retains \`terminal_output_digest\` on original commit AND historical replay.
\`read_neuron_settled_cost_diagnostic_v1\` refuses an externally supplied typed
Neuron Feature receipt whose output digest differs from this WAL-owned value,
even when every request/model/payload digest, Worker ID and token count match.

The native \`settle\` idempotent retry also checks the exact retained output,
terminal state and observed token/quota amounts: reusing a caller-supplied
observation digest with changed settlement bytes cannot get a false
idempotent acknowledgement. This is a read-side correlation check on
previously serialized WAL facts, not a new WAL format or a physical output
attestation; the trusted source/observer and current selection are still
external. Tests exercise exact retry, forged matching-observation-ID retry,
mismatched output and recovery from the real file on disk.

## Real Worker known-terminal settlement on the existing durable owner

The settle_neuron_live_worker_terminal_v1 function consumes the already
observed, single-use Worker terminal and revalidates its receipt, cost and
current in-process Worker against the actual fsynced Dispatching
inference.control record before committing the Settle event. The helper then
rereads the actual WAL and checks exact output, token and separately supplied
resource-unit totals. Over-budget pricing leaves the WAL at Dispatching;
successful settlement cannot be repeated; reopened WAL preserves the terminal
identity and cost.

The priced_usage_units argument is **not** independently metered or signed.
The generated observation digest is **not** an independent Observer signature.
The historical reader now re-derives that exact terminal observation digest
from the retained Worker source, typed output and WAL-owned separately priced
usage units. A structurally valid *generic* Settle cannot inherit a Neuron
terminal simply by matching request, output, tokens and price while using an
unrelated observation digest; reopening the actual WAL also rejects it. This
is a deterministic consistency check, NOT an independent signature or meter.
The helper adds no route selection, token pricing, NDU approval, model
promotion, trusted final-use, or authority to spend. If fsync or postcommit
verification fails, the outcome must be reconciled from the owner WAL before
any new use. Tests use actual file-backed inference.control and a fixture
Worker driver; this remains a diagnostic boundary, not real Laya inference.
