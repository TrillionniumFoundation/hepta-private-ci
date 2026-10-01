-- An authoritative absence is a mutation, not a SELECT result. Once sealed,
-- an operation can never be reserved, even by a cancelled/late reserve task.
CREATE TABLE authbus_operation_admission_fence (
    operation_id TEXT PRIMARY KEY,
    effect_digest BLOB NOT NULL CHECK(length(effect_digest) = 32)
) WITHOUT ROWID;
CREATE TRIGGER authbus_admission_fence_no_update
BEFORE UPDATE ON authbus_operation_admission_fence
BEGIN SELECT RAISE(ABORT, 'immutable operation admission fence'); END;
CREATE TRIGGER authbus_admission_fence_no_delete
BEFORE DELETE ON authbus_operation_admission_fence
BEGIN SELECT RAISE(ABORT, 'cannot forget operation admission fence'); END;
CREATE TRIGGER authbus_admission_fence_no_reservation
BEFORE INSERT ON authbus_operation_admission_fence
WHEN EXISTS(SELECT 1 FROM authbus_quota_reservation WHERE operation_id = NEW.operation_id)
 OR EXISTS(SELECT 1 FROM authbus_quota_reservation_archive WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation already has a reservation'); END;
CREATE TRIGGER authbus_reservation_admission_fenced
BEFORE INSERT ON authbus_quota_reservation
WHEN EXISTS(SELECT 1 FROM authbus_operation_admission_fence WHERE operation_id = NEW.operation_id)
BEGIN SELECT RAISE(ABORT, 'operation admission is fenced'); END;
CREATE TRIGGER authbus_dirty_admission_fence AFTER INSERT ON authbus_operation_admission_fence
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
