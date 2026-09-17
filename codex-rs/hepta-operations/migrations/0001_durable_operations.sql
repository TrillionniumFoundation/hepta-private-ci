-- Durable kernel.operations lineage v1. The operation row and local outbox row
-- are created in one SQLite transaction. Active rows cannot be deleted; bounded
-- retention first moves terminal identity into operation_tombstones so a pruned
-- operation cannot be resurrected with different semantics.
CREATE TABLE operation_records (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    destination_id TEXT NOT NULL,
    predecessor_operation_id TEXT,
    owner_generation BLOB NOT NULL CHECK (length(owner_generation) = 8),
    authority_epoch BLOB NOT NULL CHECK (length(authority_epoch) = 8),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    state TEXT NOT NULL CHECK (state IN (
        'pending', 'dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined'
    )),
    dispatch_digest BLOB CHECK (dispatch_digest IS NULL OR length(dispatch_digest) = 32),
    terminal_digest BLOB CHECK (terminal_digest IS NULL OR length(terminal_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    PRIMARY KEY (scope_id, operation_id),
    CHECK ((state IN ('applied', 'not_applied', 'quarantined')
            AND terminal_at_ms IS NOT NULL AND terminal_at_ms = updated_at_ms
            AND terminal_digest IS NOT NULL)
        OR (state NOT IN ('applied', 'not_applied', 'quarantined')
            AND terminal_at_ms IS NULL AND terminal_digest IS NULL)),
    CHECK ((state IN ('dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined')
            AND dispatch_digest IS NOT NULL)
        OR (state = 'pending' AND dispatch_digest IS NULL))
) WITHOUT ROWID;

CREATE TABLE cross_owner_outbox (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'leased', 'acknowledged', 'indeterminate', 'settled', 'quarantined'
    )),
    fence INTEGER NOT NULL CHECK (fence >= 0),
    claim_generation BLOB CHECK (claim_generation IS NULL OR length(claim_generation) = 8),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 16),
    worker_id TEXT,
    lease_until_ms INTEGER,
    next_eligible_ms INTEGER NOT NULL CHECK (next_eligible_ms >= 0),
    acknowledgement_digest BLOB CHECK (
        acknowledgement_digest IS NULL OR length(acknowledgement_digest) = 32
    ),
    reason_digest BLOB CHECK (reason_digest IS NULL OR length(reason_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    PRIMARY KEY (scope_id, operation_id, destination_id),
    FOREIGN KEY (scope_id, operation_id)
        REFERENCES operation_records(scope_id, operation_id) ON DELETE CASCADE,
    CHECK ((state = 'leased' AND worker_id IS NOT NULL
            AND lease_until_ms IS NOT NULL AND lease_until_ms > updated_at_ms
            AND claim_generation IS NOT NULL)
        OR (state != 'leased' AND worker_id IS NULL AND lease_until_ms IS NULL)),
    CHECK ((state IN ('settled', 'quarantined') AND terminal_at_ms IS NOT NULL
            AND terminal_at_ms = updated_at_ms)
        OR (state NOT IN ('settled', 'quarantined') AND terminal_at_ms IS NULL)),
    CHECK ((state = 'acknowledged' AND acknowledgement_digest IS NOT NULL)
        OR state != 'acknowledged')
) WITHOUT ROWID;

CREATE INDEX cross_owner_outbox_ready ON cross_owner_outbox
    (state, next_eligible_ms, lease_until_ms, destination_id, scope_id, operation_id);

CREATE TABLE operation_tombstones (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    destination_id TEXT NOT NULL,
    terminal_state TEXT NOT NULL CHECK (terminal_state IN ('applied', 'not_applied', 'quarantined')),
    terminal_digest BLOB NOT NULL CHECK (length(terminal_digest) = 32),
    terminal_at_ms INTEGER NOT NULL CHECK (terminal_at_ms >= 0),
    pruned_at_ms INTEGER NOT NULL CHECK (pruned_at_ms >= terminal_at_ms),
    PRIMARY KEY (scope_id, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER operation_records_identity_immutable BEFORE UPDATE OF
    scope_id, operation_id, payload_digest, destination_id,
    predecessor_operation_id, owner_generation, authority_epoch, created_at_ms
    ON operation_records
BEGIN
    SELECT RAISE(ABORT, 'operation identity is immutable');
END;

CREATE TRIGGER operation_records_terminal_immutable BEFORE UPDATE ON operation_records
WHEN OLD.state IN ('applied', 'not_applied', 'quarantined')
BEGIN
    SELECT RAISE(ABORT, 'terminal operation is immutable');
END;

CREATE TRIGGER operation_records_no_active_delete BEFORE DELETE ON operation_records
WHEN OLD.state NOT IN ('applied', 'not_applied', 'quarantined')
BEGIN
    SELECT RAISE(ABORT, 'active operation cannot be deleted');
END;

CREATE TRIGGER cross_owner_outbox_identity_immutable BEFORE UPDATE OF
    scope_id, operation_id, destination_id, payload_digest, created_at_ms
    ON cross_owner_outbox
BEGIN
    SELECT RAISE(ABORT, 'outbox identity is immutable');
END;

CREATE TRIGGER cross_owner_outbox_active_no_delete BEFORE DELETE ON cross_owner_outbox
WHEN OLD.state NOT IN ('settled', 'quarantined')
BEGIN
    SELECT RAISE(ABORT, 'active outbox row cannot be deleted');
END;

CREATE TRIGGER cross_owner_outbox_fence_monotonic BEFORE UPDATE ON cross_owner_outbox
WHEN NEW.fence <= OLD.fence
    OR NEW.attempts < OLD.attempts
    OR (NEW.attempts != OLD.attempts AND NOT
        (NEW.state = 'leased' AND NEW.attempts = OLD.attempts + 1))
BEGIN
    SELECT RAISE(ABORT, 'invalid outbox ownership transition');
END;
