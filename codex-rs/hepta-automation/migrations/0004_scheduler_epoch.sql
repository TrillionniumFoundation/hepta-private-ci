-- A scheduler generation is a monotone owner-local fence, not a capability.
-- The Agentd writer lock and current Fleet identity are still mandatory.
-- Seed from live legacy leases so an upgrade never admits an older scheduler.
CREATE TABLE automation_scheduler_epoch (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL CHECK (typeof(generation) = 'integer' AND generation >= 0)
);
INSERT INTO automation_scheduler_epoch (singleton, generation)
SELECT 1, COALESCE(MAX(lease_generation), 0) FROM automation_runs;

CREATE TRIGGER automation_scheduler_epoch_no_regression
BEFORE UPDATE ON automation_scheduler_epoch
WHEN NEW.singleton != OLD.singleton OR NEW.generation < OLD.generation
BEGIN
    SELECT RAISE(ABORT, 'automation scheduler generation cannot regress');
END;
CREATE TRIGGER automation_scheduler_epoch_no_delete
BEFORE DELETE ON automation_scheduler_epoch
BEGIN
    SELECT RAISE(ABORT, 'automation scheduler generation cannot be deleted');
END;

-- Old binaries must reject this store rather than omit the new write fence.
-- SQLx applies the migration and this version advance in one transaction.
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
