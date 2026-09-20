-- Rollback-resistant authority frontier, restart reconciliation and safe terminal retention.
CREATE TABLE authbus_authority_checkpoint (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation BLOB NOT NULL CHECK (length(generation) = 8),
    checkpoint_digest BLOB NOT NULL CHECK (length(checkpoint_digest) = 32)
) WITHOUT ROWID;

CREATE TABLE authbus_authority_checkpoint_dirty (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    dirty INTEGER NOT NULL CHECK (dirty IN (0, 1))
) WITHOUT ROWID;
INSERT INTO authbus_authority_checkpoint_dirty(singleton, dirty) VALUES (1, 0);

CREATE TABLE authbus_recovery_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    recovery_required INTEGER NOT NULL CHECK (recovery_required IN (0, 1))
) WITHOUT ROWID;
INSERT INTO authbus_recovery_state(singleton, recovery_required) VALUES (1, 0);

CREATE TABLE authbus_policy_history (
    policy_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    action TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    not_before_ms BLOB NOT NULL CHECK (length(not_before_ms) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)),
    PRIMARY KEY (policy_id, revision)
) WITHOUT ROWID;

CREATE TABLE authbus_policy_archive (
    policy_id TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    action TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    not_before_ms BLOB NOT NULL CHECK (length(not_before_ms) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    revoked INTEGER NOT NULL CHECK (revoked = 1),
    retired_at_ms BLOB NOT NULL CHECK (length(retired_at_ms) = 8)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_reservation_archive (
    reservation_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    quota_key TEXT NOT NULL,
    period_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    amount BLOB NOT NULL CHECK (length(amount) = 8),
    effect_digest BLOB NOT NULL CHECK (length(effect_digest) = 32),
    policy_id TEXT NOT NULL,
    policy_revision BLOB NOT NULL CHECK (length(policy_revision) = 8),
    policy_decision_digest BLOB NOT NULL CHECK (length(policy_decision_digest) = 32),
    state TEXT NOT NULL CHECK (state IN ('settled', 'released', 'expired', 'cancelled')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    created_at_ms BLOB NOT NULL CHECK (length(created_at_ms) = 8),
    updated_at_ms BLOB NOT NULL CHECK (length(updated_at_ms) = 8),
    dispatch_digest BLOB CHECK (dispatch_digest IS NULL OR length(dispatch_digest) = 32),
    terminal_evidence BLOB CHECK (terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    observed_cost BLOB CHECK (observed_cost IS NULL OR length(observed_cost) = 8),
    settlement_digest BLOB CHECK (settlement_digest IS NULL OR length(settlement_digest) = 32),
    archived_at_ms BLOB NOT NULL CHECK (length(archived_at_ms) = 8)
) WITHOUT ROWID;

CREATE TRIGGER authbus_reservation_transition
BEFORE UPDATE OF state ON authbus_quota_reservation
WHEN NOT (
    OLD.state = NEW.state OR
    (OLD.state = 'held' AND NEW.state IN ('dispatch_attempted', 'cancelled', 'expired')) OR
    (OLD.state = 'dispatch_attempted' AND NEW.state IN ('indeterminate', 'settled', 'released')) OR
    (OLD.state = 'indeterminate' AND NEW.state IN ('settled', 'released'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation state transition');
END;

CREATE TRIGGER authbus_reservation_live_delete
BEFORE DELETE ON authbus_quota_reservation
WHEN OLD.state IN ('held', 'dispatch_attempted', 'indeterminate')
BEGIN
    SELECT RAISE(ABORT, 'cannot delete live AuthBus reservation');
END;

CREATE TRIGGER authbus_reservation_terminal_fields
BEFORE UPDATE ON authbus_quota_reservation
WHEN (
    NEW.state IN ('settled', 'released')
    AND (NEW.terminal_evidence IS NULL OR NEW.observed_cost IS NULL OR NEW.settlement_digest IS NULL)
) OR (
    NEW.state IN ('held', 'dispatch_attempted', 'indeterminate', 'expired', 'cancelled')
    AND NEW.settlement_digest IS NOT NULL
)
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation terminal fields');
END;

-- Every authoritative mutation marks the semantic frontier dirty in the same SQLite commit.
CREATE TRIGGER authbus_dirty_time_insert AFTER INSERT ON authbus_trusted_time
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_time_update AFTER UPDATE ON authbus_trusted_time
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_policy_insert AFTER INSERT ON authbus_policy
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_policy_update AFTER UPDATE ON authbus_policy
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_policy_delete AFTER DELETE ON authbus_policy
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_policy_history_insert AFTER INSERT ON authbus_policy_history
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_policy_archive_insert AFTER INSERT ON authbus_policy_archive
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_quota_insert AFTER INSERT ON authbus_quota_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_quota_update AFTER UPDATE ON authbus_quota_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_reservation_insert AFTER INSERT ON authbus_quota_reservation
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_reservation_update AFTER UPDATE ON authbus_quota_reservation
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_reservation_delete AFTER DELETE ON authbus_quota_reservation
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_reservation_archive AFTER INSERT ON authbus_quota_reservation_archive
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_issuer_insert AFTER INSERT ON authbus_issuer_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_issuer_update AFTER UPDATE ON authbus_issuer_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
