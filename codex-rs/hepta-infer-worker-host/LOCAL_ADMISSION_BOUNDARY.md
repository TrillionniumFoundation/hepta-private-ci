# Local admission preparation and recovery diagnostics

This supplement supersedes the statement in the earlier hardening ledger that
none of the verified local preparation types exist. It does not supersede the
ledger's prohibition on production local execution. The synchronous local
worker still consumes unverified compatibility policy and is not wired to the
new verifier. No physical local driver, durable local dispatch protocol or
`AttestedModelHandle` is claimed by this change.

## Implemented preparation boundary

`src/local_admission.rs`, behind `experimental-local-model` outside unit tests,
contains `LocalAdmissionVerifier`, `VerifiedResourceGrant`,
`VerifiedModelManifest`, `VerifiedInput` and `TrustedDeadline`.

The four verified values have private fields, no public constructor and no
Clone/Serialize/Deserialize implementation. They originate only from a kernel
claim of an independently signed `FinalUseGrant`. The worker has no signing key.
The unsigned request and canonical binding helper are proposals, not authority.
The witness structure is serializable audit data, never an effect-entry token.

The verifier pins the worker subject, generation and device lease from protected
host configuration. Even a valid signature for another host or generation is
rejected. The canonical request and scope bind:

- stable operation identity and load/run purpose;
- worker subject, generation and device lease;
- model, weights, tokenizer, preprocessing, quantization, runtime and device
  digests, model token ceiling and resident-memory ceiling;
- aggregate memory, model count, concurrency, tokens, KV and transient budgets;
- the actual input digest and absolute deadline.

All manifest digests must be canonical and nonzero. Resource arithmetic is
checked; resident plus workspace ceilings cannot exceed the proposed aggregate
ceiling. These are admission checks, not physical allocator enforcement.

Input is owned and immutable. The verifier hashes the actual supplied bytes;
run input is 1..32768 bytes and load preparation uses the empty input digest.
`VerifiedModelManifest` means that this exact manifest was authorized, not that
its weights, tokenizer, runtime or device have been physically inspected.

## Existing authority owner, not a new execution journal

The verifier calls `FinalUseAuthority::open_state_dir_with_trust` and requires a
host-supplied clock plus an externally durable compare-and-set frontier. It does
not select the weaker system-clock/no-frontier compatibility constructor.
Signature, signer, grant, nonce, epoch, expiry, revocation and durable nonce
consumption remain kernel-owned. A failed frontier write cannot yield a verified
claim. The kernel's existing directory/locking checks remain authoritative.

The same guarded clock is shared with the kernel. Backwards time or clock
failure fences the verifier for its remaining lifetime. Each deadline combines
the signed absolute expiry with a fixed monotonic deadline and uses checked
arithmetic. Time advancing again cannot clear a detected rollback. This
process-local guard is not a cross-restart trusted-time service; deployment must
qualify the supplied clock and external frontier. Test fixtures do not do that.

Host revocation updates use the existing monotonic kernel update path. The host
must authenticate the distribution source. `check_live` rejects a changed head,
revoked grant, elapsed deadline or failed clock. It cannot discover an upstream
revocation that the host has not delivered.

A successful preparation consumes its kernel nonce even when later abandoned.
It has no public physical-effect entry, token extraction or refund API. The
future execution boundary must additionally require an inference.control-owned
local dispatch proof and revalidate immediately before physical entry. Adding a
public `enter`, a caller boolean, or reusing hosted thread IDs as local device
handles would bypass that missing integration and is prohibited.

## Read-only hosted diagnostics

`inspect_native_run(&DurableInferenceControl, request_id)` reads one existing
owner record and produces `NativeRecoverySnapshot`. It cannot open/create a
journal, contact a provider, reserve, settle, cancel, release or replay. A missing
identity returns `RequestNotFound`. The owner handle remains the only source of
truth; no worker-side journal decoder or persistent cache is introduced.

The snapshot reports revision, worker generation, state, held slot,
cancellation, observed terminality, optional observed tokens, redacted owner
status, recorded dispatch deadline and correlation-field presence. Operation
identity is domain-separated SHA-256, not a raw request string. Prompts, model
output, principal, provider, session IDs and error text are omitted. The hash is
pseudonymous, not a guarantee of anonymization; avoid high-cardinality labels.

`recovery_action` is a routing hint only. It distinguishes a reserved request,
a observed terminal, a pre-effect stop/rejection, a reconcile-only dispatch and
legacy unresolved state. Correlation fields being present is not validation of
those fields. Only the existing authenticated reconciliation path can establish
terminal evidence. Diagnostics never authorize capacity release or retry.

The current v1 journal has no persisted first-admission or first-indeterminate
timestamp. This API therefore has no age field and does not infer age from an
absolute deadline. Held slots and unknown usage remain independent: a terminal
record can release a slot while still having unknown usage. `None` is never
converted to zero. Cumulative reconcile/denial/latency metrics and durable age
remain separate unfinished owner integration work.

## Verification scope

Four diagnostic tests use the actual durable inference.control owner and check
unchanged records/journal bytes, missing identity, reopen, held capacity,
redaction and unknown-versus-zero usage.

Ten local preparation tests use the actual kernel signature/nonce/frontier
verifier with test-only signing key, clock and in-memory frontier. They cover
exact binding and input, forged signatures, 23 scope/request mutations, valid
signatures for the wrong host, rollback fencing, wall/monotonic expiry,
revocation, resource arithmetic, frontier conflict and nonce persistence across
verifier reopen. These are source test cases, not executed-pass receipts.

Run both default and `experimental-local-model` library tests with `just test`,
then all-target compilation and strict Clippy on the exact source and
prospective merge. This editing environment has no Rust toolchain. No Rustfmt,
Rust test, binary, Clippy, device or deployment success is asserted here.

## Remaining blockers

The async physical driver, actual verified artifact descriptors, attested model
handle, live in-driver cancellation/revocation, durable local operation/handle
transitions, completed-request deduplication, trusted OS/device measurements and
cross-process resource recovery remain open. Hosted late signed usage and
permanent missing-history resolution must be integrated with the existing
inference.control owner's evolving protocol rather than a second worker store.
Configurable acknowledgement grace and complete operational metrics are not
implemented by this supplement. All production, activation, acceptance and
release claims remain false.
