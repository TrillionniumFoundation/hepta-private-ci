-- Handoff retains an owner that can settle admitted work. Permanent retirement
-- does not: never install its tombstone while lifecycle settlement is pending.
CREATE TRIGGER automation_timer_lifecycle_terminal_drain
BEFORE UPDATE OF phase ON automation_timer_lifecycle
WHEN NEW.phase = 'retired' AND EXISTS (
    SELECT 1 FROM automation_occurrence_lifecycle
    WHERE state IN ('admitted', 'running', 'indeterminate')
)
BEGIN
    SELECT RAISE(ABORT, 'timer owner still has unsettled occurrences');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
