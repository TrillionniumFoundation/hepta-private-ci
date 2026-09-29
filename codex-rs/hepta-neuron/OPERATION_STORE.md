# Durable neuron operation and result store

`FileNeuronOperationStore` is the owner-local sidecar for the V1
`NeuronRuntime`. It complements, rather than replaces, the sparse checkpoint
journal and the independent acknowledgement witness:

- `SparseJournal` owns deterministic checkpoint evolution;
- `FileNeuronOperationStore` owns the complete logical operation and its exact
  result;
- `AnchorWitnessStore` owns the externally acknowledged checkpoint frontier.

None of these stores grants model-selection, effect, deployment, promotion or
release authority.

## Frozen identity

The `HPTNOP01` header binds the semantic digest of the complete
`NeuronRuntimeConfigV1`, subject scope, objective, generation and state width.
The runtime-config digest includes the model manifest, encoder, head, weights,
tokenizer, preprocessor, quantization, runtime, device, normalizer, native
mechanism, calibration and OOD artifacts, calibration limits and measured
bounds, dimensions and resource envelope. Reopening the same generation with a
changed field is a context mismatch before state is exposed.

Bootstrap may initialize an empty operation file. Recovery uses
`open_existing` and never initializes a missing history. A missing or empty
sidecar therefore fails closed and remains byte-for-byte unchanged.

## Record model and transaction order

Each bounded frame contains a canonical prepared operation or a completion
marker and is protected by a frame checksum. A prepared operation binds:

- tick identity and complete input semantic digest;
- exact expected and successor journal anchors;
- the numerical sparse tick actually supplied to the deterministic kernel;
- the complete tick, signal, resource and model-runtime result.

The owner transaction order is:

```text
check live host admission and exact input identity
reject scope/sequence/journal capacity/result capacity/witness capacity before model execution
verify the selected model output tuple and compute the pure sparse successor
check live host admission again
sync the prepared operation and exact result
compare-and-append the sparse journal
revalidate the committed checkpoint and result
CAS the independent witness, with exact read-back on uncertain acknowledgement
sync the operation completion marker
check live host admission before current-use delivery
return the stored result
```

Once the prepared record is durable, recovery never invokes the model again.
An exact retry returns the stored result. Reusing a tick identity with a
different input is conflict. Only one prepared successor may exist at a time.

## Recovery matrix

| Durable state | Recovery behavior |
| --- | --- |
| Initialized nonempty journal header and empty operation history/witness | Reopen the enrolled owner before its first tick. A lost empty journal is not initialized during recovery. |
| Completed operation, journal and witness agree | Return the exact stored result on retry. |
| Prepared result exists, journal is still at the predecessor | Commit the stored sparse tick, advance the witness and mark complete. |
| Journal committed but the witness is still at the predecessor or absent on the first operation | Validate the committed checkpoint, advance the witness and mark complete. |
| Witness CAS took effect but its acknowledgement was lost | Read back the exact successor, accept only that value and mark complete. |
| Any unrelated journal, result-store or witness frontier | Reject; never choose a new predecessor or reexecute the model. |

A partial final operation-store frame is truncated and synced on reopen. A
complete corrupt frame, changed header, unknown record shape or checksum
failure rejects the store. Write or sync uncertainty poisons the live handle;
reopen is required before reconciliation.

## Bounds and compatibility

The store accepts at most 4096 operations and 256 KiB per encoded event. These
are source bounds, not a target-host performance claim. The current format is a
V1 sidecar for the existing single-population V1 journal. It does not reinterpret
old journal bytes and it is not a migration certificate for a historical
journal that lacks an operation sidecar. Such a history requires an explicit,
reviewed migration or remains on the predecessor binary.

V2/DecisionCell persistence requires its own versioned operation identity,
parameter-bundle binding and store migration. It may not silently reuse this
V1 header or claim that a digest-only parameter reference was executed.

## Verification

Runtime and store regressions cover complete-result retry after restart,
prepared-result recovery after the result-store sync cut, first journal commit
without a witness, witness-commit acknowledgement loss, complete configuration
drift, forged canonical predecessor, missing-sidecar recovery, partial tails,
writer fencing and segment rollover. These source tests do not replace current
exact-head, synthetic-merge, target-host, physical power-loss or independent
acceptance evidence.

## Admission and publication

`NeuronRuntime::tick_guarded` requires a host-supplied `NeuronAdmissionGuard`.
The guard runs before inference, before durable preparation, and before result
publication. Historical retries also pass current-use checks. A rejected new
request leaves no pending operation and cannot prevent a valid next request or
segment rollover. `tick` remains the explicit mechanism/qualification adapter;
the canonical Agentd product path uses the guarded method.

A durable prepared record is a recovery obligation, not a fresh-use grant.
Revocation/deadline observed after preparation suppresses success delivery but
does not erase committed history or cause model reexecution. `query_result`
reconciles and reads exact historical output by tick identity and input digest;
it is not permission to use a revoked signal. The composing host must supply
real selected-artifact, calibration/OOD, source and revocation evidence. Repeated
checks alone are not an independent trust root or a physical interrupt.

Canonical checkpoint publication requires the complete stored and completed
operation receipt, including its exact tick identity and predecessor. Runtime
recovery checks the stored numerical tick against the native checkpoint input
binding and checks error/saturation/sparsity against the independently replayed
journal receipt. An exact predecessor receipt is carried in memory across V1
successor transitions; no existing on-disk journal byte is reinterpreted.

## Real process cuts

`runtime_process_tests.rs` exits a real child process without destructors at
bootstrap, prepared-result sync, journal commit, witness sync and operation
completion. The parent reopens real stores, verifies the identical retained
output, and verifies that the model-call log contains one call across retries.
This covers process teardown/reopen, not disk-controller power loss, a selected
production model or independent learning efficacy. The existing exhaustive
partial-byte journal and operation-store tests remain enabled.

## Witness capacity before preparation

`AnchorWitnessStore::admit_new_anchor` is an explicit required native contract.
Under the exclusive writer lifetime, it rejects a poisoned/full witness or a
mismatched predecessor before new model execution or durable preparation. The
file witness reuses the same check at CAS. Historical result lookup and completed
retries do not consume new capacity; an existing exact witness successor is still
reconciled without another append. A full witness must not leave a newly committed
journal successor with a permanently incomplete operation. Capacity exhaustion is
an admission failure, not a reason to delete acknowledgement history or silently
raise a configured bound. This adds no new on-disk format or rollover semantics.
