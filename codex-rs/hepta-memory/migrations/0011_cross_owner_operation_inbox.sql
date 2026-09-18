CREATE TABLE cognitive_cross_owner_operations (
    operation_id TEXT PRIMARY KEY NOT NULL,
    source_owner_id TEXT NOT NULL,
    semantic_sha256 TEXT NOT NULL CHECK (length(semantic_sha256) = 64),
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    payload BLOB NOT NULL CHECK (length(payload) BETWEEN 1 AND 1048576),
    destination_owner_agent_id TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL CHECK (length(receipt_sha256) = 64),
    applied_at_unix_seconds INTEGER NOT NULL CHECK (applied_at_unix_seconds >= 0)
) STRICT;

CREATE INDEX cognitive_cross_owner_operations_source_lookup
    ON cognitive_cross_owner_operations(source_owner_id, operation_id);

CREATE TRIGGER cognitive_cross_owner_operations_no_update
BEFORE UPDATE ON cognitive_cross_owner_operations
BEGIN
    SELECT RAISE(ABORT, 'cross-owner operation receipts are immutable');
END;

CREATE TRIGGER cognitive_cross_owner_operations_no_delete
BEFORE DELETE ON cognitive_cross_owner_operations
BEGIN
    SELECT RAISE(ABORT, 'cross-owner operation receipts are append-only');
END;
