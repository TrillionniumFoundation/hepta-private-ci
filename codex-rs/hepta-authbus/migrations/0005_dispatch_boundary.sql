-- Persist the physical dispatch boundary separately from later state changes.
-- Existing dispatch_attempted rows have an exact boundary in updated_at_ms.
-- Legacy indeterminate and terminal rows cannot be reconstructed safely and
-- remain NULL. Indeterminate settlement fails closed; terminal rows remain
-- readable for exact retry and compaction.
ALTER TABLE authbus_quota_reservation
    ADD COLUMN dispatched_at_ms BLOB
    CHECK (dispatched_at_ms IS NULL OR length(dispatched_at_ms) = 8);

ALTER TABLE authbus_quota_reservation_archive
    ADD COLUMN dispatched_at_ms BLOB
    CHECK (dispatched_at_ms IS NULL OR length(dispatched_at_ms) = 8);

UPDATE authbus_quota_reservation
SET dispatched_at_ms = updated_at_ms
WHERE state = 'dispatch_attempted';

-- A new row must encode whether physical dispatch has occurred. The timestamp
-- is written exactly once with Held -> DispatchAttempted. Pre-0005 rows are
-- retained as-is because this trigger is installed after migration.
CREATE TRIGGER authbus_reservation_dispatch_boundary_insert
BEFORE INSERT ON authbus_quota_reservation
WHEN (NEW.state IN ('held', 'cancelled', 'expired')
      AND NEW.dispatched_at_ms IS NOT NULL)
  OR (NEW.state IN ('dispatch_attempted', 'indeterminate', 'settled', 'released')
      AND NEW.dispatched_at_ms IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation dispatch boundary');
END;

CREATE TRIGGER authbus_reservation_dispatch_boundary_update
BEFORE UPDATE ON authbus_quota_reservation
WHEN (NEW.state IN ('held', 'cancelled', 'expired')
      AND NEW.dispatched_at_ms IS NOT NULL)
  OR (NEW.state IN ('dispatch_attempted', 'indeterminate', 'settled', 'released')
      AND NEW.dispatched_at_ms IS NULL)
  OR (OLD.dispatched_at_ms IS NOT NULL
      AND NEW.dispatched_at_ms IS NOT OLD.dispatched_at_ms)
  OR (OLD.dispatched_at_ms IS NULL
      AND NEW.dispatched_at_ms IS NOT NULL
      AND NOT (OLD.state = 'held' AND NEW.state = 'dispatch_attempted'))
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus reservation dispatch boundary');
END;

-- The frontier serialization gains dispatched_at_ms in this migration. Even an
-- otherwise empty database must publish a successor checkpoint before the new
-- digest format is considered current.
UPDATE authbus_authority_checkpoint_dirty
SET dirty = 1
WHERE singleton = 1
  AND EXISTS (SELECT 1 FROM authbus_authority_checkpoint WHERE singleton = 1);

-- Keep the old digest dialect until its outstanding witness is reconciled.
ALTER TABLE authbus_authority_checkpoint ADD COLUMN frontier_version INTEGER NOT NULL DEFAULT 1 CHECK (frontier_version IN (1, 2));
