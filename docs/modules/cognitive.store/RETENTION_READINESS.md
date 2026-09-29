# Ancestry-safe retention checkpoint readiness

## Purpose and boundary

`retention_readiness.py` verifies the evidence required before a destructive hot-generation pruning implementation may be considered for publication. It does not open SQLite, choose eligible rows, delete history, upload a segment, publish an active pointer, remove a predecessor generation or prove physical erasure.

This distinction is intentional. The current v1 exact-cut digest covers complete logical history. A full-history encrypted cold archive can preserve that cut, but deleting hot rows requires a new checkpoint-aware schema and reader/recovery contract. Readiness evidence cannot silently reinterpret the existing cut.

## Signed checkpoint plan

The coordinator signs `hepta.cognitive.retention-checkpoint-plan.v3`. The plan binds:

- canonical Agent, exact source commit/tree and writer generation;
- schema and exact current-cut digests;
- complete current head-set digest;
- tombstone, source, fact and KG frontiers;
- retention policy, legal/hold state and unresolved-operation inventory digests;
- predecessor and private successor image identities;
- a bounded successor image size;
- an independent rebuild owner;
- an ordered list of immutable encrypted segments plus the canonical segment-set digest, count, total row count and first/last manifest identities;
- a bounded validity interval.

Each segment binds its storage owner, ordinal, declared key range, row count, plaintext/ciphertext/manifest digests and the previous segment manifest. The first segment has no predecessor; every later segment must continue the exact manifest chain. A one-row segment must bind one exact key; a multi-row range must be increasing; adjacent segment ranges must be strictly ordered and disjoint.

Plaintext, ciphertext and manifest identities must be pairwise distinct inside each segment **and globally unique across the entire signed segment inventory**. A later segment therefore cannot reuse an earlier segment's plaintext digest while presenting new ciphertext and manifest identities. Duplicate segment IDs and any cross-segment plaintext, ciphertext or manifest identity are rejected. The signed aggregate must exactly equal the canonical segment inventory, so a rebuild receipt cannot silently refer to another count, row total or chain endpoint. V1 and V2 artifacts are not silently reinterpreted under these stronger owner-attested range and content-identity semantics.

## Segment and rebuild receipts

Each segment owner signs `hepta.cognitive.retention-segment-receipt.v3`, explicitly attesting the segment's first and last key, ordinal, row count, plaintext digest, ciphertext digest, manifest digest and predecessor link. The coordinator's plan therefore cannot claim a range that the storage owner never signed. Only a completed `immutable_encrypted_segment` observation satisfies the segment obligation. Missing, pending, indeterminate or failed publication remains incomplete.

The rebuild owner signs `hepta.cognitive.retention-rebuild-receipt.v3`. A completed receipt must prove:

- the exact source, owner, generation, schema, image identities and frontiers from the plan;
- identical before and after semantic cuts;
- identical current head set and tombstone frontier;
- successful segment-resolution, SQLite integrity, foreign-key, projection and pending-operation checks;
- a distinct private successor image;
- `published=false`.

The last condition prevents a readiness verifier from laundering an unapproved pointer update into evidence. Publication must still use the existing signed bootstrap, live authority final-use check and active-generation reconciliation path.

## Report semantics

A complete report is named `retention_ready`, not `pruned`. It always returns:

```text
successor_published = false
hot_history_pruned = false
predecessor_erased = false
physical_erasure_proved = false
activation_authorized = false
```

Real hot pruning still requires the checkpoint-aware schema/read migration, deterministic rebuild implementation, native restore equivalence, selected-host fault qualification and independently governed publication. Later removal of retired generations, backups, exports or trained parameters remains a separate per-owner lifecycle operation.

## Usage

```sh
python3 tools/cognitive-store-host-bootstrap/retention_readiness.py \
  --plan /trusted/retention-checkpoint-plan.json \
  --receipts /trusted/retention-owner-receipts.json \
  --trusted-owners /trusted/current-owner-trust.json \
  --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST" \
  --expected-trust-sha256 "$CURRENT_TRUST_DIGEST"
```

Exit code 0 authenticates a complete readiness evidence set. Exit code 2 means at least one segment or rebuild obligation is incomplete. Neither result authorizes data deletion or generation publication.

The rebuild owner must be distinct from every segment storage owner. A completed rebuild observation must be no earlier than every supplied segment publication receipt, preventing a pre-segment rebuild assertion from being combined with later archive receipts.
