CREATE TABLE operations_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at_ms INTEGER NOT NULL
);

INSERT INTO operations_meta(singleton, schema_version, created_at_ms)
VALUES (1, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);

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

CREATE TABLE operation_ledger (
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    predecessor_digest BLOB CHECK (predecessor_digest IS NULL OR length(predecessor_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    destination TEXT NOT NULL,
    owner_generation BLOB NOT NULL CHECK (length(owner_generation) = 8),
    authority_epoch BLOB NOT NULL CHECK (length(authority_epoch) = 8),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    state TEXT NOT NULL CHECK (state IN ('pending', 'dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined')),
    dispatch_digest BLOB CHECK (dispatch_digest IS NULL OR length(dispatch_digest) = 32),
    indeterminate_digest BLOB CHECK (indeterminate_digest IS NULL OR length(indeterminate_digest) = 32),
    terminal_evidence_digest BLOB CHECK (terminal_evidence_digest IS NULL OR length(terminal_evidence_digest) = 32),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    terminal_at_ms INTEGER,
    PRIMARY KEY(scope, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER operation_ledger_identity_immutable
BEFORE UPDATE OF scope, operation_id, semantic_digest, predecessor_digest, payload_digest, destination, created_at_ms
ON operation_ledger
BEGIN
    SELECT RAISE(ABORT, 'operation identity is immutable');
END;

CREATE INDEX operation_ledger_state_updated
ON operation_ledger(state, updated_at_ms, scope, operation_id);

CREATE TABLE cross_owner_outbox (
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'acknowledged', 'indeterminate', 'settled', 'quarantined')),
    fence INTEGER NOT NULL DEFAULT 0 CHECK (fence >= 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at_ms INTEGER NOT NULL,
    worker_id TEXT,
    lease_until_ms INTEGER,
    claim_generation BLOB CHECK (claim_generation IS NULL OR length(claim_generation) = 8),
    acknowledgement_digest BLOB CHECK (acknowledgement_digest IS NULL OR length(acknowledgement_digest) = 32),
    last_error_digest BLOB CHECK (last_error_digest IS NULL OR length(last_error_digest) = 32),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    terminal_at_ms INTEGER,
    PRIMARY KEY(scope, operation_id),
    FOREIGN KEY(scope, operation_id) REFERENCES operation_ledger(scope, operation_id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TRIGGER cross_owner_outbox_identity_immutable
BEFORE UPDATE OF scope, operation_id, destination, semantic_digest, created_at_ms
ON cross_owner_outbox
BEGIN
    SELECT RAISE(ABORT, 'outbox identity is immutable');
END;

CREATE UNIQUE INDEX cross_owner_outbox_destination_operation
ON cross_owner_outbox(destination, operation_id);

CREATE INDEX cross_owner_outbox_ready
ON cross_owner_outbox(state, available_at_ms, lease_until_ms, destination, operation_id);

CREATE TABLE destination_operation_dedup (
    destination TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'not_applied', 'quarantined')),
    evidence_digest BLOB NOT NULL CHECK (length(evidence_digest) = 32),
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY(destination, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER destination_operation_dedup_no_update
BEFORE UPDATE ON destination_operation_dedup
BEGIN
    SELECT RAISE(ABORT, 'destination outcome is immutable');
END;

CREATE INDEX destination_operation_dedup_recorded
ON destination_operation_dedup(recorded_at_ms, destination, operation_id);
