-- Provider-backed effects are a separate lineage from model invocation
-- terminals.  An invocation response is not an effect acknowledgement: the
-- latter must be bound to the occurrence key and exact payload digest.
CREATE TABLE provider_effect_intents (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    effect_key TEXT NOT NULL UNIQUE,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64
        AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL
);

CREATE TABLE provider_effect_acknowledgements (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    effect_key TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    provider_operation_id_sha256 TEXT NOT NULL CHECK (
        length(provider_operation_id_sha256) = 64
        AND provider_operation_id_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'rejected')),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64
        AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    FOREIGN KEY(effect_key)
        REFERENCES provider_effect_intents(effect_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE(effect_key, provider_operation_id_sha256, status, payload_sha256)
);

-- Unknown outcomes are first-class durable quarantine observations.  They are
-- not ACKs and can never be interpreted as provider success or rejection.
CREATE TABLE provider_effect_uncertainties (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    effect_key TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    reason_code TEXT NOT NULL CHECK (
        length(reason_code) BETWEEN 1 AND 128
        AND reason_code NOT GLOB '*[^a-z0-9_.-]*'
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64
        AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    FOREIGN KEY(effect_key)
        REFERENCES provider_effect_intents(effect_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE(effect_key, payload_sha256, reason_code)
);

CREATE INDEX provider_effect_intents_seq
    ON provider_effect_intents(effect_key, seq);

CREATE INDEX provider_effect_acknowledgements_key_seq
    ON provider_effect_acknowledgements(effect_key, seq);

CREATE INDEX provider_effect_uncertainties_key_seq
    ON provider_effect_uncertainties(effect_key, seq);

CREATE TRIGGER provider_effect_intents_no_update
BEFORE UPDATE ON provider_effect_intents
BEGIN
    SELECT RAISE(ABORT, 'provider effect intents are immutable');
END;

CREATE TRIGGER provider_effect_intents_no_delete
BEFORE DELETE ON provider_effect_intents
BEGIN
    SELECT RAISE(ABORT, 'provider effect intents are immutable');
END;

CREATE TRIGGER provider_effect_acknowledgements_no_update
BEFORE UPDATE ON provider_effect_acknowledgements
BEGIN
    SELECT RAISE(ABORT, 'provider effect acknowledgements are immutable');
END;

CREATE TRIGGER provider_effect_acknowledgements_no_delete
BEFORE DELETE ON provider_effect_acknowledgements
BEGIN
    SELECT RAISE(ABORT, 'provider effect acknowledgements are immutable');
END;

CREATE TRIGGER provider_effect_uncertainties_no_update
BEFORE UPDATE ON provider_effect_uncertainties
BEGIN
    SELECT RAISE(ABORT, 'provider effect uncertainties are immutable');
END;

CREATE TRIGGER provider_effect_uncertainties_no_delete
BEFORE DELETE ON provider_effect_uncertainties
BEGIN
    SELECT RAISE(ABORT, 'provider effect uncertainties are immutable');
END;
