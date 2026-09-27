# inference.worker hardening and evidence boundary

This is an implementation-status supplement to
`docs/modules/inference.worker/TECHNICAL.md`, not an activation receipt.
The remediation baseline is main commit
`a126987b84737dbc2ee2592442a314117bddb4a2`.
An implementation map's historical `sourceBase` is provenance; current-candidate
identity belongs to the generated CI receipt and must not be fabricated by
rewriting that provenance.

## Profiles

| Profile | Source status | Explicit limit |
| --- | --- | --- |
| HostedAppServerWorker | Production candidate using `native-app-server` | No activation or independent target-host acceptance inferred |
| LocalModelWorker | Experimental, non-production | Requires Cargo feature `experimental-local-model` outside unit tests |
| LegacyReceiptBoundary | Pure validation of supplied values | Not execution, signed authority, billing or device evidence |

Cargo feature selection is a build/API boundary, not a permission grant. A
transitive dependency can enable a feature. A release inventory must inspect the
resolved feature graph and must not select the experimental local driver for a
production caller. Unit tests intentionally retain local negative tests without
making that API available in the default production library.

## Local resource lifecycle implemented in source

`model_worker.rs` owns the synchronous experimental worker. Value validation is
in `model_worker_types.rs`, Neuron projections in `model_neuron.rs`, and aggregate
process-local resource accounting in `model_resources.rs`.

Before physical load, the worker reserves the manifest's entire nonzero
`maximum_resident_bytes` upper bound. Before a request, it additionally reserves
`maximum_kv_bytes + maximum_transient_bytes` using checked arithmetic. Every
loaded model and admitted workspace draws from the same generation-wide limit.
An injected driver must itself enforce these bounds; a post-execution memory
number is not OS/device enforcement or an attestation.

The RAII lease has two distinct drop semantics. Before physical entry, dropping
a lease returns definitely-unused capacity. After entry, dropping without an
observed terminal outcome retains the budget, records a quarantined reservation
and fences the generation. Allocation errors without a returned handle are not
proof that the allocator did nothing. There is no automatic unfence or refund
based on elapsed time.

Unload borrows the stored driver handle. The model is marked repair-required
before unload; an error retains both handle and reservation for cleanup retry.
Only a successful unload removes the record and releases resident capacity.
Cleanup remains possible after policy expiry, revocation or generation fencing:
it reduces resource use and cannot start inference. A successful cleanup does
not silently reset a fenced generation or clear unrelated unknown workspaces.
A device-reset notification can only fence the generation.

Local token observations use `Option<u32>`. `None` is unknown, including a
terminal response with missing accounting. Pre-dispatch cancellation alone may
report the observed zero `Some(0)`. The legacy v1 pure receipt API retains its old
zero sentinel for compatibility and must not be consumed as billing evidence.

The experimental Neuron feature digest has an explicit v2 domain separator and
binds the new workspace limits. Old v1 digests are not silently reinterpreted.
The inference.control-owned Neuron receipt format is not changed by this
experimental admission digest revision.

## Verified local preparation implemented separately

`local_admission.rs` now provides privately constructed `VerifiedResourceGrant`,
`VerifiedModelManifest`, `VerifiedInput` and `TrustedDeadline`. It reuses the
kernel signed-grant verifier and durable nonce state, requires a host clock and
external compare-and-set frontier, hashes actual owned input, and binds the
worker/generation/device lease, complete model tuple, resource limits, purpose
and absolute deadline. A shared guarded clock fences rollback; a fixed monotonic
deadline prevents retry-based extension. The types cannot be cloned or restored
from serialized untrusted input.

This is preparation only. See [local admission and diagnostic boundaries](LOCAL_ADMISSION_BOUNDARY.md)
for the canonical binding, revocation, time and test scope. There is deliberately
no public effect-entry API until an inference.control-owned local dispatch proof
exists. No private signing key, physical loader, `AttestedModelHandle`, or device
attestation is introduced by this preparation layer.

## Capabilities that are NOT closed by these changes

The existing synchronous model worker is not connected to the new verifier. Its
`ResourceGrant` is still an unverified compatibility policy, its clock is supplied
by the caller and cancellation is a pre-entry snapshot. The sealed preparation
layer does not upgrade that older path into an authorized async executor. Actual
verified artifact descriptors and a physical async driver remain missing.
Production local execution remains prohibited.

The local model/operation records and resource counters are process-local. A
completed local request is not durably deduplicated, and process loss cannot be
reconciled from these counters. The follow-on implementation must extend the
existing inference.control owner with versioned local dispatch/handle/grant
witness semantics, without inventing another incompatible worker journal. It
must not reinterpret hosted App Server thread identifiers as local device
identities or use a timeout as proof of non-execution.

The required trusted OS/device memory observer, real weights/tokenizer/runtime
loading proof, live cancellation/deadline handling, multi-process reservations,
OOM/device-reset/load-kill qualification and independent acceptance remain open.
The resource snapshot is diagnostic state, not physical isolation evidence.

## Hosted recovery scope

Exact App Server thread-history reconciliation already exists in
`native_app_server.rs` and is used on uncertain reopen. It matches the original
operation, input, thread, session, provider and runtime binding and never starts a
new turn to recover the same operation.

`inspect_native_run` additionally exposes a redacted, no-effect snapshot through
an already opened inference.control owner. It reports persisted revision, slot
occupancy, terminality and optional usage without opening a journal or contacting
a provider. It does not authorize settlement/release or infer age from a deadline.
Four regression tests exercise unchanged journal bytes, reopen, unknown identity,
held capacity and unknown-versus-zero usage through the real durable owner.

Missing-history resolution, later trustworthy token-usage reconciliation,
configurable lost-acknowledgement grace and the complete operational monitoring
surface remain open. The ephemeral-thread history retention and unresolved-effect operating contract in
`FINAL_USE_AUTHORITY_PORT.md` continues to apply. History loss is indeterminate,
not a terminal negative result and not permission to replay or reset a journal.

## Qualification and current status

`.github/workflows/hepta-inference-worker.yml` adds independent inference.control,
inference.worker and Agentd library steps on Linux/macOS source-head and
merge-candidate trees. It also checks owner formatting, binary compilation,
all-target compilation, strict Clippy and unchanged tracked state. Failures in
one library do not skip the other owners. Existing qualification workflows are
not removed or weakened.

`scripts/hepta_inference_status.py` writes `CURRENT_STATUS.json` to an artifact,
not into the source tree. It binds source/base/tested commit and tree identities,
Git source-blob IDs, the current lane/run, per-step outcomes and SHA-256 hashes of
retained JUnit files. Missing, malformed, skipped, failed or zero-test evidence
cannot produce a successful lane receipt. Binary compilation is explicitly not
reported as binary behavioral testing. A single-platform artifact does not claim
the other platform or the other candidate lane passed.

Real-hardware, target-host composition, independent acceptance, activation and
release remain unobserved/false. This document contains no Rust pass receipt.
The authoring environment has no Rust/Cargo/rustfmt. A CI-produced source archive
at `543c2a2a6a35d5a8cfacb2c451f83d280fdce8eb` was recovered and its Git tree
reconstructed exactly as `04c2dbe045353b23b1d36ecf72ed37dba2456f8d`; full Git
ancestry was not reconstructed. Against that source, seven Python receipt tests,
`refresh-derived --check` and the strict module registry passed locally. These
are not Rust execution or complete source-map qualification receipts.

The same candidate's CI passed derived projections, the registry and macOS
inference.control library steps, but reported stale cross-module implementation
maps and six Rustfmt differences in the new admission files. Those exact format
differences are corrected in the follow-up source commit. Native worker/Agentd,
Linux and full Clippy success were not observed at that checkpoint. Actual
formatting, compilation, tests and lint must be read from each final candidate's
CI artifacts, never inherited from that diagnostic checkpoint.
Queued/running workflows and tests merely present in source are not completion.

## Review and remaining sequence

The resource change is staged separately from qualification plumbing. Its large
file diff includes mechanical extraction of the original model/Neuron module;
public entrypoints remain in `model_worker.rs`, with the existing test identities
retained. Review the resource state transitions separately from the extraction.

Before merge, require current source and merge receipts, resolve the inherited
owner/lifecycle and derived-projection failures rather than masking them, inspect
the default/experimental feature graph, and run the registered ownership and
Bazel checks. Next compose the verified local preparation with the existing
owner-journal dispatch/recovery protocol and an async physical driver, then
qualify actual devices and provider resolution. Non-ancestor historical map
anchors and cross-owner source drift are repository-controlled baseline blockers,
not hardware limitations; refreshing this module's source observation alone
cannot close the repository-wide check. No source commit in this branch grants
production or release rights.
