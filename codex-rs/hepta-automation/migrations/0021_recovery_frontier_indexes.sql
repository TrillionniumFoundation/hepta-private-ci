-- Preserve schema 20's published checksum while bounding the unknown frontier.
-- Select the indexed dispatch key, not an equivalent joined key that can force
-- SQLite to sort the full retained dispatch history for each new sweep.
CREATE INDEX automation_dispatch_recovery_identity
ON automation_dispatch_outcomes (task_id, occurrence)
WHERE outcome = 'uncertain';
DROP VIEW automation_recovery_frontier;
CREATE VIEW automation_recovery_frontier AS
SELECT 'unknown' AS lane, t.owner_agent_id, d.task_id, d.occurrence
FROM automation_dispatch_outcomes d
JOIN automation_runs r ON r.task_id = d.task_id AND r.occurrence = d.occurrence
JOIN automation_tasks t ON t.task_id = d.task_id
WHERE d.outcome = 'uncertain'
UNION ALL
SELECT 'terminal' AS lane, owner_agent_id, task_id, occurrence
FROM automation_occurrence_lifecycle
WHERE state IN ('admitted', 'running', 'indeterminate');
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
