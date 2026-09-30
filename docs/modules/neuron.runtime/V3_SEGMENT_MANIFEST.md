# Neuron Runtime V3 segment-manifest design

This document specifies a future, separately versioned storage profile for
lossless rollover and compaction. It does not change `HPTNGS02`, `HPTNGI02`, V2
witness bytes or any current operation meaning. V2 remains authoritative until a
same-candidate migration and rollback qualification explicitly selects V3.

## 1. Goals

V3 may reduce long-running file growth and payload duplication while preserving:

- every successful result and exact operation identity;
- every failure tombstone and its terminal reason;
- reservation and dispatch history, including unknown outcomes;
- full receipt/checkpoint interpretation;
- provider receipt identity and query-only recovery semantics;
- witness outbox, acknowledgement and anti-rollback lineage;
- retained historical-generation queries;
- deletion and revocation non-resurrection evidence.

Capacity recovery must never depend on deleting history, resetting generation,
reusing an operation key or interpreting V2 bytes under a new schema.

## 2. Formats and ownership

Proposed identifiers:

```text
HPTNGM03  segment manifest
HPTNGS03  immutable generation segments
HPTNGI03  immutable operation-index segments
HPTNGW03  witness-lineage segments
```

One owner publishes a manifest only after all referenced segments are complete,
synced and content-addressed. Segments are immutable. A replacement manifest may
add or supersede segments, but cannot mutate a referenced segment in place.

The manifest binds:

- schema and format versions;
- subject/objective/body/model/configuration identities;
- generation and predecessor-manifest digest;
- ordered segment descriptors;
- operation, success, failure, reservation and dispatch frontiers;
- checkpoint and witness frontiers;
- source V2 store/index/witness digests for a migration manifest;
- migration tool and source binary digests;
- canonical manifest digest.

## 3. Segment descriptor

Every descriptor contains:

```text
segment_id
segment_kind
first_sequence
last_sequence
record_count
logical_bytes
physical_bytes
content_sha256
format_version
immutable = true
```

Allowed kinds are:

```text
operation_history
full_receipt_payloads
checkpoint_payloads
failure_tombstones
dispatch_history
runtime_index
witness_lineage
```

Sequence intervals for the same kind must be ordered and non-overlapping. Empty
segments are forbidden. Content hashes cover the exact on-disk bytes.

## 4. Lossless migration invariants

A V2-to-V3 migration is valid only when independent replay proves all of the
following:

1. every V2 operation key occurs exactly once in V3;
2. successful operations decode to byte-identical full receipts and checkpoints;
3. failed operations preserve their terminal failure and cannot be resurrected;
4. reserved and dispatched operations retain their recovery classification;
5. an unknown provider outcome remains unknown and cannot become `NotStarted`;
6. witness-pending and witness-acknowledged states preserve exact lineage;
7. current checkpoint and operation frontiers are identical;
8. historical queries return the same status and result bytes;
9. deletion/revocation rebuild does not reintroduce removed lineage;
10. the source V2 files remain read-only and retained through acceptance.

The migration never writes through the live V2 owner. The generation is first
quiesced, drained, reconciled and sealed. V3 output is built in a distinct empty
namespace and selected only after validation.

## 5. Crash consistency

Qualification must terminate the migration process after each of these cuts:

```text
segment_create
segment_write
segment_sync
segment_path_identity_check
manifest_temp_write
manifest_temp_sync
manifest_replace
manifest_parent_sync
manifest_readback
selection_pointer_publish
```

After every cut, fresh-process recovery must choose either the complete prior V2
profile or one complete V3 manifest. It must never expose a mixed profile, accept
an unreferenced partial segment or delete the predecessor evidence.

## 6. Rollback and compatibility

V3 readers must retain a read-only V2 decoder for the declared compatibility
window. Rollback is allowed only before V3 has accepted a new operation and while
the complete V2 source remains sealed and retained. Once V3 records any
reservation, dispatch, failure or result, returning to V2 is a new migration, not
a pointer reversal.

Old binaries fail closed on V3 identifiers. No V2 header, event kind or checksum
scope is redefined. A V3 manifest may reference content-addressed payloads, but
historical receipt meaning remains byte-stable.

## 7. Payload sharing

A future implementation may represent large immutable checkpoint/full-receipt
payloads through content-addressed blobs or shared immutable memory. Acceptance
requires:

- one canonical payload digest and length;
- reference-count-independent recovery;
- no dangling reference after crash or compaction;
- exact historical result bytes;
- bounded garbage collection driven only by complete retained manifests;
- V2-to-V3 and V3 read-only compatibility tests.

Using `Arc<[u8]>` in memory alone is not a storage migration and does not authorize
changing persisted bytes.

## 8. Required evidence before activation

The selected V3 candidate must retain:

- exact source/base/tested-tree and binary digests;
- deterministic migration output from repeated runs;
- V2/V3 cross-version replay and historical-query parity;
- all crash-cut results;
- ENOSPC, EIO, sync uncertainty and namespace-replacement tests;
- long-horizon growth and bounded-open-time measurements;
- backup/restore with success, failure, dispatch and witness history;
- independent security and operator review.

Until those receipts exist, generation handoff and backpressure remain the only
qualified V2 capacity policy. `productionActivation` and `release` remain false.
