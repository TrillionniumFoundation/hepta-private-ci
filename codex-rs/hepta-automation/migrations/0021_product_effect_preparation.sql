-- Immutable product preparation for final-use-authorized TaskFlow effects.
CREATE TABLE automation_product_effect_preparations (
    owner_agent_id TEXT NOT NULL,
    operation_id TEXT NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 256),
    run_id TEXT NOT NULL CHECK (length(run_id) BETWEEN 1 AND 256),
    step_id TEXT NOT NULL CHECK (length(step_id) BETWEEN 1 AND 256),
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 32),
    intent_json TEXT NOT NULL CHECK (length(intent_json) BETWEEN 2 AND 65536),
    intent_digest TEXT NOT NULL CHECK (length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
    provider_scope TEXT NOT NULL CHECK(length(provider_scope) BETWEEN 1 AND 128),
    preparation_digest TEXT NOT NULL CHECK(length(preparation_digest) = 64),
    provider_key TEXT NOT NULL CHECK (length(provider_key) BETWEEN 1 AND 256),
    provider_profile_digest TEXT NOT NULL CHECK (length(provider_profile_digest) = 64 AND provider_profile_digest NOT GLOB '*[^0-9a-f]*'),
    definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64 AND definition_digest NOT GLOB '*[^0-9a-f]*'),
    prepared_generation INTEGER NOT NULL CHECK (prepared_generation > 0),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    lease_deadline_ms INTEGER NOT NULL CHECK(lease_deadline_ms > prepared_at_ms),
    PRIMARY KEY(owner_agent_id, operation_id, attempt),
    UNIQUE(owner_agent_id, run_id, step_id, attempt)
);
CREATE INDEX automation_product_effect_attempt_lookup
ON automation_product_effect_preparations(owner_agent_id, run_id, step_id, attempt);
CREATE TRIGGER automation_product_effect_preparations_no_update
BEFORE UPDATE ON automation_product_effect_preparations BEGIN
    SELECT RAISE(ABORT, 'product effect preparations are immutable');
END;
CREATE TRIGGER automation_product_effect_preparations_no_delete
BEFORE DELETE ON automation_product_effect_preparations BEGIN
    SELECT RAISE(ABORT, 'product effect preparations are immutable');
END;
CREATE TABLE automation_product_effect_ready (
    owner_agent_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 32),
    preparation_digest TEXT NOT NULL,
    PRIMARY KEY(owner_agent_id, operation_id, attempt),
    FOREIGN KEY(owner_agent_id, operation_id, attempt)
        REFERENCES automation_product_effect_preparations(owner_agent_id, operation_id, attempt)
);
CREATE TRIGGER automation_product_effect_ready_no_update BEFORE UPDATE ON automation_product_effect_ready BEGIN
    SELECT RAISE(ABORT, 'product effect readiness is immutable');
END;
CREATE TRIGGER automation_product_effect_ready_no_delete BEFORE DELETE ON automation_product_effect_ready BEGIN
    SELECT RAISE(ABORT, 'product effect readiness is immutable');
END;
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
