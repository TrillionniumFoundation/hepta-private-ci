-- Bind the actual key before provider contact. NULL means a legacy/custom
-- driver whose lookup identity cannot safely be inferred by the generic bridge.
ALTER TABLE taskflow_effect_dispatch_attempts ADD COLUMN provider_key TEXT
    CHECK(provider_key IS NULL OR (length(provider_key) = 83 AND provider_key LIKE 'provider-effect:v1:%'));

-- Observation discovery only: never changes provider or occurrence identity.
CREATE TABLE automation_dispatch_recovery_cursor (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    owner_agent_id TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL CHECK(observed_at_ms >= 0),
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK(occurrence > 0)
);
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 23 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
