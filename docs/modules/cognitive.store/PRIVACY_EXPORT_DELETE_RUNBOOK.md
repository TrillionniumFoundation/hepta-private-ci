# Privacy, export and delete runbook

This runbook is an operator procedure. It does not turn a logical tombstone into a claim of physical erasure or model unlearning.

## Preconditions

1. Authenticate the requester and exact Agent/workspace scope.
2. Freeze a current signed recovery witness and record source commit/tree, schema digest and active-generation identity.
3. Stop or fence new writes for the affected scope when a consistent export/delete cut is required.
4. Enumerate legal holds, retention policy and downstream data owners.
5. Allocate a stable request id; all receipts and retries use this id.

## Export

1. Open an authorized read-only cut.
2. Export source revisions, Memory revisions, citations, lifecycle, validity intervals and fact sets in canonical key order.
3. Include current heads and tombstones explicitly; do not export hidden payload after policy redaction.
4. Emit a manifest binding owner/scope, schema, cut digest, counts, byte bounds, every object digest and export policy.
5. Encrypt to the requester-controlled destination; the store receipt grants no transfer authority.
6. Revalidate the cut before publication. Mutation during export either restarts from a new cut or yields an explicit stale export.

## Logical delete

1. Resolve each target stable Memory id and current revision.
2. Append a cited tombstone through `AgentdProductionWriterHost` and the sealed mutation capability.
3. Verify the terminal production receipt and exact successor cut.
4. Rebuild or invalidate current projections, FTS results and caches.
5. Record that logical visibility is closed. Do not mark physical erasure complete.

## Physical erasure campaign

Create one disposition per owner/storage class:

- active SQLite generation;
- retired/recovery generations;
- WAL, rollback journal and temporary recovery candidates;
- local and remote backups;
- cold archive segments/checkpoints;
- FTS/projection/cache copies;
- operation logs containing payload rather than digest-only metadata;
- exported datasets and learning snapshots;
- derived artifacts and serving caches;
- external destinations previously authorized to receive a copy.

Allowed dispositions are `not_applicable`, `pending`, `erased`, `retained_under_hold`, `revoked`, `unreachable` and `indeterminate`. Overall completion requires every applicable owner to be terminal; `unreachable` and `indeterminate` are not success.

Database-page erasure requires rebuilding a fresh generation without prohibited payload, checkpointing it, proving the current semantic cut, publishing it atomically and retiring predecessor files according to host storage policy. Direct row deletion in the active generation is forbidden.

## Derived learning state

A Memory tombstone triggers owner notifications and source-support revocation. It does not prove that optimizer state, model parameters or third-party models forgot the payload. Use the learning/artifact owners' unlearning or rebuild procedures and retain their receipts. Where unlearning cannot be established, report that limitation explicitly.

## Closeout receipt

The closeout binds request id, requester authority, scope, pre/post cut digests, tombstone receipts, owner dispositions, backup generations, artifact revocations, exceptions, holds, timestamps and independent reviewer identity. Sensitive payload is represented by digest unless the requester export requires content.

## Failure and rollback

- Before tombstone commit: retry only after re-reading the current head.
- After possible commit with lost response: reconcile by stable operation/receipt identity; never issue a blind second delete.
- During generation rebuild: keep the current generation active.
- After pointer-rename ambiguity: classify `Indeterminate`, preserve both generations and perform trusted recovery reconciliation.
