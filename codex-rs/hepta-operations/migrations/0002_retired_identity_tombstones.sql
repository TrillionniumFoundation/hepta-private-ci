-- Preserve retired source and destination semantic identities so bounded
-- terminal-row pruning cannot resurrect a previously completed effect.
CREATE TABLE operation_tombstones (
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    predecessor_digest BLOB CHECK (predecessor_digest IS NULL OR length(predecessor_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    destination TEXT NOT NULL,
    terminal_state TEXT NOT NULL CHECK (terminal_state IN ('applied', 'not_applied', 'quarantined')),
    terminal_evidence_digest BLOB NOT NULL CHECK (length(terminal_evidence_digest) = 32),
    retired_at_ms INTEGER NOT NULL,
    PRIMARY KEY(scope, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER operation_tombstones_no_update
BEFORE UPDATE ON operation_tombstones
BEGIN
    SELECT RAISE(ABORT, 'operation tombstones are immutable');
END;

CREATE TRIGGER operation_tombstones_no_delete
BEFORE DELETE ON operation_tombstones
BEGIN
    SELECT RAISE(ABORT, 'operation tombstones are permanent');
END;

CREATE TABLE destination_operation_tombstones (
    destination TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'not_applied', 'quarantined')),
    evidence_digest BLOB NOT NULL CHECK (length(evidence_digest) = 32),
    recorded_at_ms INTEGER NOT NULL,
    retired_at_ms INTEGER NOT NULL,
    PRIMARY KEY(destination, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER destination_operation_tombstones_no_update
BEFORE UPDATE ON destination_operation_tombstones
BEGIN
    SELECT RAISE(ABORT, 'destination operation tombstones are immutable');
END;

CREATE TRIGGER destination_operation_tombstones_no_delete
BEFORE DELETE ON destination_operation_tombstones
BEGIN
    SELECT RAISE(ABORT, 'destination operation tombstones are permanent');
END;

DROP TRIGGER operations_meta_no_update;
DROP TRIGGER operations_meta_no_delete;

CREATE TABLE operations_meta_v2 (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 2),
    created_at_ms INTEGER NOT NULL
);

INSERT INTO operations_meta_v2(singleton, schema_version, created_at_ms)
SELECT singleton, 2, created_at_ms
FROM operations_meta
WHERE singleton = 1 AND schema_version = 1;

DROP TABLE operations_meta;
ALTER TABLE operations_meta_v2 RENAME TO operations_meta;

CREATE TRIGGER operations_meta_no_update
BEFORE UPDATE ON operations_meta
BEGIN
    SELECT RAISE(ABORT, 'operations_meta is immutable');
END;

CREATE TRIGGER operations_meta_no_delete
BEFORE DELETE ON operations_meta
BEGIN
    SELECT RAISE(ABORT, 'operations_meta is immutable');
END;
