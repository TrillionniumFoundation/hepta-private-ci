-- Recovery must use the provider configuration selected before contact.
-- NULL preserves legacy/generic adapter semantics; immutability triggers on
-- the attempt table also protect this new column against replacement.
ALTER TABLE taskflow_effect_dispatch_attempts
ADD COLUMN provider_contract_binding TEXT CHECK (
    provider_contract_binding IS NULL OR (
        length(provider_contract_binding) = 64
        AND provider_contract_binding NOT GLOB '*[^0-9a-f]*'
        AND provider_contract_binding !=
            '0000000000000000000000000000000000000000000000000000000000000000'
    )
);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
