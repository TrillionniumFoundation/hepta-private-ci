-- Durable source-of-truth for kernel.operations. The operation row and its
-- cross-owner outbox row are created in one BEGIN IMMEDIATE transaction.
CREATE TABLE operation_ledger (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    predecessor_operation_id TEXT,
    destination TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    owner_generation BLOB NOT NULL CHECK (length(owner_generation) = 8),
    revision INTEGER NOT NULL CHECK (revision > 0),
    writer_fence INTEGER NOT NULL CHECK (writer_fence >= 0),
    state TEXT NOT NULL CHECK (state IN (
        'prepared', 'dispatching', 'dispatched', 'indeterminate',
        'applied', 'not_applied', 'quarantined'
    )),
    authority_epoch BLOB CHECK (length(authority_epoch) = 8),
    authority_digest BLOB CHECK (length(authority_digest) = 32),
    dispatch_digest BLOB CHECK (length(dispatch_digest) = 32),
    indeterminate_digest BLOB CHECK (length(indeterminate_digest) = 32),
    terminal_outcome TEXT CHECK (terminal_outcome IN ('applied', 'not_applied', 'quarantined')),
    terminal_evidence_digest BLOB CHECK (length(terminal_evidence_digest) = 32),
    terminal_observer_id TEXT,
    terminal_observer_generation BLOB CHECK (length(terminal_observer_generation) = 8),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    PRIMARY KEY (scope_id, operation_id),
    CHECK ((state IN ('applied', 'not_applied', 'quarantined') AND terminal_at_ms IS NOT NULL
            AND terminal_outcome IS NOT NULL AND terminal_evidence_digest IS NOT NULL
            AND terminal_observer_id IS NOT NULL AND terminal_observer_generation IS NOT NULL)
        OR (state NOT IN ('applied', 'not_applied', 'quarantined') AND terminal_at_ms IS NULL
            AND terminal_outcome IS NULL AND terminal_evidence_digest IS NULL
            AND terminal_observer_id IS NULL AND terminal_observer_generation IS NULL)),
    CHECK ((state = 'dispatching' AND authority_epoch IS NOT NULL AND authority_digest IS NOT NULL)
        OR state != 'dispatching')
) WITHOUT ROWID;

CREATE TABLE cross_owner_outbox (
    destination TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'acked', 'indeterminate', 'quarantined')),
    fence INTEGER NOT NULL CHECK (fence >= 0),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 16),
    worker_id TEXT,
    owner_generation BLOB NOT NULL CHECK (length(owner_generation) = 8),
    lease_until_ms INTEGER,
    next_eligible_at_ms INTEGER NOT NULL CHECK (next_eligible_at_ms >= 0),
    acknowledgement_digest BLOB CHECK (length(acknowledgement_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    PRIMARY KEY (destination, scope_id, operation_id),
    FOREIGN KEY (scope_id, operation_id) REFERENCES operation_ledger(scope_id, operation_id),
    CHECK ((state = 'leased' AND worker_id IS NOT NULL AND lease_until_ms IS NOT NULL
            AND lease_until_ms > updated_at_ms)
        OR (state != 'leased' AND worker_id IS NULL AND lease_until_ms IS NULL)),
    CHECK ((state IN ('queued', 'leased') AND terminal_at_ms IS NULL)
        OR (state IN ('acked', 'indeterminate', 'quarantined') AND terminal_at_ms IS NOT NULL)),
    CHECK ((state = 'acked' AND acknowledgement_digest IS NOT NULL)
        OR (state != 'acked' AND acknowledgement_digest IS NULL))
) WITHOUT ROWID;

CREATE INDEX cross_owner_outbox_ready ON cross_owner_outbox
    (destination, state, next_eligible_at_ms, operation_id);
CREATE INDEX operation_ledger_unsettled ON operation_ledger
    (destination, state, updated_at_ms, operation_id);

-- Terminal source rows may be compacted only after a tombstone is written in
-- the same transaction. Tombstones permanently fence semantic identity reuse.
CREATE TABLE operation_tombstones (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    semantic_digest BLOB NOT NULL CHECK (length(semantic_digest) = 32),
    destination TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    terminal_outcome TEXT NOT NULL CHECK (terminal_outcome IN ('applied', 'not_applied', 'quarantined')),
    terminal_evidence_digest BLOB NOT NULL CHECK (length(terminal_evidence_digest) = 32),
    retired_at_ms INTEGER NOT NULL CHECK (retired_at_ms >= 0),
    PRIMARY KEY (scope_id, operation_id)
) WITHOUT ROWID;

CREATE TRIGGER operation_ledger_identity_immutable BEFORE UPDATE OF
    scope_id, operation_id, semantic_digest, predecessor_operation_id,
    destination, payload_digest, created_at_ms
    ON operation_ledger
BEGIN
    SELECT RAISE(ABORT, 'operation identity is immutable');
END;

CREATE TRIGGER operation_ledger_terminal_immutable BEFORE UPDATE ON operation_ledger
WHEN OLD.state IN ('applied', 'not_applied', 'quarantined')
BEGIN
    SELECT RAISE(ABORT, 'terminal operation is immutable');
END;

CREATE TRIGGER cross_owner_outbox_identity_immutable BEFORE UPDATE OF
    destination, scope_id, operation_id, payload_digest, created_at_ms
    ON cross_owner_outbox
BEGIN
    SELECT RAISE(ABORT, 'outbox identity is immutable');
END;

CREATE TRIGGER cross_owner_outbox_active_no_delete BEFORE DELETE ON cross_owner_outbox
WHEN OLD.state IN ('queued', 'leased')
BEGIN
    SELECT RAISE(ABORT, 'active outbox rows cannot be deleted');
END;
