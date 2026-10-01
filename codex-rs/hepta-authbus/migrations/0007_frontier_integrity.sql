-- Integrity guards for the incremental authority frontier.
--
-- A clean accumulator is already named by the local checkpoint and therefore
-- cannot move independently. The one permitted clean transition is the
-- one-time seed of a migrated database: NULL -> the exact current checkpoint
-- digest with no pending changes and an unchanged applied sequence.
CREATE TRIGGER authbus_frontier_accumulator_clean_guard
BEFORE UPDATE OF root_digest, applied_change_id ON authbus_frontier_accumulator
WHEN EXISTS (
        SELECT 1 FROM authbus_authority_checkpoint WHERE singleton = 1
     )
 AND (SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton = 1) = 0
 AND (
        OLD.root_digest IS NOT NULL
        OR NEW.root_digest != (
            SELECT checkpoint_digest
            FROM authbus_authority_checkpoint
            WHERE singleton = 1
        )
        OR NEW.applied_change_id != OLD.applied_change_id
        OR EXISTS (
            SELECT 1 FROM authbus_frontier_change
            WHERE change_id > OLD.applied_change_id
        )
     )
BEGIN
    SELECT RAISE(ABORT, 'clean AuthBus frontier accumulator cannot diverge');
END;

-- Clearing the dirty frontier is the final local promotion step. It is legal
-- only when the durable accumulator equals the local checkpoint and every
-- journal event is covered by the applied sequence.
CREATE TRIGGER authbus_frontier_dirty_clear_guard
BEFORE UPDATE OF dirty ON authbus_authority_checkpoint_dirty
WHEN NEW.dirty = 0
 AND EXISTS (
        SELECT 1 FROM authbus_authority_checkpoint WHERE singleton = 1
     )
 AND (
        (SELECT root_digest
         FROM authbus_frontier_accumulator
         WHERE singleton = 1) IS NULL
        OR (SELECT root_digest
            FROM authbus_frontier_accumulator
            WHERE singleton = 1) !=
           (SELECT checkpoint_digest
            FROM authbus_authority_checkpoint
            WHERE singleton = 1)
        OR EXISTS (
            SELECT 1
            FROM authbus_frontier_change
            WHERE change_id > (
                SELECT applied_change_id
                FROM authbus_frontier_accumulator
                WHERE singleton = 1
            )
        )
     )
BEGIN
    SELECT RAISE(ABORT, 'AuthBus dirty frontier cannot clear before exact promotion');
END;

CREATE TRIGGER authbus_frontier_accumulator_identity_immutable
BEFORE UPDATE OF singleton, schema_version ON authbus_frontier_accumulator
BEGIN
    SELECT RAISE(ABORT, 'AuthBus frontier accumulator identity is immutable');
END;

CREATE TRIGGER authbus_frontier_accumulator_delete_forbidden
BEFORE DELETE ON authbus_frontier_accumulator
BEGIN
    SELECT RAISE(ABORT, 'AuthBus frontier accumulator cannot be deleted');
END;
