-- Durable AuthBus policy/quota/reservation state shares the existing evidence SQLite owner.
-- All unsigned counters are fixed-width big-endian blobs so the full u64 range is preserved.
CREATE TABLE authbus_policy_versions (
    policy_id TEXT NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    principal_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_digest BLOB NOT NULL CHECK(length(resource_digest) = 32),
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    audience TEXT NOT NULL,
    quota_key TEXT NOT NULL,
    max_reservation BLOB NOT NULL CHECK(length(max_reservation) = 8),
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    PRIMARY KEY(policy_id, revision)
) WITHOUT ROWID;

CREATE TABLE authbus_policy_heads (
    policy_id TEXT PRIMARY KEY,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE TRIGGER authbus_policy_versions_no_update BEFORE UPDATE ON authbus_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy versions are immutable');
END;

CREATE TRIGGER authbus_policy_versions_no_delete BEFORE DELETE ON authbus_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy versions are immutable');
END;

CREATE TRIGGER authbus_policy_heads_no_delete BEFORE DELETE ON authbus_policy_heads
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy heads cannot be deleted');
END;

CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY,
    config_revision BLOB NOT NULL CHECK(length(config_revision) = 8),
    ledger_revision BLOB NOT NULL CHECK(length(ledger_revision) = 8),
    capacity BLOB NOT NULL CHECK(length(capacity) = 8),
    reserved BLOB NOT NULL CHECK(length(reserved) = 8),
    consumed BLOB NOT NULL CHECK(length(consumed) = 8),
    period_start_ms BLOB NOT NULL CHECK(length(period_start_ms) = 8),
    period_end_ms BLOB NOT NULL CHECK(length(period_end_ms) = 8),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE TRIGGER authbus_quota_registry_no_delete BEFORE DELETE ON authbus_quota_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus quota registry cannot be deleted');
END;

CREATE TABLE authbus_quota_reservations (
    reservation_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    quota_key TEXT NOT NULL,
    amount BLOB NOT NULL CHECK(length(amount) = 8),
    state TEXT NOT NULL CHECK(state IN ('active', 'settled', 'cancelled', 'expired', 'quarantined')),
    expires_at_ms BLOB NOT NULL CHECK(length(expires_at_ms) = 8),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    authorization_digest BLOB NOT NULL CHECK(length(authorization_digest) = 32),
    quota_revision_at_reserve BLOB NOT NULL CHECK(length(quota_revision_at_reserve) = 8),
    observed_cost BLOB CHECK(observed_cost IS NULL OR length(observed_cost) = 8),
    terminal_evidence BLOB CHECK(terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= created_at_ms),
    FOREIGN KEY(quota_key) REFERENCES authbus_quota_registry(quota_key) ON DELETE RESTRICT,
    CHECK (
        (state = 'settled' AND observed_cost IS NOT NULL AND terminal_evidence IS NOT NULL)
        OR (state = 'cancelled' AND observed_cost IS NULL AND terminal_evidence IS NOT NULL)
        OR (state IN ('active', 'expired') AND observed_cost IS NULL AND terminal_evidence IS NULL)
        OR (state = 'quarantined' AND observed_cost IS NULL AND terminal_evidence IS NOT NULL)
    )
) WITHOUT ROWID;

CREATE INDEX authbus_quota_reservations_quota_state
    ON authbus_quota_reservations(quota_key, state, reservation_id);
CREATE INDEX authbus_quota_reservations_expiry
    ON authbus_quota_reservations(state, expires_at_ms, reservation_id);

CREATE TRIGGER authbus_quota_reservations_transition BEFORE UPDATE ON authbus_quota_reservations
WHEN OLD.reservation_id != NEW.reservation_id
    OR OLD.operation_id != NEW.operation_id
    OR OLD.quota_key != NEW.quota_key
    OR OLD.amount != NEW.amount
    OR OLD.expires_at_ms != NEW.expires_at_ms
    OR OLD.policy_digest != NEW.policy_digest
    OR OLD.authorization_digest != NEW.authorization_digest
    OR OLD.quota_revision_at_reserve != NEW.quota_revision_at_reserve
    OR NEW.updated_at_ms < OLD.updated_at_ms
    OR OLD.state IN ('settled', 'cancelled')
    OR (OLD.state = 'active' AND NEW.state NOT IN ('settled', 'cancelled', 'expired', 'quarantined'))
    OR (OLD.state IN ('expired', 'quarantined') AND NEW.state NOT IN ('settled', 'cancelled', 'quarantined'))
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation transition');
END;

CREATE TRIGGER authbus_quota_reservations_no_delete BEFORE DELETE ON authbus_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservations are retained for reconciliation');
END;

CREATE TABLE authbus_issuer_registry (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    public_key BLOB NOT NULL CHECK(length(public_key) = 32),
    state TEXT NOT NULL CHECK(state IN ('active', 'revoked', 'retired')),
    registered_at_ms INTEGER NOT NULL CHECK(registered_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= registered_at_ms),
    PRIMARY KEY(issuer_id, key_epoch)
) WITHOUT ROWID;

CREATE TABLE authbus_issuer_heads (
    issuer_id TEXT PRIMARY KEY,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE TRIGGER authbus_issuer_registry_identity_immutable BEFORE UPDATE OF issuer_id, key_epoch, public_key, registered_at_ms
    ON authbus_issuer_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus issuer identity is immutable');
END;

CREATE TRIGGER authbus_issuer_registry_no_delete BEFORE DELETE ON authbus_issuer_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus issuer registry entries cannot be deleted');
END;

CREATE TRIGGER authbus_issuer_heads_no_delete BEFORE DELETE ON authbus_issuer_heads
BEGIN
    SELECT RAISE(ABORT, 'AuthBus issuer heads cannot be deleted');
END;

CREATE TABLE authbus_replay_retired_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    retired_checkpoint_generation BLOB NOT NULL CHECK(length(retired_checkpoint_generation) = 8),
    retired_at_ms INTEGER NOT NULL CHECK(retired_at_ms >= 0),
    PRIMARY KEY(issuer_id, key_epoch)
) WITHOUT ROWID;

CREATE TRIGGER authbus_replay_retired_epochs_no_update BEFORE UPDATE ON authbus_replay_retired_epochs
BEGIN
    SELECT RAISE(ABORT, 'AuthBus retired replay epochs are immutable');
END;

CREATE TRIGGER authbus_replay_retired_epochs_no_delete BEFORE DELETE ON authbus_replay_retired_epochs
BEGIN
    SELECT RAISE(ABORT, 'AuthBus retired replay epochs cannot be deleted');
END;

CREATE TABLE authbus_rollback_guard (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    generation BLOB NOT NULL CHECK(length(generation) = 8),
    chain_digest BLOB NOT NULL CHECK(length(chain_digest) = 32),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
);

INSERT INTO authbus_rollback_guard(singleton, generation, chain_digest, updated_at_ms)
VALUES (
    1,
    zeroblob(8),
    X'8492fd67f1a1ad6363abac14a31cd933f098be88a98f36e76665bcad0f71294a',
    0
);

CREATE TRIGGER authbus_rollback_guard_no_delete BEFORE DELETE ON authbus_rollback_guard
BEGIN
    SELECT RAISE(ABORT, 'AuthBus rollback guard cannot be deleted');
END;
