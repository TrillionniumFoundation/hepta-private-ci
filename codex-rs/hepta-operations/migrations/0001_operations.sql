CREATE TABLE operation_ledger (
    operation_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    destination TEXT NOT NULL,
    expected_predecessor_digest BLOB CHECK (length(expected_predecessor_digest) = 32),
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    owner_generation BLOB NOT NULL CHECK (length(owner_generation) = 8),
    authority_epoch BLOB NOT NULL CHECK (length(authority_epoch) = 8),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    state TEXT NOT NULL CHECK (state IN (
        'pending', 'dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined'
    )),
    writer_fence INTEGER NOT NULL CHECK (writer_fence >= 0),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 16),
    dispatch_digest BLOB CHECK (length(dispatch_digest) = 32),
    acknowledgement_digest BLOB CHECK (length(acknowledgement_digest) = 32),
    indeterminate_reason_digest BLOB CHECK (length(indeterminate_reason_digest) = 32),
    terminal_digest BLOB CHECK (length(terminal_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    UNIQUE (semantic_digest),
    CHECK ((state IN ('applied','not_applied','quarantined') AND terminal_at_ms IS NOT NULL AND terminal_digest IS NOT NULL)
        OR (state NOT IN ('applied','not_applied','quarantined') AND terminal_at_ms IS NULL AND terminal_digest IS NULL)),
    CHECK ((state = 'pending' AND dispatch_digest IS NULL AND indeterminate_reason_digest IS NULL)
        OR (state = 'dispatched' AND dispatch_digest IS NOT NULL AND indeterminate_reason_digest IS NULL)
        OR (state = 'indeterminate' AND dispatch_digest IS NOT NULL AND indeterminate_reason_digest IS NOT NULL)
        OR (state IN ('applied','not_applied') AND dispatch_digest IS NOT NULL)
        OR state = 'quarantined')
);

CREATE TABLE cross_owner_outbox (
    operation_id TEXT PRIMARY KEY REFERENCES operation_ledger(operation_id) ON DELETE RESTRICT,
    destination TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    payload BLOB NOT NULL CHECK (length(payload) BETWEEN 1 AND 1048576),
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'leased', 'dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined'
    )),
    fence INTEGER NOT NULL CHECK (fence >= 0),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 16),
    worker_id TEXT,
    lease_until_ms INTEGER,
    available_at_ms INTEGER NOT NULL CHECK (available_at_ms >= 0),
    acknowledgement_digest BLOB CHECK (length(acknowledgement_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    CHECK ((state = 'leased' AND worker_id IS NOT NULL AND lease_until_ms IS NOT NULL AND lease_until_ms > updated_at_ms)
        OR (state != 'leased' AND worker_id IS NULL AND lease_until_ms IS NULL)),
    CHECK ((state IN ('applied','not_applied','quarantined') AND terminal_at_ms IS NOT NULL)
        OR (state NOT IN ('applied','not_applied','quarantined') AND terminal_at_ms IS NULL))
);

CREATE INDEX cross_owner_outbox_pending
    ON cross_owner_outbox (destination, state, available_at_ms, lease_until_ms, operation_id);
CREATE INDEX cross_owner_outbox_terminal
    ON cross_owner_outbox (state, terminal_at_ms, operation_id);

CREATE TRIGGER operation_ledger_identity_immutable BEFORE UPDATE ON operation_ledger
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.owner_id IS NOT NEW.owner_id
  OR OLD.scope_digest IS NOT NEW.scope_digest
  OR OLD.payload_digest IS NOT NEW.payload_digest
  OR OLD.destination IS NOT NEW.destination
  OR OLD.expected_predecessor_digest IS NOT NEW.expected_predecessor_digest
  OR OLD.semantic_digest IS NOT NEW.semantic_digest
BEGIN
    SELECT RAISE(ABORT, 'operation semantic identity is immutable');
END;

CREATE TRIGGER operation_ledger_active_no_delete BEFORE DELETE ON operation_ledger
WHEN OLD.state NOT IN ('applied','not_applied','quarantined')
BEGIN
    SELECT RAISE(ABORT, 'active operations cannot be deleted');
END;

CREATE TRIGGER cross_owner_outbox_identity_immutable BEFORE UPDATE ON cross_owner_outbox
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.destination IS NOT NEW.destination
  OR OLD.semantic_digest IS NOT NEW.semantic_digest
  OR OLD.payload_digest IS NOT NEW.payload_digest
  OR OLD.payload IS NOT NEW.payload
BEGIN
    SELECT RAISE(ABORT, 'outbox semantic identity is immutable');
END;

CREATE TRIGGER cross_owner_outbox_active_no_delete BEFORE DELETE ON cross_owner_outbox
WHEN OLD.state NOT IN ('applied','not_applied','quarantined')
BEGIN
    SELECT RAISE(ABORT, 'active operation outbox rows cannot be deleted');
END;
