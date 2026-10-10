-- Preserve exact recovery material for every new final-use-authorized effect.
-- Existing pre-v20 rows remain readable with NULL recovery material and retain
-- their original digest-only, no-redispatch semantics.
ALTER TABLE taskflow_effect_dispatch_attempts
    ADD COLUMN provider_effect_key TEXT CHECK (
        provider_effect_key IS NULL OR (
            length(provider_effect_key) = 83
            AND substr(provider_effect_key, 1, 19) = 'provider-effect:v1:'
            AND substr(provider_effect_key, 20) NOT GLOB '*[^0-9a-f]*'
        )
    );

ALTER TABLE taskflow_effect_dispatch_attempts
    ADD COLUMN wire_payload BLOB CHECK (
        wire_payload IS NULL OR (
            typeof(wire_payload) = 'blob'
            AND length(wire_payload) BETWEEN 1 AND 65536
        )
    );

-- From schema v20 onward, every newly created provider-contact barrier must
-- carry both exact materials in the same INSERT as the immutable attempt row.
CREATE TRIGGER taskflow_effect_dispatch_attempts_require_recovery_material
BEFORE INSERT ON taskflow_effect_dispatch_attempts
WHEN NEW.provider_effect_key IS NULL OR NEW.wire_payload IS NULL
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch recovery material is required');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
