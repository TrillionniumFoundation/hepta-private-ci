# Acknowledged-history recovery anchor

This bounded NEU-2 hardening extends `SparseJournal`; it is not a new journal,
wire protocol, model, or production caller. The on-disk HPTNSJ01 format and the
existing successful-commit byte vectors are unchanged.

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
A valid later complete frame is preserved and synced before exposure, allowing
reconciliation of a write whose acknowledgement was lost. An earlier anchor is
a minimum retained-history requirement, not an instruction to roll back later
valid commits. Corruption after the anchor still rejects the entire open.

`InvalidAnchor`, `AcknowledgedHistoryMissing`, and `AnchorMismatch` are separate
errors. These errors do not initialize, truncate, rewrite, or silently choose a
new predecessor. The handle closes normally on rejection. Normal clock, scope,
configuration, replay, quota, and cooperating-writer fencing checks remain intact.

## Host integration boundary

The legacy `open` method remains available for bootstrap and explicitly
unanchored qualification use. It is not an anti-rollback API. A host that has
acknowledged history must call the anchored method and must never retry a failed
anchored open through the unanchored method. This patch does not install such a
host, authenticate the witness, or create an external witness store.

The host transaction order is: durably commit the journal, durably retain its
acknowledgement witness, then acknowledge externally. If witness publication is
uncertain, reconcile the already committed tick before retrying. An anchor cannot
protect acknowledgements that the host failed to retain. Concurrent witness
updates, segment rotation, deletion/unlearning, backup erasure, physical power
loss, and target latency require separate implementation and qualification.

## Regression coverage

Nine new tests cover exact anchored replay, loss of a whole acknowledged frame,
empty replacement, every partial acknowledged-frame boundary, anchor mismatch
before tail repair, preservation of later complete frames, rehashed alternate
history, malformed anchors, and corruption after a matching anchor. Missing or
mismatched history is checked to leave the file bytes untouched. Existing tests
and golden digests are retained. Test source is not proof of execution; exact
candidate compilation, tests, strict lint and both source/merge checks are required.
