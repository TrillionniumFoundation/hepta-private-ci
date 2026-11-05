-- Logical effect identity remains in provider_effect_intents. A later
-- observation of that same operation is not necessarily the same journal
-- event: source changes and observations after uncertainty must be retained.
-- Preserve every original byte, sequence and allocator high-water mark;
-- only serialized append code decides whether the latest event is a retry.
CREATE TABLE provider_effect_acknowledgements_observations (
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
    source TEXT CHECK (
        source IS NULL
        OR source IN ('dispatch_response', 'status_lookup')
    ),
    FOREIGN KEY(effect_key)
        REFERENCES provider_effect_intents(effect_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
INSERT INTO provider_effect_acknowledgements_observations (
    seq, effect_key, payload_sha256, provider_operation_id_sha256,
    status, schema_version, payload_json, record_sha256, recorded_at_ms, source
)
SELECT seq, effect_key, payload_sha256, provider_operation_id_sha256,
       status, schema_version, payload_json, record_sha256, recorded_at_ms, source
FROM provider_effect_acknowledgements ORDER BY seq;
INSERT INTO sqlite_sequence(name, seq)
SELECT 'provider_effect_acknowledgements_observations', 0
WHERE NOT EXISTS (
    SELECT 1 FROM sqlite_sequence
    WHERE name = 'provider_effect_acknowledgements_observations'
);
UPDATE sqlite_sequence
SET seq = max(seq, coalesce((
    SELECT seq FROM sqlite_sequence WHERE name = 'provider_effect_acknowledgements'
), 0))
WHERE name = 'provider_effect_acknowledgements_observations';
DROP TABLE provider_effect_acknowledgements;
ALTER TABLE provider_effect_acknowledgements_observations
RENAME TO provider_effect_acknowledgements;
CREATE INDEX provider_effect_acknowledgements_key_seq
    ON provider_effect_acknowledgements(effect_key, seq);
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

CREATE TABLE provider_effect_uncertainties_observations (
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
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
INSERT INTO provider_effect_uncertainties_observations (
    seq, effect_key, payload_sha256, reason_code,
    schema_version, payload_json, record_sha256, recorded_at_ms
)
SELECT seq, effect_key, payload_sha256, reason_code,
       schema_version, payload_json, record_sha256, recorded_at_ms
FROM provider_effect_uncertainties ORDER BY seq;
INSERT INTO sqlite_sequence(name, seq)
SELECT 'provider_effect_uncertainties_observations', 0
WHERE NOT EXISTS (
    SELECT 1 FROM sqlite_sequence
    WHERE name = 'provider_effect_uncertainties_observations'
);
UPDATE sqlite_sequence
SET seq = max(seq, coalesce((
    SELECT seq FROM sqlite_sequence WHERE name = 'provider_effect_uncertainties'
), 0))
WHERE name = 'provider_effect_uncertainties_observations';
DROP TABLE provider_effect_uncertainties;
ALTER TABLE provider_effect_uncertainties_observations
RENAME TO provider_effect_uncertainties;
CREATE INDEX provider_effect_uncertainties_key_seq
    ON provider_effect_uncertainties(effect_key, seq);
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
