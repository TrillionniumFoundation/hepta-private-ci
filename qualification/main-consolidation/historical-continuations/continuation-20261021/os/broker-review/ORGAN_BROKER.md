# Organ control broker seam

This crate is the first implementation seam for issue #111. It is deliberately
**default deny** and does not claim A05 or A07 completion.

trill-ui-broker exposes a versioned, pointer-free UI protocol. The renderer or
mobile client sees only bounded strings, digests, generations, boot-local
delivery identifiers, explicit generation fences (authority/body/resource/bridge/owner), and unknown states. It never receives raw HOS2
pointers, CapSpace handles, signer material, Agentd UDS paths, PIDs as
authority, or platform device handles.

The protocol keeps the durable Hepta key
K = (scope_id, operation_id, payload_digest) in DurableIntent separate from
the boot-local HOS2 delivery binding
D = (boot_id, delivery_id, capspace_epoch, sequence). A delivery binding is
not a durable operation identity and a process restart does not silently turn
a new D into a retry of K.

SameUidAuthenticator uses Linux kernel SO_PEERCRED data through
peer_credentials_from_unix. This authenticates the kernel-reported UID/PID
at the transport boundary only. Same-UID application identity, A05 CapSpace
grants, A07 Final-use, signer verification, and device authority still require
the future owner integration. The broker therefore grants only Observe,
OfflineDraft, and Reconcile; SubmitEffect and CancelEffect are always denied.

Each SessionHandle is bound to the Broker instance that authenticated it.
Its numeric session_id is a local counter, not a transferable credential.
Another Broker, including one created after a restart, rejects the old handle
even when its local counter has the same value. A foreign handle cannot close
a local session. Clones keep the original session identity; closing that
session invalidates every clone. This process-local binding does not replace
transport authentication or grant any effect authority.

The broker operation and replay maps are bounded process caches used to
remember an indeterminate observation and make notification replay idempotent.
They are not a second K ledger. The maps are intentionally lost on restart.
Until the original Hepta owner supplies a verified receipt, reconciliation
returns unknown and never infers success from a process exit, timeout, or UI
message.

Notifications are bounded. A dropped prefix sets reconcile_required, so a
mobile client that disconnects must pull/reconcile before presenting a terminal
effect. Offline drafts return local_only; they contain a digest and can be
stored by the local draft facility, but cannot submit an effect.

The crate adversarial tests cover protocol version/unknown-field rejection,
foreign-UID rejection, denied effect capabilities, K/D separation, generation
fences, unknown reconciliation, bounded notification loss, replay conflict,
foreign/restarted Broker handles, and shared clone invalidation.
