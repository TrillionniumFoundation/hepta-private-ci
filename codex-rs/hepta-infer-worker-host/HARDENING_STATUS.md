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

## Capabilities that are NOT closed by these changes

The local `ResourceGrant` remains an unverified experimental policy. The worker
still has a synchronous driver, a caller-supplied clock, and pre-entry cancellation
snapshot. These changes do not implement `VerifiedResourceGrant`,
`VerifiedModelManifest`, `AttestedModelHandle`, `TrustedDeadline`, actual verified
input descriptors, or a physical async driver. They must not be advertised as
having done so. Production local execution remains prohibited.

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

Missing-history resolution, later trustworthy token-usage reconciliation,
configurable lost-acknowledgement grace and the complete operational monitoring
surface are not closed by the local-resource patch. The ephemeral-thread history
retention and unresolved-effect operating contract in
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
The authoring environment did not provide Rust/Cargo/rustfmt or a complete local
checkout; only the Python receipt logic was executed locally. Actual formatting,
compilation, tests and lint must be read from the exact candidate's CI artifacts.
Queued/running workflows and tests merely present in source are not completion.

## Review and remaining sequence

The resource change is staged separately from qualification plumbing. Its large
file diff includes mechanical extraction of the original model/Neuron module;
public entrypoints remain in `model_worker.rs`, with the existing test identities
retained. Review the resource state transitions separately from the extraction.

Before merge, require current source and merge receipts, resolve the inherited
owner/lifecycle and derived-projection failures rather than masking them, inspect
the default/experimental feature graph, and run the registered ownership and
Bazel checks. Next close the verified local authority/input boundary and existing
owner-journal integration; then qualify actual physical devices and provider
resolution. No source commit in this branch grants production or release rights.
