-- Durable round-robin recovery discovery for non-terminal occurrences.
-- The cursor is discovery progress only; it grants no execution, effect, or
-- terminal authority and never changes occurrence identity or outcome.
CREATE TABLE automation_occurrence_recovery_cursor (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    owner_agent_id TEXT NOT NULL,
    last_updated_at_ms INTEGER NOT NULL CHECK (last_updated_at_ms >= 0),
    last_task_id TEXT NOT NULL,
    last_occurrence INTEGER NOT NULL CHECK (last_occurrence > 0)
);

CREATE INDEX automation_occurrence_pending_rotation_idx
ON automation_occurrence_lifecycle (
    owner_agent_id, updated_at_ms, task_id, occurrence
)
WHERE state IN ('admitted', 'running', 'indeterminate');

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
