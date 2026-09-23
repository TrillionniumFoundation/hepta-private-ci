-- Destination-owned half of kernel.operations cross-owner mutation.
-- The immutable dedupe receipt is committed in the same transaction as the
-- automation task row so exact replay cannot create a second task effect.
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

-- automation_meta is intentionally immutable at runtime. A schema migration is
-- the one reviewed place allowed to move its version.
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1 AND schema_version = 3;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
