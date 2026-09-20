# Acknowledged-history recovery anchor

This bounded NEU-2 hardening composes `SparseJournal`, the canonical operation
result journal and an independent witness. The HPTNSJ01 sparse format remains
unchanged; HPTNOP01 supplies the terminal-result evidence that a checkpoint digest
alone cannot reconstruct.

## Failure being closed

Checksums verify the bytes still present. They cannot prove that a complete,
previously acknowledged suffix has not disappeared. An internally valid prefix
or an empty replacement can therefore pass unanchored recovery. This is an
information boundary, not a checksum algorithm defect.

`SparseJournal::open_anchored` requires a `JournalAnchor` with a positive sequence
and its checkpoint digest. The host must retain this witness separately from the
journal, bind it to the same scope and generation, authenticate it, and enforce
its freshness and revocation. Reading the anchor back from the suspect journal
or accepting an arbitrary model-supplied digest supplies no rollback protection.

## Algorithm and transaction ordering

The existing open path and the anchored path share one parser and replay engine.
An anchor is valid only for sequence 1 through the declared segment quota and a
nonzero checkpoint digest. Before any file initialization or repair, anchored
recovery requires the acknowledged sequence to be present. It then validates
all complete frames and reconstructs their checkpoint/receipt chain. The exact
checkpoint at the anchor sequence must match the external witness.

Only after that comparison may a later incomplete frame be truncated and synced.
A valid later complete sparse frame is preserved and synced before exposure. The
canonical owner first reconciles every durable operation record against the exact
checkpoint sequence, requires every exposed sparse successor to have one matching
committed operation record, and revalidates that operation's complete lineage.
Only then may it advance the independent witness one sequence at a time. This also
covers the first-commit cut where sparse state and a committed operation exist but
the witness is still empty. Failure to reconcile the operation or witness fails
open; it cannot create another journal commit on top of an untracked or stale
anchor. An earlier anchor is a minimum retained-history requirement, not an
instruction to roll back later valid commits. Corruption after the anchor still
rejects the entire open.

`InvalidAnchor`, `AcknowledgedHistoryMissing`, and `AnchorMismatch` are separate
errors. These errors do not initialize, truncate, rewrite, or silently choose a
new predecessor. The handle closes normally on rejection. Normal clock, scope,
configuration, replay, quota, and cooperating-writer fencing checks remain intact.

## Host integration boundary

The legacy `open` method remains available for bootstrap and explicitly
unanchored qualification use. It is not an anti-rollback API. A host that has
acknowledged history must call the anchored method and must never retry a failed
anchored open through the unanchored method. `NeuronRuntimeHost` and the bounded
`FileRecoveryWitness` implement this local owner ordering. The file witness uses
two independently checksummed alternating slots, so an interrupted overwrite can
fall back to the previous complete anchor instead of destroying both old and new
state. Reopen selects the highest valid adjacent sequence and ignores one torn
slot; if neither slot validates, recovery fails closed. The caller still owns
authentication, directory protection, freshness policy and external scope.

The canonical host transaction order is: durably prepare the exact operation
result, durably commit the sparse checkpoint, durably mark the operation committed,
revalidate current lineage, durably retain the acknowledgement witness, then
acknowledge externally. If terminal or witness publication is uncertain, recovery
reconciles the original operation by operation ID/request digest/checkpoint before
any retry; it never re-executes a committed model call merely because the reply was
lost. An anchor cannot protect acknowledgements that the host failed to retain. Continuation rotation
and live-lineage rebuild are implemented source mechanisms; backup erasure,
physical power loss, target latency, multi-host witness coordination and empirical
unlearning qualification remain separate evidence or integration work.

## Regression coverage

Nine new tests cover exact anchored replay, loss of a whole acknowledged frame,
empty replacement, every partial acknowledged-frame boundary, anchor mismatch
before tail repair, preservation of later complete frames, rehashed alternate
history, malformed anchors, and corruption after a matching anchor. Missing or
mismatched history is checked to leave the file bytes untouched. Existing tests
and golden digests are retained. Test source is not proof of execution; exact
candidate compilation, tests, strict lint and both source/merge checks are required.
