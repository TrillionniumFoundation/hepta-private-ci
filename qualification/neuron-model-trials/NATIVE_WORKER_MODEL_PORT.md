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

pre-admitted WorkerRequest/ResourceGrant + already loaded ModelManifest
-> WorkerNeuronControlPort -> InferenceWorker::run_neuron_features_receipt
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

