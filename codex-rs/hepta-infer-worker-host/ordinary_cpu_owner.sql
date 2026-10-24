-- Install in the destination owner's existing migration lineage, not a source ledger.
CREATE TABLE ordinary_cpu_entries (
    slot INTEGER PRIMARY KEY CHECK (slot >= 0 AND slot < 16),
    operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id) BETWEEN 1 AND 128),
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    terminal_receipt TEXT CHECK (length(terminal_receipt) <= 128)
);
CREATE TRIGGER ordinary_cpu_entries_no_delete BEFORE DELETE ON ordinary_cpu_entries
BEGIN SELECT RAISE(ABORT, 'ordinary CPU owner slots cannot be discarded'); END;
CREATE TRIGGER ordinary_cpu_entries_no_reinsert BEFORE INSERT ON ordinary_cpu_entries
WHEN EXISTS (SELECT 1 FROM ordinary_cpu_entries
    WHERE slot = NEW.slot OR operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'ordinary CPU owner slots cannot be replaced'); END;
CREATE TRIGGER ordinary_cpu_entries_immutable BEFORE UPDATE ON ordinary_cpu_entries
WHEN OLD.slot != NEW.slot OR OLD.operation_id != NEW.operation_id
    OR OLD.semantic_digest != NEW.semantic_digest OR OLD.terminal_receipt IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'ordinary CPU entry identity and terminality are immutable'); END;

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
