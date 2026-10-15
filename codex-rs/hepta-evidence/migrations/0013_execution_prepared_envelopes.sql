-- P2b: immutable, complete, recoverable execution control-envelope bytes.
--
-- This extends the ORIGINAL Evidence database/owner. It cannot authorize a
-- Final-use, physical Codex request, tool effect, or a retry after a lost ACK.
-- The matching ProviderEffectIntent and this row MUST be committed in a single
-- BEGIN IMMEDIATE transaction. Digest-only orphan records fail closed.
CREATE TABLE execution_prepared_envelopes (
    effect_key TEXT PRIMARY KEY NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    intent_json TEXT NOT NULL CHECK (
        length(CAST(intent_json AS BLOB)) BETWEEN 1 AND 4096
        AND json_valid(intent_json)
    ),
    intent_sha256 TEXT NOT NULL CHECK (
        length(intent_sha256) = 64
        AND intent_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    request_sha256 BLOB NOT NULL CHECK (length(request_sha256) = 32),
    recorded_at_ms INTEGER NOT NULL,
    FOREIGN KEY(effect_key)
        REFERENCES provider_effect_intents(effect_key)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TRIGGER execution_prepared_envelopes_no_update
BEFORE UPDATE ON execution_prepared_envelopes
BEGIN
    SELECT RAISE(ABORT, 'execution prepared envelopes are immutable');
END;

CREATE TRIGGER execution_prepared_envelopes_no_delete
BEFORE DELETE ON execution_prepared_envelopes
BEGIN
    SELECT RAISE(ABORT, 'execution prepared envelopes are immutable');
END;
