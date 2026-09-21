-- A materialized occurrence owns the exact schedule revision it was born
-- under. Do not allow policy/revision mutation while any occurrence for that
-- task is non-terminal; otherwise a crash/reclaim could try to recompute the
-- old occurrence under new schedule bytes.
CREATE TRIGGER automation_schedule_policy_no_inflight_update
BEFORE UPDATE OF revision, missed_run_policy, max_catch_up_occurrences, overlap_policy
ON automation_schedule_metadata
WHEN EXISTS (
    SELECT 1 FROM automation_occurrence_lifecycle o
     WHERE o.task_id = NEW.task_id
       AND o.state IN ('claimed', 'admitted', 'running', 'indeterminate')
)
BEGIN
    SELECT RAISE(ABORT, 'automation schedule revision is frozen while an occurrence is active');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 7 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
