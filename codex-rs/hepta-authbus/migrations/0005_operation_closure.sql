-- An absence read is not a durable negative fact. Serialize closure with reserve.
-- This is a tombstone, not a synthetic reservation or a source of authority.
CREATE TABLE authbus_operation_closure (
    operation_id TEXT PRIMARY KEY,
    effect_digest BLOB NOT NULL CHECK (length(effect_digest) = 32 AND effect_digest != zeroblob(32)),
    closed_at_ms BLOB NOT NULL CHECK (length(closed_at_ms) = 8)
) WITHOUT ROWID;

CREATE TRIGGER authbus_operation_closure_immutable_update
BEFORE UPDATE ON authbus_operation_closure
BEGIN SELECT RAISE(ABORT, 'operation closure is immutable'); END;
CREATE TRIGGER authbus_operation_closure_immutable_delete
BEFORE DELETE ON authbus_operation_closure
BEGIN SELECT RAISE(ABORT, 'operation closure must be retained'); END;
CREATE TRIGGER authbus_operation_closure_no_reservation
BEFORE INSERT ON authbus_operation_closure
WHEN EXISTS(SELECT 1 FROM authbus_quota_reservation WHERE operation_id = NEW.operation_id)
  OR EXISTS(SELECT 1 FROM authbus_quota_reservation_archive WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation already has a reservation'); END;
CREATE TRIGGER authbus_operation_closure_capacity
BEFORE INSERT ON authbus_operation_closure
WHEN (SELECT count(*) FROM authbus_operation_closure) >= 65536
BEGIN SELECT RAISE(ABORT, 'operation closure capacity exceeded'); END;
CREATE TRIGGER authbus_reservation_no_closed_operation
BEFORE INSERT ON authbus_quota_reservation
WHEN EXISTS(SELECT 1 FROM authbus_operation_closure WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation has been closed'); END;
CREATE TRIGGER authbus_archive_no_closed_operation
BEFORE INSERT ON authbus_quota_reservation_archive
WHEN EXISTS(SELECT 1 FROM authbus_operation_closure WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation has been closed'); END;
CREATE TRIGGER authbus_dirty_operation_closure
AFTER INSERT ON authbus_operation_closure
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
