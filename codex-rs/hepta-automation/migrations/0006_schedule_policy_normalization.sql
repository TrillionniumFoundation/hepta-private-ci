-- Keep policy metadata canonical for readers: skip/coalesce do not consume a
-- catch-up budget. The initial v4 backfill used the default bounded ceiling in
-- this column for all policies; normalize existing rows and future inserts.
UPDATE automation_schedule_metadata
   SET max_catch_up_occurrences = 0, catch_up_remaining = 0
 WHERE missed_run_policy IN ('skip', 'coalesce');

CREATE TRIGGER automation_schedule_policy_normalize_insert
AFTER INSERT ON automation_schedule_metadata
WHEN NEW.missed_run_policy IN ('skip', 'coalesce')
     AND (NEW.max_catch_up_occurrences != 0 OR NEW.catch_up_remaining != 0)
BEGIN
    UPDATE automation_schedule_metadata
       SET max_catch_up_occurrences = 0, catch_up_remaining = 0
     WHERE task_id = NEW.task_id;
END;

CREATE TRIGGER automation_schedule_policy_normalize_update
AFTER UPDATE OF missed_run_policy, max_catch_up_occurrences
ON automation_schedule_metadata
WHEN NEW.missed_run_policy IN ('skip', 'coalesce')
     AND (NEW.max_catch_up_occurrences != 0 OR NEW.catch_up_remaining != 0)
BEGIN
    UPDATE automation_schedule_metadata
       SET max_catch_up_occurrences = 0, catch_up_remaining = 0
     WHERE task_id = NEW.task_id;
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 6 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
