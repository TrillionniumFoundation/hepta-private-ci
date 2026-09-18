-- AuthBus policy/quota/reservation owner state. All counters and window
-- timestamps are fixed-width big-endian u64 blobs; mutation is performed under
-- BEGIN IMMEDIATE. Reservation identity/binding columns are immutable.
CREATE TABLE authbus_policy_heads (
    policy_id TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    revoked INTEGER NOT NULL CHECK(revoked IN (0,1)),
    updated_at_ms INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE authbus_policy_rules (
    policy_id TEXT NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    allow INTEGER NOT NULL CHECK(allow IN (0,1)),
    PRIMARY KEY(policy_id, revision, principal_id, action_id, scope_digest)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    unit_id TEXT NOT NULL,
    window_start_ms BLOB NOT NULL CHECK(length(window_start_ms) = 8),
    window_end_ms BLOB NOT NULL CHECK(length(window_end_ms) = 8),
    endowment BLOB NOT NULL CHECK(length(endowment) = 8),
    reserved BLOB NOT NULL CHECK(length(reserved) = 8),
    consumed BLOB NOT NULL CHECK(length(consumed) = 8),
    updated_at_ms INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE authbus_quota_reservations (
    reservation_id TEXT PRIMARY KEY NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    quota_key TEXT NOT NULL,
    quota_revision BLOB NOT NULL CHECK(length(quota_revision) = 8),
    amount BLOB NOT NULL CHECK(length(amount) = 8),
    expires_at_ms BLOB NOT NULL CHECK(length(expires_at_ms) = 8),
    policy_id TEXT NOT NULL,
    policy_revision BLOB NOT NULL CHECK(length(policy_revision) = 8),
    effect_digest BLOB NOT NULL CHECK(length(effect_digest) = 32),
    binding_digest BLOB NOT NULL CHECK(length(binding_digest) = 32),
    state TEXT NOT NULL CHECK(state IN ('active','effect_started','settled','cancelled','expired','quarantined')),
    effect_started_at_ms INTEGER,
    observed_cost BLOB CHECK(observed_cost IS NULL OR length(observed_cost) = 8),
    terminal_evidence BLOB CHECK(terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    settlement_digest BLOB CHECK(settlement_digest IS NULL OR length(settlement_digest) = 32),
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(quota_key) REFERENCES authbus_quota_registry(quota_key) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK (
        (state IN ('effect_started','settled','quarantined') AND effect_started_at_ms IS NOT NULL)
        OR (state IN ('active','cancelled','expired') AND effect_started_at_ms IS NULL)
    ),
    CHECK (
        (state = 'settled' AND observed_cost IS NOT NULL AND terminal_evidence IS NOT NULL AND settlement_digest IS NOT NULL)
        OR (state != 'settled' AND observed_cost IS NULL AND terminal_evidence IS NULL AND settlement_digest IS NULL)
    )
) WITHOUT ROWID;

CREATE INDEX authbus_quota_reservations_state
ON authbus_quota_reservations(quota_key, quota_revision, state, updated_at_ms, reservation_id);

CREATE TRIGGER authbus_quota_reservation_immutable BEFORE UPDATE OF
    reservation_id, operation_id, principal_id, action_id, scope_digest, quota_key,
    quota_revision, amount, expires_at_ms, policy_id, policy_revision, effect_digest,
    binding_digest
    ON authbus_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation binding is immutable');
END;

CREATE TRIGGER authbus_quota_reservation_transition BEFORE UPDATE ON authbus_quota_reservations
WHEN NEW.updated_at_ms < OLD.updated_at_ms
    OR NOT (
        (OLD.state = 'active' AND NEW.state IN ('effect_started','cancelled','expired'))
        OR (OLD.state = 'effect_started' AND NEW.state IN ('settled','quarantined'))
        OR (OLD.state = 'quarantined' AND NEW.state = 'settled')
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation transition');
END;

CREATE TRIGGER authbus_quota_reservation_held_no_delete BEFORE DELETE ON authbus_quota_reservations
WHEN OLD.state IN ('active','effect_started','quarantined')
BEGIN
    SELECT RAISE(ABORT, 'held AuthBus reservations cannot be deleted');
END;
