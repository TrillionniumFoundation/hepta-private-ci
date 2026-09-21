-- Distinguish an idle catch-up budget from an exhausted active catch-up
-- window. `catch_up_remaining = 0` alone is ambiguous for max_occurrences=1
-- and across process restart.
ALTER TABLE automation_schedule_metadata
ADD COLUMN catch_up_active INTEGER NOT NULL DEFAULT 0
    CHECK (catch_up_active IN (0, 1));

CREATE TRIGGER automation_schedule_policy_clear_catch_up_state
AFTER UPDATE OF missed_run_policy ON automation_schedule_metadata
WHEN NEW.missed_run_policy != 'catch_up'
BEGIN
    UPDATE automation_schedule_metadata
       SET catch_up_active = 0, catch_up_remaining = 0
     WHERE task_id = NEW.task_id;
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 9 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
