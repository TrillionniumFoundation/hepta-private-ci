-- Preserve the effect-entry instant independently of later lifecycle updates.
-- Historical indeterminate rows have no recoverable dispatch instant. They
-- retain the old, conservative updated_at_ms settlement bound; never invent a
-- pre-dispatch timestamp during migration or recreate historical authority.
CREATE TABLE authbus_dispatch_observation (
    reservation_id TEXT PRIMARY KEY,
    dispatched_at_ms BLOB NOT NULL CHECK (
        typeof(dispatched_at_ms) = 'blob' AND length(dispatched_at_ms) = 8
        AND dispatched_at_ms > X'0000000000000000'
    )
) WITHOUT ROWID;

CREATE TRIGGER authbus_dispatch_observation_insert_guard
BEFORE INSERT ON authbus_dispatch_observation
WHEN EXISTS (
    SELECT 1 FROM authbus_dispatch_observation
    WHERE reservation_id = NEW.reservation_id
) OR NOT EXISTS (
    SELECT 1 FROM authbus_quota_reservation
    WHERE reservation_id = NEW.reservation_id
      AND state = 'dispatch_attempted'
      AND dispatch_digest = effect_digest
      AND updated_at_ms = NEW.dispatched_at_ms
)
BEGIN SELECT RAISE(ABORT, 'dispatch observation must match effect entry'); END;

CREATE TRIGGER authbus_dispatch_observation_immutable_update
BEFORE UPDATE ON authbus_dispatch_observation
BEGIN SELECT RAISE(ABORT, 'dispatch observation is immutable'); END;

CREATE TRIGGER authbus_dispatch_observation_immutable_delete
BEFORE DELETE ON authbus_dispatch_observation
BEGIN SELECT RAISE(ABORT, 'dispatch observation is immutable'); END;

CREATE TRIGGER authbus_reservation_record_dispatch
AFTER UPDATE OF state ON authbus_quota_reservation
WHEN OLD.state = 'held' AND NEW.state = 'dispatch_attempted'
BEGIN
    INSERT INTO authbus_dispatch_observation(reservation_id, dispatched_at_ms)
    VALUES (NEW.reservation_id, NEW.updated_at_ms);
END;

CREATE TRIGGER authbus_frontier_dispatch_observation_insert
AFTER INSERT ON authbus_dispatch_observation
BEGIN
    INSERT INTO authbus_frontier_change(domain, operation, record_key, canonical_record)
    VALUES (
        'dispatch_observation', 'upsert', NEW.reservation_id,
        hex(CAST(NEW.reservation_id AS BLOB))||'|'||hex(NEW.dispatched_at_ms)
    );
    UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1;
END;
