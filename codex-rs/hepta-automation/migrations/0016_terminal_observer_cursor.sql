-- Persist bounded terminal-observer pagination progress so a known turn can
-- age beyond the recent 16x100 window without becoming permanently invisible.
-- Each Agentd recovery pass remains bounded; the next pass resumes from this
-- opaque App Server cursor. The cursor is recovery progress, not occurrence
-- identity or provider terminal evidence.
ALTER TABLE automation_occurrence_lifecycle
ADD COLUMN terminal_scan_cursor TEXT
    CHECK (
        terminal_scan_cursor IS NULL OR
        length(terminal_scan_cursor) BETWEEN 1 AND 2048
    );

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 16 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
