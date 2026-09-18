-- Destination-owned half of kernel.operations cross-owner mutation.
-- The automation task row and this immutable receipt are committed in the same
-- owner transaction, so exact delivery replay cannot create a second task.
CREATE TABLE destination_operation_dedupe (
    destination TEXT NOT NULL,
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    evidence_digest BLOB NOT NULL CHECK (length(evidence_digest) = 32),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (destination, scope, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER destination_operation_dedupe_no_update
BEFORE UPDATE ON destination_operation_dedupe
BEGIN
    SELECT RAISE(ABORT, 'destination operation dedupe receipts are immutable');
END;

CREATE TRIGGER destination_operation_dedupe_no_delete
BEFORE DELETE ON destination_operation_dedupe
BEGIN
    SELECT RAISE(ABORT, 'destination operation dedupe receipts are permanent');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1 AND schema_version = 3;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
