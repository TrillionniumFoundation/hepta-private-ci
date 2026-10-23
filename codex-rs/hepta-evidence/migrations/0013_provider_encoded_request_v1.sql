CREATE TABLE provider_encoded_requests_v1 (
    attempt_id TEXT PRIMARY KEY REFERENCES provider_invocation_intents(attempt_id),
    body_sha256 TEXT NOT NULL CHECK (
        typeof(body_sha256) = 'text'
        AND length(body_sha256) = 64 AND body_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    byte_length INTEGER NOT NULL CHECK (typeof(byte_length) = 'integer' AND byte_length > 0)
) WITHOUT ROWID;
CREATE TRIGGER provider_encoded_requests_v1_no_update
BEFORE UPDATE ON provider_encoded_requests_v1 BEGIN
    SELECT RAISE(ABORT, 'encoded provider request is immutable');
END;
CREATE TRIGGER provider_encoded_requests_v1_no_delete
BEFORE DELETE ON provider_encoded_requests_v1 BEGIN
    SELECT RAISE(ABORT, 'encoded provider request is immutable');
END;
