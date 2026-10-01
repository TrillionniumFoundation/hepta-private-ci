-- Freeze the exact provider key before contact. Existing NULL identities
-- retain their original unscoped run/step identity and require independent
-- owner-isolation evidence; they must never be silently upgraded or replayed.
ALTER TABLE taskflow_effect_dispatch_attempts ADD COLUMN provider_effect_key TEXT
    CHECK (provider_effect_key IS NULL OR (
        length(provider_effect_key) = 83
        AND substr(provider_effect_key, 1, 19) = 'provider-effect:v1:'
        AND substr(provider_effect_key, 20) NOT GLOB '*[^0-9a-f]*'
    ));

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
