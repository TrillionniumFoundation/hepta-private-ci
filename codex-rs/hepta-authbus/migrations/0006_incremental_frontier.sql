-- Incremental authority frontier.
--
-- The legacy checkpoint digest is a complete ordered snapshot of every
-- authoritative row.  It remains the one-time seed for an upgraded database.
-- Subsequent owner mutations append canonical after-image/delete events in the
-- same SQLite transaction as the authoritative change.  The Rust owner folds
-- those events into a domain-separated hash accumulator before publishing the
-- external checkpoint, then prunes only events already covered by the durable
-- accumulator.  This removes history-sized work from the mutation hot path
-- without creating another source of truth.
CREATE TABLE authbus_frontier_accumulator (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    root_digest BLOB CHECK (root_digest IS NULL OR length(root_digest) = 32),
    applied_change_id INTEGER NOT NULL CHECK (applied_change_id >= 0)
) WITHOUT ROWID;
INSERT INTO authbus_frontier_accumulator
    (singleton, schema_version, root_digest, applied_change_id)
VALUES (1, 1, NULL, 0);

CREATE TABLE authbus_frontier_change (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    record_key TEXT NOT NULL,
    canonical_record TEXT NOT NULL
);

CREATE TRIGGER authbus_frontier_change_immutable_update
BEFORE UPDATE ON authbus_frontier_change
BEGIN
    SELECT RAISE(ABORT, 'AuthBus frontier changes are immutable');
END;

-- Applied events may be pruned after their accumulator update commits. Pending
-- events are immutable and undeletable, including by a direct SQL caller.
CREATE TRIGGER authbus_frontier_change_pending_delete
BEFORE DELETE ON authbus_frontier_change
WHEN OLD.change_id > (
    SELECT applied_change_id FROM authbus_frontier_accumulator WHERE singleton = 1
)
BEGIN
    SELECT RAISE(ABORT, 'cannot delete pending AuthBus frontier change');
END;

CREATE TRIGGER authbus_frontier_time_insert
AFTER INSERT ON authbus_trusted_time
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'trusted_time', 'upsert', 'singleton:1',
        hex(NEW.wall_time_ms)||'|'||hex(NEW.source_revision)||'|'||hex(NEW.source_digest)
    );
END;
CREATE TRIGGER authbus_frontier_time_update
AFTER UPDATE ON authbus_trusted_time
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'trusted_time', 'upsert', 'singleton:1',
        hex(NEW.wall_time_ms)||'|'||hex(NEW.source_revision)||'|'||hex(NEW.source_digest)
    );
END;
CREATE TRIGGER authbus_frontier_time_delete
AFTER DELETE ON authbus_trusted_time
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'trusted_time', 'delete', 'singleton:1',
        hex(OLD.wall_time_ms)||'|'||hex(OLD.source_revision)||'|'||hex(OLD.source_digest)
    );
    UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1;
END;

CREATE TRIGGER authbus_frontier_policy_insert
AFTER INSERT ON authbus_policy
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'policy', 'upsert', NEW.policy_id,
        hex(CAST(NEW.policy_id AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(CAST(NEW.action AS BLOB))||'|'||hex(NEW.scope_digest)||'|'||
        hex(CAST(NEW.effect AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.not_before_ms)||'|'||hex(NEW.expires_at_ms)||'|'||CAST(NEW.revoked AS TEXT)
    );
END;
CREATE TRIGGER authbus_frontier_policy_update
AFTER UPDATE ON authbus_policy
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'policy', 'upsert', NEW.policy_id,
        hex(CAST(NEW.policy_id AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(CAST(NEW.action AS BLOB))||'|'||hex(NEW.scope_digest)||'|'||
        hex(CAST(NEW.effect AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.not_before_ms)||'|'||hex(NEW.expires_at_ms)||'|'||CAST(NEW.revoked AS TEXT)
    );
END;
CREATE TRIGGER authbus_frontier_policy_delete
AFTER DELETE ON authbus_policy
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'policy', 'delete', OLD.policy_id,
        hex(CAST(OLD.policy_id AS BLOB))||'|'||hex(CAST(OLD.principal AS BLOB))||'|'||
        hex(CAST(OLD.action AS BLOB))||'|'||hex(OLD.scope_digest)||'|'||
        hex(CAST(OLD.effect AS BLOB))||'|'||hex(OLD.revision)||'|'||
        hex(OLD.not_before_ms)||'|'||hex(OLD.expires_at_ms)||'|'||CAST(OLD.revoked AS TEXT)
    );
END;

CREATE TRIGGER authbus_frontier_policy_history_insert
AFTER INSERT ON authbus_policy_history
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'policy_history', 'upsert', NEW.policy_id||':'||hex(NEW.revision),
        hex(CAST(NEW.policy_id AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(CAST(NEW.action AS BLOB))||'|'||hex(NEW.scope_digest)||'|'||
        hex(CAST(NEW.effect AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.not_before_ms)||'|'||hex(NEW.expires_at_ms)||'|'||CAST(NEW.revoked AS TEXT)
    );
END;

CREATE TRIGGER authbus_frontier_policy_archive_insert
AFTER INSERT ON authbus_policy_archive
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'policy_archive', 'upsert', NEW.policy_id,
        hex(CAST(NEW.policy_id AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(CAST(NEW.action AS BLOB))||'|'||hex(NEW.scope_digest)||'|'||
        hex(CAST(NEW.effect AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.not_before_ms)||'|'||hex(NEW.expires_at_ms)||'|'||
        CAST(NEW.revoked AS TEXT)||'|'||hex(NEW.retired_at_ms)
    );
END;

CREATE TRIGGER authbus_frontier_quota_insert
AFTER INSERT ON authbus_quota_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'quota', 'upsert', NEW.quota_key,
        hex(CAST(NEW.quota_key AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(NEW.scope_digest)||'|'||hex(CAST(NEW.unit AS BLOB))||'|'||
        hex(CAST(NEW.period_id AS BLOB))||'|'||hex(NEW.limit_amount)||'|'||
        hex(NEW.available)||'|'||hex(NEW.reserved)||'|'||hex(NEW.consumed)||'|'||
        hex(NEW.revision)
    );
END;
CREATE TRIGGER authbus_frontier_quota_update
AFTER UPDATE ON authbus_quota_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'quota', 'upsert', NEW.quota_key,
        hex(CAST(NEW.quota_key AS BLOB))||'|'||hex(CAST(NEW.principal AS BLOB))||'|'||
        hex(NEW.scope_digest)||'|'||hex(CAST(NEW.unit AS BLOB))||'|'||
        hex(CAST(NEW.period_id AS BLOB))||'|'||hex(NEW.limit_amount)||'|'||
        hex(NEW.available)||'|'||hex(NEW.reserved)||'|'||hex(NEW.consumed)||'|'||
        hex(NEW.revision)
    );
END;
CREATE TRIGGER authbus_frontier_quota_delete
AFTER DELETE ON authbus_quota_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'quota', 'delete', OLD.quota_key,
        hex(CAST(OLD.quota_key AS BLOB))||'|'||hex(CAST(OLD.principal AS BLOB))||'|'||
        hex(OLD.scope_digest)||'|'||hex(CAST(OLD.unit AS BLOB))||'|'||
        hex(CAST(OLD.period_id AS BLOB))||'|'||hex(OLD.limit_amount)||'|'||
        hex(OLD.available)||'|'||hex(OLD.reserved)||'|'||hex(OLD.consumed)||'|'||
        hex(OLD.revision)
    );
END;

CREATE TRIGGER authbus_frontier_reservation_insert
AFTER INSERT ON authbus_quota_reservation
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'reservation', 'upsert', NEW.reservation_id,
        hex(CAST(NEW.reservation_id AS BLOB))||'|'||hex(CAST(NEW.operation_id AS BLOB))||'|'||
        hex(CAST(NEW.quota_key AS BLOB))||'|'||hex(CAST(NEW.period_id AS BLOB))||'|'||
        hex(CAST(NEW.principal AS BLOB))||'|'||hex(NEW.amount)||'|'||
        hex(NEW.effect_digest)||'|'||hex(CAST(NEW.policy_id AS BLOB))||'|'||
        hex(NEW.policy_revision)||'|'||hex(NEW.policy_decision_digest)||'|'||
        hex(CAST(NEW.state AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.expires_at_ms)||'|'||hex(NEW.created_at_ms)||'|'||hex(NEW.updated_at_ms)||'|'||
        COALESCE(hex(NEW.dispatch_digest),'-')||'|'||
        COALESCE(hex(NEW.terminal_evidence),'-')||'|'||
        COALESCE(hex(NEW.observed_cost),'-')||'|'||
        COALESCE(hex(NEW.settlement_digest),'-')
    );
END;
CREATE TRIGGER authbus_frontier_reservation_update
AFTER UPDATE ON authbus_quota_reservation
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'reservation', 'upsert', NEW.reservation_id,
        hex(CAST(NEW.reservation_id AS BLOB))||'|'||hex(CAST(NEW.operation_id AS BLOB))||'|'||
        hex(CAST(NEW.quota_key AS BLOB))||'|'||hex(CAST(NEW.period_id AS BLOB))||'|'||
        hex(CAST(NEW.principal AS BLOB))||'|'||hex(NEW.amount)||'|'||
        hex(NEW.effect_digest)||'|'||hex(CAST(NEW.policy_id AS BLOB))||'|'||
        hex(NEW.policy_revision)||'|'||hex(NEW.policy_decision_digest)||'|'||
        hex(CAST(NEW.state AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.expires_at_ms)||'|'||hex(NEW.created_at_ms)||'|'||hex(NEW.updated_at_ms)||'|'||
        COALESCE(hex(NEW.dispatch_digest),'-')||'|'||
        COALESCE(hex(NEW.terminal_evidence),'-')||'|'||
        COALESCE(hex(NEW.observed_cost),'-')||'|'||
        COALESCE(hex(NEW.settlement_digest),'-')
    );
END;
CREATE TRIGGER authbus_frontier_reservation_delete
AFTER DELETE ON authbus_quota_reservation
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'reservation', 'delete', OLD.reservation_id,
        hex(CAST(OLD.reservation_id AS BLOB))||'|'||hex(CAST(OLD.operation_id AS BLOB))||'|'||
        hex(CAST(OLD.quota_key AS BLOB))||'|'||hex(CAST(OLD.period_id AS BLOB))||'|'||
        hex(CAST(OLD.principal AS BLOB))||'|'||hex(OLD.amount)||'|'||
        hex(OLD.effect_digest)||'|'||hex(CAST(OLD.policy_id AS BLOB))||'|'||
        hex(OLD.policy_revision)||'|'||hex(OLD.policy_decision_digest)||'|'||
        hex(CAST(OLD.state AS BLOB))||'|'||hex(OLD.revision)||'|'||
        hex(OLD.expires_at_ms)||'|'||hex(OLD.created_at_ms)||'|'||hex(OLD.updated_at_ms)||'|'||
        COALESCE(hex(OLD.dispatch_digest),'-')||'|'||
        COALESCE(hex(OLD.terminal_evidence),'-')||'|'||
        COALESCE(hex(OLD.observed_cost),'-')||'|'||
        COALESCE(hex(OLD.settlement_digest),'-')
    );
END;

CREATE TRIGGER authbus_frontier_reservation_archive_insert
AFTER INSERT ON authbus_quota_reservation_archive
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'reservation_archive', 'upsert', NEW.reservation_id,
        hex(CAST(NEW.reservation_id AS BLOB))||'|'||hex(CAST(NEW.operation_id AS BLOB))||'|'||
        hex(CAST(NEW.quota_key AS BLOB))||'|'||hex(CAST(NEW.period_id AS BLOB))||'|'||
        hex(CAST(NEW.principal AS BLOB))||'|'||hex(NEW.amount)||'|'||
        hex(NEW.effect_digest)||'|'||hex(CAST(NEW.policy_id AS BLOB))||'|'||
        hex(NEW.policy_revision)||'|'||hex(NEW.policy_decision_digest)||'|'||
        hex(CAST(NEW.state AS BLOB))||'|'||hex(NEW.revision)||'|'||
        hex(NEW.expires_at_ms)||'|'||hex(NEW.created_at_ms)||'|'||hex(NEW.updated_at_ms)||'|'||
        COALESCE(hex(NEW.dispatch_digest),'-')||'|'||
        COALESCE(hex(NEW.terminal_evidence),'-')||'|'||
        COALESCE(hex(NEW.observed_cost),'-')||'|'||
        COALESCE(hex(NEW.settlement_digest),'-')||'|'||hex(NEW.archived_at_ms)
    );
END;

CREATE TRIGGER authbus_frontier_issuer_insert
AFTER INSERT ON authbus_issuer_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'issuer', 'upsert', NEW.issuer_id||'|'||NEW.purpose||'|'||hex(NEW.key_epoch),
        hex(CAST(NEW.issuer_id AS BLOB))||'|'||hex(CAST(NEW.purpose AS BLOB))||'|'||
        hex(NEW.key_epoch)||'|'||hex(NEW.public_key)||'|'||
        hex(CAST(NEW.state AS BLOB))||'|'||hex(NEW.revision)
    );
END;
CREATE TRIGGER authbus_frontier_issuer_update
AFTER UPDATE ON authbus_issuer_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'issuer', 'upsert', NEW.issuer_id||'|'||NEW.purpose||'|'||hex(NEW.key_epoch),
        hex(CAST(NEW.issuer_id AS BLOB))||'|'||hex(CAST(NEW.purpose AS BLOB))||'|'||
        hex(NEW.key_epoch)||'|'||hex(NEW.public_key)||'|'||
        hex(CAST(NEW.state AS BLOB))||'|'||hex(NEW.revision)
    );
END;
CREATE TRIGGER authbus_frontier_issuer_delete
AFTER DELETE ON authbus_issuer_registry
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'issuer', 'delete', OLD.issuer_id||'|'||OLD.purpose||'|'||hex(OLD.key_epoch),
        hex(CAST(OLD.issuer_id AS BLOB))||'|'||hex(CAST(OLD.purpose AS BLOB))||'|'||
        hex(OLD.key_epoch)||'|'||hex(OLD.public_key)||'|'||
        hex(CAST(OLD.state AS BLOB))||'|'||hex(OLD.revision)
    );
END;
