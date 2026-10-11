-- Conservation-safe quota and reservation owner. Big-endian BLOB counters keep
-- the full u64 range while all arithmetic remains in checked Rust code.
CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    unit TEXT NOT NULL,
    period_id TEXT NOT NULL,
    limit_amount BLOB NOT NULL CHECK (length(limit_amount) = 8),
    available BLOB NOT NULL CHECK (length(available) = 8),
    reserved BLOB NOT NULL CHECK (length(reserved) = 8),
    consumed BLOB NOT NULL CHECK (length(consumed) = 8),
    revision BLOB NOT NULL CHECK (length(revision) = 8)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_reservation (
    reservation_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    quota_key TEXT NOT NULL REFERENCES authbus_quota_registry(quota_key),
    period_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    amount BLOB NOT NULL CHECK (length(amount) = 8),
    effect_digest BLOB NOT NULL CHECK (length(effect_digest) = 32),
    policy_id TEXT NOT NULL,
    policy_revision BLOB NOT NULL CHECK (length(policy_revision) = 8),
    policy_decision_digest BLOB NOT NULL CHECK (length(policy_decision_digest) = 32),
    state TEXT NOT NULL CHECK (state IN
        ('held', 'dispatch_attempted', 'indeterminate', 'settled', 'released', 'expired')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    created_at_ms BLOB NOT NULL CHECK (length(created_at_ms) = 8),
    updated_at_ms BLOB NOT NULL CHECK (length(updated_at_ms) = 8),
    dispatch_digest BLOB CHECK (dispatch_digest IS NULL OR length(dispatch_digest) = 32),
    terminal_evidence BLOB CHECK (terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    observed_cost BLOB CHECK (observed_cost IS NULL OR length(observed_cost) = 8),
    settlement_digest BLOB CHECK (settlement_digest IS NULL OR length(settlement_digest) = 32)
) WITHOUT ROWID;

CREATE INDEX authbus_reservation_principal_state
    ON authbus_quota_reservation(principal, state);
CREATE INDEX authbus_reservation_quota_state
    ON authbus_quota_reservation(quota_key, state);

CREATE TRIGGER authbus_reservation_immutable BEFORE UPDATE OF
    reservation_id, operation_id, quota_key, period_id, principal, amount, effect_digest,
    policy_id, policy_revision, policy_decision_digest, expires_at_ms, created_at_ms
    ON authbus_quota_reservation
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation identity is immutable');
END;
