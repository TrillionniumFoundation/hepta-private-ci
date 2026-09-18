-- Destination-owner deduplication table. Product owners may copy this exact
-- table into their own migration lineage and use DestinationDedupeStore with
-- their already-migrated SQLite pool so dedupe and domain mutation share one
-- transaction.
CREATE TABLE destination_operation_dedupe (
    destination TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    outcome_digest BLOB NOT NULL CHECK (length(outcome_digest) = 32),
    applied_at_ms INTEGER NOT NULL CHECK (applied_at_ms >= 0),
    PRIMARY KEY (destination, scope_id, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER destination_operation_dedupe_immutable BEFORE UPDATE
    ON destination_operation_dedupe
BEGIN
    SELECT RAISE(ABORT, 'destination operation dedupe receipts are immutable');
END;

CREATE TRIGGER destination_operation_dedupe_no_delete BEFORE DELETE
    ON destination_operation_dedupe
BEGIN
    SELECT RAISE(ABORT, 'destination operation dedupe receipts cannot be deleted');
END;
