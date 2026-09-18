-- Durable metadata owner for secrets.heptabao dynamic leases.
--
-- Raw secret values are deliberately absent. The provider lease id is stored
-- because it is required for renew/revoke/reconciliation, but remains
-- privileged metadata and must not be emitted into general receipts/logs.

CREATE TABLE secret_lease_records (
    lease_key TEXT PRIMARY KEY NOT NULL
        CHECK (length(lease_key) BETWEEN 1 AND 256),
    provider_id TEXT NOT NULL
        CHECK (length(provider_id) BETWEEN 1 AND 256),
    provider_path TEXT NOT NULL
        CHECK (length(provider_path) BETWEEN 1 AND 2048),
    request_sha256 TEXT NOT NULL
        CHECK (length(request_sha256) = 64
               AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    provider_lease_id TEXT
        CHECK (provider_lease_id IS NULL
               OR length(provider_lease_id) BETWEEN 1 AND 2048),
    state TEXT NOT NULL
        CHECK (state IN (
            'requesting', 'active', 'renewing', 'revoke_pending',
            'revoked', 'expired', 'unknown', 'rejected'
        )),
    revision INTEGER NOT NULL CHECK (revision > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    record_sha256 TEXT NOT NULL
        CHECK (length(record_sha256) = 64
               AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) WITHOUT ROWID;

CREATE INDEX secret_lease_records_state
    ON secret_lease_records(state, updated_at_ms, lease_key);

CREATE UNIQUE INDEX secret_lease_records_provider_lease_id
    ON secret_lease_records(provider_lease_id)
    WHERE provider_lease_id IS NOT NULL;

CREATE TRIGGER secret_lease_records_transition
BEFORE UPDATE ON secret_lease_records
WHEN
    NEW.lease_key != OLD.lease_key
    OR NEW.provider_id != OLD.provider_id
    OR NEW.provider_path != OLD.provider_path
    OR NEW.request_sha256 != OLD.request_sha256
    OR NEW.revision != OLD.revision + 1
    OR (
        OLD.provider_lease_id IS NOT NULL
        AND NEW.provider_lease_id IS NOT OLD.provider_lease_id
    )
    OR NOT (
        (OLD.state = 'requesting'
            AND NEW.state IN ('active', 'unknown', 'rejected'))
        OR (OLD.state = 'active'
            AND NEW.state IN ('renewing', 'revoke_pending', 'expired'))
        OR (OLD.state = 'renewing'
            AND NEW.state IN ('active', 'unknown', 'expired'))
        OR (OLD.state = 'revoke_pending'
            AND NEW.state IN ('active', 'revoked', 'unknown'))
        OR (OLD.state = 'unknown'
            AND NEW.state IN ('active', 'revoked', 'expired', 'rejected'))
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid secret lease transition');
END;

CREATE TRIGGER secret_lease_records_no_delete
BEFORE DELETE ON secret_lease_records
BEGIN
    SELECT RAISE(ABORT, 'secret lease records preserve lifecycle lineage');
END;
