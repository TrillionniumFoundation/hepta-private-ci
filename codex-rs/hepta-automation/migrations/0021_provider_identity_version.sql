-- Historical attempts must recover under the provider key they dispatched.
-- New attempts explicitly persist version 2, which frames owner/run/step.
ALTER TABLE taskflow_effect_dispatch_attempts
ADD COLUMN provider_key_version INTEGER NOT NULL DEFAULT 1
CHECK (provider_key_version IN (1, 2));

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
