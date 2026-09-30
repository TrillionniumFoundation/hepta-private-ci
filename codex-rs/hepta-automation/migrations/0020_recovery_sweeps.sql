-- Polling progress is not occurrence state, an absence proof or dispatch authority.
-- Preserve every historical V1 row and all existing migration checksums.
CREATE TABLE automation_recovery_sweeps (
    lane TEXT PRIMARY KEY CHECK (lane IN ('unknown', 'terminal')),
    sweep_generation INTEGER NOT NULL DEFAULT 0 CHECK (sweep_generation >= 0),
    after_task_id TEXT NOT NULL DEFAULT '',
    after_occurrence INTEGER NOT NULL DEFAULT 0 CHECK (after_occurrence >= 0),
    upper_task_id TEXT NOT NULL DEFAULT '',
    upper_occurrence INTEGER NOT NULL DEFAULT 0 CHECK (upper_occurrence >= 0),
    CHECK (
        (upper_task_id = '' AND upper_occurrence = 0
            AND after_task_id = '' AND after_occurrence = 0)
        OR (length(upper_task_id) = 36 AND upper_occurrence > 0
            AND ((after_task_id = '' AND after_occurrence = 0)
                OR (length(after_task_id) = 36 AND after_occurrence > 0
                    AND (after_task_id, after_occurrence) <= (upper_task_id, upper_occurrence))))
    )
);
INSERT INTO automation_recovery_sweeps (lane) VALUES ('unknown'), ('terminal');
CREATE TRIGGER automation_recovery_sweeps_no_delete
BEFORE DELETE ON automation_recovery_sweeps
BEGIN
    SELECT RAISE(ABORT, 'recovery sweep rows are permanent');
END;
CREATE TRIGGER automation_recovery_sweeps_monotone
BEFORE UPDATE ON automation_recovery_sweeps
WHEN NEW.lane != OLD.lane
    OR NEW.sweep_generation < OLD.sweep_generation
    OR NEW.sweep_generation > OLD.sweep_generation + 1
    OR (NEW.sweep_generation = OLD.sweep_generation AND (
        NEW.upper_task_id != OLD.upper_task_id
        OR NEW.upper_occurrence != OLD.upper_occurrence
        OR (NEW.after_task_id, NEW.after_occurrence) < (OLD.after_task_id, OLD.after_occurrence)
    ))
BEGIN
    SELECT RAISE(ABORT, 'recovery sweep rewound or changed its frozen frontier');
END;
CREATE INDEX automation_occurrence_recovery_identity
ON automation_occurrence_lifecycle (owner_agent_id, task_id, occurrence)
WHERE state IN ('admitted', 'running', 'indeterminate');
CREATE VIEW automation_recovery_frontier AS
SELECT 'unknown' AS lane, t.owner_agent_id, r.task_id, r.occurrence
FROM automation_dispatch_outcomes d
JOIN automation_runs r ON r.task_id = d.task_id AND r.occurrence = d.occurrence
JOIN automation_tasks t ON t.task_id = r.task_id
WHERE d.outcome = 'uncertain'
UNION ALL
SELECT 'terminal' AS lane, owner_agent_id, task_id, occurrence
FROM automation_occurrence_lifecycle
WHERE state IN ('admitted', 'running', 'indeterminate');
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
