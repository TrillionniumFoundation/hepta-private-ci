PRAGMA foreign_keys = ON;

CREATE TABLE authbus_policy_heads (
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    max_active_reservations INTEGER NOT NULL CHECK (
        max_active_reservations BETWEEN 1 AND 4096
    ),
    record_digest BLOB NOT NULL CHECK (length(record_digest) = 32),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    PRIMARY KEY (principal_id, action_id, scope_digest)
) WITHOUT ROWID;

CREATE TABLE authbus_policy_history (
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    max_active_reservations INTEGER NOT NULL CHECK (
        max_active_reservations BETWEEN 1 AND 4096
    ),
    record_digest BLOB NOT NULL CHECK (length(record_digest) = 32),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (principal_id, action_id, scope_digest, revision)
) WITHOUT ROWID;

CREATE TRIGGER authbus_policy_history_no_update
BEFORE UPDATE ON authbus_policy_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy history is immutable');
END;

CREATE TRIGGER authbus_policy_history_no_delete
BEFORE DELETE ON authbus_policy_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy history is immutable');
END;

CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    capacity BLOB NOT NULL CHECK (length(capacity) = 8),
    reserved BLOB NOT NULL CHECK (length(reserved) = 8),
    consumed BLOB NOT NULL CHECK (length(consumed) = 8),
    period_start_ms INTEGER NOT NULL CHECK (period_start_ms >= 0),
    period_end_ms INTEGER NOT NULL CHECK (period_end_ms > period_start_ms),
    record_digest BLOB NOT NULL CHECK (length(record_digest) = 32),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_history (
    quota_key TEXT NOT NULL,
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    capacity BLOB NOT NULL CHECK (length(capacity) = 8),
    period_start_ms INTEGER NOT NULL CHECK (period_start_ms >= 0),
    period_end_ms INTEGER NOT NULL CHECK (period_end_ms > period_start_ms),
    record_digest BLOB NOT NULL CHECK (length(record_digest) = 32),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (quota_key, revision)
) WITHOUT ROWID;

CREATE TRIGGER authbus_quota_history_no_update
BEFORE UPDATE ON authbus_quota_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus quota history is immutable');
END;

CREATE TRIGGER authbus_quota_history_no_delete
BEFORE DELETE ON authbus_quota_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus quota history is immutable');
END;

CREATE TABLE authbus_quota_reservations (
    reservation_id BLOB PRIMARY KEY NOT NULL CHECK (length(reservation_id) = 32),
    operation_id TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    policy_revision BLOB NOT NULL CHECK (length(policy_revision) = 8),
    quota_key TEXT NOT NULL,
    quota_revision BLOB NOT NULL CHECK (length(quota_revision) = 8),
    amount BLOB NOT NULL CHECK (length(amount) = 8),
    state TEXT NOT NULL CHECK (
        state IN ('reserved', 'in_flight', 'settled', 'cancelled', 'expired', 'quarantined')
    ),
    observed_cost BLOB CHECK (observed_cost IS NULL OR length(observed_cost) = 8),
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > 0),
    terminal_evidence BLOB CHECK (terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    FOREIGN KEY (quota_key) REFERENCES authbus_quota_registry(quota_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX authbus_quota_reservations_state_expiry
ON authbus_quota_reservations(state, expires_at_ms, quota_key);

CREATE INDEX authbus_quota_reservations_principal_state
ON authbus_quota_reservations(principal_id, state);

CREATE TRIGGER authbus_quota_reservation_identity_immutable
BEFORE UPDATE OF reservation_id, operation_id, principal_id, action_id, scope_digest,
    policy_revision, quota_key, quota_revision, amount, expires_at_ms, created_at_ms
ON authbus_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation identity is immutable');
END;

CREATE TRIGGER authbus_quota_reservation_transition
BEFORE UPDATE ON authbus_quota_reservations
WHEN
    new.updated_at_ms < old.updated_at_ms
    OR (old.state = 'reserved' AND new.state NOT IN ('in_flight', 'cancelled', 'expired'))
    OR (old.state = 'in_flight' AND new.state NOT IN ('settled', 'quarantined'))
    OR (old.state = 'quarantined' AND new.state NOT IN ('settled', 'cancelled'))
    OR (old.state IN ('settled', 'cancelled', 'expired') AND new.state != old.state)
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation transition');
END;

CREATE TABLE authbus_trust_heads (
    issuer_id TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    verifying_key_digest BLOB NOT NULL CHECK (length(verifying_key_digest) = 32),
    registration_digest BLOB NOT NULL CHECK (length(registration_digest) = 32),
    revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE TABLE authbus_retired_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    checkpoint_generation BLOB NOT NULL CHECK (length(checkpoint_generation) = 8),
    retired_at_ms INTEGER NOT NULL CHECK (retired_at_ms >= 0),
    PRIMARY KEY (issuer_id, key_epoch)
) WITHOUT ROWID;

CREATE TRIGGER authbus_retired_epochs_no_delete
BEFORE DELETE ON authbus_retired_epochs
BEGIN
    SELECT RAISE(ABORT, 'AuthBus retired epochs are permanent');
END;

CREATE TABLE authbus_replay_checkpoint (
    singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
    generation BLOB NOT NULL CHECK (length(generation) = 8),
    replay_digest BLOB NOT NULL CHECK (length(replay_digest) = 32),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
);
