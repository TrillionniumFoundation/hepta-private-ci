-- Additive Calendar V2 schedule history. Existing Once/FixedInterval rows retain
-- their original schema and meaning. The current schedule revision in
-- automation_schedule_metadata points at exactly one append-only calendar
-- version when a task uses the V2 calendar surface.
CREATE TABLE automation_calendar_schedule_versions (
    task_id TEXT NOT NULL REFERENCES automation_tasks(task_id),
    owner_agent_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    schedule_json TEXT NOT NULL CHECK (length(schedule_json) BETWEEN 2 AND 262144),
    schedule_digest TEXT NOT NULL CHECK (
        length(schedule_digest) = 64 AND schedule_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY(task_id, revision)
);

CREATE INDEX automation_calendar_schedule_owner_revision_idx
    ON automation_calendar_schedule_versions(owner_agent_id, task_id, revision);

CREATE TRIGGER automation_calendar_schedule_versions_no_update
BEFORE UPDATE ON automation_calendar_schedule_versions
BEGIN
    SELECT RAISE(ABORT, 'calendar schedule versions are immutable');
END;

CREATE TRIGGER automation_calendar_schedule_versions_no_delete
BEFORE DELETE ON automation_calendar_schedule_versions
BEGIN
    SELECT RAISE(ABORT, 'calendar schedule versions are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 12 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
