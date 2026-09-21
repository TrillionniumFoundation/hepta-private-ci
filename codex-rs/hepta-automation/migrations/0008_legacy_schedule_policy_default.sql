-- Preserve the existing `create_task` scheduler contract while making the
-- overlap decision explicit. Legacy callers historically advanced the next
-- timer after durable Core admission, so their canonical default is `allow`.
-- Callers that require serial/terminally-gated recurrence set `forbid` before
-- the first occurrence is materialized.
UPDATE automation_schedule_metadata
   SET overlap_policy = 'allow'
 WHERE revision = 1
   AND NOT EXISTS (
       SELECT 1 FROM automation_occurrence_lifecycle o
        WHERE o.task_id = automation_schedule_metadata.task_id
   );

CREATE TRIGGER automation_task_default_policy
AFTER INSERT ON automation_tasks
BEGIN
    INSERT OR IGNORE INTO automation_schedule_metadata (
        task_id, owner_agent_id, revision, missed_run_policy,
        max_catch_up_occurrences, catch_up_remaining, overlap_policy,
        created_at_ms, updated_at_ms
    ) VALUES (
        NEW.task_id, NEW.owner_agent_id, 1, 'skip', 0, 0, 'allow',
        NEW.created_at_ms, NEW.updated_at_ms
    );
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 8 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
