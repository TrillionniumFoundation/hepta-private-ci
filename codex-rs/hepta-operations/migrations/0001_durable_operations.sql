CREATE TABLE operation_ledger (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    predecessor_id TEXT,
    destination_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK(length(payload_digest) = 32),
    semantic_digest BLOB NOT NULL CHECK(length(semantic_digest) = 32),
    owner_generation BLOB NOT NULL CHECK(length(owner_generation) = 8),
    authority_epoch BLOB NOT NULL CHECK(length(authority_epoch) = 8),
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    state TEXT NOT NULL CHECK(state IN (
        'prepared', 'dispatched', 'indeterminate', 'applied', 'not_applied', 'quarantined'
    )),
    dispatch_digest BLOB CHECK(dispatch_digest IS NULL OR length(dispatch_digest) = 32),
    indeterminate_digest BLOB CHECK(indeterminate_digest IS NULL OR length(indeterminate_digest) = 32),
    terminal_evidence_digest BLOB CHECK(terminal_evidence_digest IS NULL OR length(terminal_evidence_digest) = 32),
    terminal_observer_id TEXT,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER CHECK(terminal_at_ms IS NULL OR terminal_at_ms >= created_at_ms),
    PRIMARY KEY(scope_id, operation_id),
    CHECK((state IN ('applied', 'not_applied', 'quarantined')) = (terminal_at_ms IS NOT NULL)),
    CHECK((state IN ('applied', 'not_applied', 'quarantined')) = (terminal_evidence_digest IS NOT NULL))
) STRICT;

CREATE TABLE cross_owner_outbox (
    scope_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,
    payload_digest BLOB NOT NULL CHECK(length(payload_digest) = 32),
    semantic_digest BLOB NOT NULL CHECK(length(semantic_digest) = 32),
    state TEXT NOT NULL CHECK(state IN (
        'queued', 'leased', 'indeterminate', 'acknowledged', 'quarantined'
    )),
    fence INTEGER NOT NULL CHECK(fence >= 0),
    attempts INTEGER NOT NULL CHECK(attempts >= 0 AND attempts <= 32),
    worker_id TEXT,
    claim_owner_generation BLOB CHECK(claim_owner_generation IS NULL OR length(claim_owner_generation) = 8),
    lease_until_ms INTEGER,
    next_eligible_at_ms INTEGER NOT NULL CHECK(next_eligible_at_ms >= 0),
    acknowledgement_digest BLOB CHECK(acknowledgement_digest IS NULL OR length(acknowledgement_digest) = 32),
    acknowledgement_watermark BLOB CHECK(acknowledgement_watermark IS NULL OR length(acknowledgement_watermark) = 8),
    last_error_digest BLOB CHECK(last_error_digest IS NULL OR length(last_error_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER CHECK(terminal_at_ms IS NULL OR terminal_at_ms >= created_at_ms),
    PRIMARY KEY(scope_id, operation_id),
    FOREIGN KEY(scope_id, operation_id) REFERENCES operation_ledger(scope_id, operation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((state = 'leased') = (worker_id IS NOT NULL)),
    CHECK((state = 'leased') = (claim_owner_generation IS NOT NULL)),
    CHECK((state = 'leased') = (lease_until_ms IS NOT NULL)),
    CHECK((state IN ('acknowledged', 'quarantined')) = (terminal_at_ms IS NOT NULL))
) STRICT;

CREATE INDEX cross_owner_outbox_ready_idx
    ON cross_owner_outbox(destination_id, state, next_eligible_at_ms, scope_id, operation_id);
CREATE INDEX cross_owner_outbox_terminal_idx
    ON cross_owner_outbox(state, terminal_at_ms, scope_id, operation_id);
CREATE INDEX operation_ledger_state_idx
    ON operation_ledger(state, updated_at_ms, scope_id, operation_id);
