-- The original step-attempt trigger advanced only when the scheduler generation
-- changed. A provider-proven safe retry can reuse the same Agent generation
-- with a fresh lease token, so attempt rollover now belongs to the lifecycle
-- transaction that can inspect whether the previous attempt has durable step
-- history. Removing the trigger prevents double increments on generation
-- takeover and keeps one durable attempt per actual dispatch boundary.
DROP TRIGGER IF EXISTS automation_occurrence_step_attempt_on_reclaim;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 10 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
