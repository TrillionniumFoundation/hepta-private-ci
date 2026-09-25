# Durable sparse checkpoint journal

This NEU-2 sub-slice builds on the Q24 kernel, not a competing implementation.
`SparseJournal` is an opt-in host adapter; `sparse_tick` stays pure. It implements
persistence and crash/reopen for one bounded run/generation segment, not full
NEU-2 completion, calibrated intelligence or production activation.

## Ownership and admission

The host passes a newly opened read/write `File`, frozen `SparseConfig`,
`JournalScope` and a 1..1024-record quota. No pathname is accepted or opened.
The host verifies consent, scope, revocation, file/directory ownership and
filesystem suitability. Do not pass cloned/inherited handles already locked
elsewhere. `File::try_lock` fences cooperating independent writers; it is
advisory, not a hostile-writer sandbox. Only the neuron checkpoint owner writes
this journal. New-file directory synchronization remains the host's obligation.

## Persistent format and transaction

A 136-byte versioned header binds config, principal/run scope, objective and
checksum. Each frame is canonical tick inputs (176+16*d bytes), predecessor and
successor checkpoint digests (64 bytes), signal semantics digest (32 bytes) and
checksum (32 bytes): 304+16*d bytes total. All numbers are big-endian; no untrusted
record length is allocated. The receipt and checkpoint are reconstructed together
by the frozen deterministic kernel, then compared with the stored output digests.

`commit(expected_predecessor, tick)` validates before writing and uses exact
compare-and-append. It returns success and publishes state only after `sync_data`.
An equal retry returns the exact original receipt without another write, even
after later ticks; changed content or predecessor conflicts. Missing sequences
and clock regression reject. No last-write-wins or success-from-queue behavior.

Recovery validates all complete frames before truncating and syncing an
incomplete final frame. A complete bad frame, damaged header, unknown version or
wrong config/generation/scope rejects without repairing history. Recovery also
syncs a valid complete suffix before returning: an earlier sync may have failed
after writing a full frame. Any write/sync uncertainty returns indeterminate,
poisons the handle and requires reopen/reconciliation rather than a blind retry.

## Complete operation/result sidecar

The sparse journal intentionally does not contain the complete model/runtime and
calibration result. `NeuronRuntime` therefore pairs it with the separately locked
`HPTNOP01` operation store described in
[OPERATION_STORE.md](OPERATION_STORE.md). The sidecar header freezes the complete
runtime configuration; a prepared frame stores the exact successor operation and
result before this journal is advanced. A completion frame is appended only after
the journal and independent witness agree. Recovery requires the existing
sidecar and never creates one beside an already committed journal.

This separation preserves the fixed V1 journal vectors while closing exact-result
retry and acknowledgement-loss recovery. It is not permission to fall back to an
unanchored journal when operation history is missing.

## Bounds, migration and rollback

At most 1024 ticks per segment: below 4.6 MB at d=256, plus one incomplete tail.
Replay and receipt-cache memory are quota-bounded. Bounded successor segments
preserve the exact predecessor checkpoint and global sequence; recovery walks the
registered chain and rejects a missing acknowledged segment. Compaction is not
implemented. This synced disk path has no real-time latency claim. Configuration,
selected model weights and topology remain immutable throughout one generation,
and the operation-store header rejects same-generation configuration drift.

The host must revoke/rebuild deleted-data-derived state before reopening it. The V1 journal remains deliberately tied to the single-population/same-width `SparseConfig` replay format. `PopulationSparseConfigV2` is a different mechanism generation and may not be written into this V1 format; durable V2 use requires an explicitly versioned store/migration.
Encryption and backup deletion remain separate work. Canonical Neuron JSON protocol adapters, an independently synced file-backed acknowledgement witness, and exact inference-control feature-receipt binding are implemented on the closure line; authenticated selected-artifact/current-owner distribution and daemon activation remain separate composition/evidence work. Process-exit
tests do not certify physical power-loss behavior or target-hardware p99 timing.
Downgrade leaves this new journal inert; never silently choose a stale checkpoint.

## Executable verification

The existing read-only neuron workflow runs locked all-target compilation,
repository `just test`, strict Clippy, formatting and clean-source checks at exact
source and actual-base synthetic merge. Fourteen new entries cover thirteen
scenarios plus a child helper: real reopen, retry, stale CAS, writer fencing,
every final-frame cut point, corruption, rehashed invalid lineage, context drift,
quota, poisoned writes, unacknowledged full frames and process exit without Rust
destructors. The helper is invoked by its parent; its standalone empty entry is
not a separate crash experiment. The first committed file also matches an
independent integer/SHA256 oracle: 520 bytes, checkpoint
`c38b12275a0b6e93855931c7da4d3af3c79ba0d5c8dc74151a3c53210b6677b3`, file digest
`a4f3f20a33961d665b9aedd9c154e32163bf45d46de15cb64404929e611a3b44`.
Execution results belong in exact-candidate evidence, not cached capability flags.

## Normal owner-drop lock lifetime

Normal destruction explicitly unlocks the owned file before closing its handle.
On Linux a temporarily duplicated or inherited open description can otherwise
retain the lock after the owner closes, including during concurrent process
creation. A regression retains such a duplicate, proves another writer is
blocked while the owner lives, drops the owner, and verifies immediate recovery
without discarding the duplicate first. Dropping the old duplicate must not
release a newly acquired independent writer lock.

The duplicate exists only inside the regression fixture. No public handle is
exposed, and the host prohibition on shared writers or independently closing
inherited handles is unchanged. Unlock during Drop is best effort; errors are
not represented as successful commits, and normal file closure remains the
fallback. Existing commit synchronization and poison/recovery behavior remain
unchanged. Process death still requires OS handle closure and does not run Drop;
this is not a physical power-loss or hostile-writer guarantee.
