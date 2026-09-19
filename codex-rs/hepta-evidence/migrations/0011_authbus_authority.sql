-- Durable AuthBus policy, quota and reservation authority state.
-- This migration intentionally reuses the evidence-store owner and transaction
-- boundary; no second authority database is introduced.

CREATE TABLE authbus_policy_revisions (
    policy_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    revision INTEGER NOT NULL CHECK(revision > 0),
    allowed INTEGER NOT NULL CHECK(allowed IN (0, 1)),
    revoked INTEGER NOT NULL CHECK(revoked IN (0, 1)),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    recorded_at_ms INTEGER NOT NULL CHECK(recorded_at_ms >= 0),
    PRIMARY KEY(policy_id, revision),
    UNIQUE(principal_id, action_id, scope_digest, revision)
) WITHOUT ROWID;

CREATE INDEX authbus_policy_lookup ON authbus_policy_revisions
    (principal_id, action_id, scope_digest, revision DESC);

CREATE TRIGGER authbus_policy_no_update BEFORE UPDATE ON authbus_policy_revisions
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy revisions are immutable');
END;

CREATE TRIGGER authbus_policy_no_delete BEFORE DELETE ON authbus_policy_revisions
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy revisions are immutable');
END;

CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY,
    limit_value INTEGER NOT NULL CHECK(limit_value > 0),
    available INTEGER NOT NULL CHECK(available >= 0),
    reserved INTEGER NOT NULL CHECK(reserved >= 0),
    consumed INTEGER NOT NULL CHECK(consumed >= 0),
    revision INTEGER NOT NULL CHECK(revision > 0),
    CHECK(available + reserved + consumed = limit_value)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_reservations (
    reservation_id TEXT PRIMARY KEY,
    quota_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK(amount > 0),
    observed_cost INTEGER CHECK(observed_cost >= 0),
    expires_at_ms INTEGER NOT NULL CHECK(expires_at_ms > 0),
    quota_revision INTEGER NOT NULL CHECK(quota_revision > 0),
    state TEXT NOT NULL CHECK(state IN (
        'held', 'indeterminate', 'settled', 'cancelled', 'expired', 'quarantined'
    )),
    reservation_digest BLOB NOT NULL CHECK(length(reservation_digest) = 32),
    settlement_digest BLOB CHECK(length(settlement_digest) = 32),
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= created_at_ms),
    FOREIGN KEY(quota_key) REFERENCES authbus_quota_registry(quota_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK(
        (state IN ('held', 'indeterminate') AND settlement_digest IS NULL)
        OR state IN ('settled', 'cancelled', 'expired', 'quarantined')
    ),
    CHECK(
        (state = 'settled' AND observed_cost IS NOT NULL AND settlement_digest IS NOT NULL)
        OR state != 'settled'
    )
) WITHOUT ROWID;

CREATE INDEX authbus_quota_reservation_state ON authbus_quota_reservations
    (quota_key, state, expires_at_ms, reservation_id);

CREATE TRIGGER authbus_quota_reservation_identity_immutable BEFORE UPDATE OF
    reservation_id, quota_key, operation_id, amount, expires_at_ms,
    quota_revision, reservation_digest, created_at_ms
    ON authbus_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation identity is immutable');
END;

CREATE TABLE authbus_replay_checkpoint_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    checkpoint_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation > 0),
    replay_root BLOB NOT NULL CHECK(length(replay_root) = 32),
    observed_at_ms INTEGER NOT NULL CHECK(observed_at_ms > 0)
);

CREATE TABLE authbus_trust_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    public_key BLOB NOT NULL CHECK(length(public_key) = 32),
    revoked INTEGER NOT NULL CHECK(revoked IN (0, 1)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    recorded_at_ms INTEGER NOT NULL CHECK(recorded_at_ms >= 0),
    PRIMARY KEY(issuer_id, key_epoch, revision)
) WITHOUT ROWID;

CREATE INDEX authbus_trust_current ON authbus_trust_epochs
    (issuer_id, key_epoch, revision DESC);

CREATE TRIGGER authbus_trust_no_update BEFORE UPDATE ON authbus_trust_epochs
BEGIN
    SELECT RAISE(ABORT, 'AuthBus trust epochs are immutable');
END;

CREATE TRIGGER authbus_trust_no_delete BEFORE DELETE ON authbus_trust_epochs
BEGIN
    SELECT RAISE(ABORT, 'AuthBus trust epochs are immutable');
END;
