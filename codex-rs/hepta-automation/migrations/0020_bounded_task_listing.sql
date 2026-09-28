-- Preserve every historical migration and every task/occurrence. Keyset reads
-- need this creation-order index; no offset or whole-history copy is required.
CREATE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms, task_id);
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
