CREATE TABLE secret_lease_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL
);

CREATE TRIGGER secret_lease_meta_no_update
BEFORE UPDATE ON secret_lease_meta
BEGIN
    SELECT RAISE(ABORT, 'secret lease metadata is immutable');
END;

CREATE TRIGGER secret_lease_meta_no_delete
BEFORE DELETE ON secret_lease_meta
BEGIN
    SELECT RAISE(ABORT, 'secret lease metadata is immutable');
END;

CREATE TABLE secret_leases (
    lease_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    provider_mount TEXT NOT NULL,
    namespace TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    scope_sha256 BLOB NOT NULL CHECK (length(scope_sha256) = 32),
    request_sha256 BLOB NOT NULL CHECK (length(request_sha256) = 32),
    fingerprint_key_id TEXT NOT NULL,
    secret_fingerprint BLOB NOT NULL CHECK (length(secret_fingerprint) = 32),
    renewable INTEGER NOT NULL CHECK (renewable IN (0, 1)),
    issued_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    rotation_generation INTEGER NOT NULL CHECK (rotation_generation > 0),
    state TEXT NOT NULL CHECK (
        state IN ('active', 'renew_indeterminate', 'revoke_indeterminate', 'revoked', 'expired')
    ),
    revision INTEGER NOT NULL CHECK (revision > 0),
    updated_at_ms INTEGER NOT NULL,
    CHECK (expires_at_ms > issued_at_ms)
);

CREATE INDEX secret_leases_state_expiry_idx
    ON secret_leases(state, expires_at_ms, lease_id);

CREATE TABLE secret_lease_operations (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('issue', 'renew', 'revoke')),
    lease_id TEXT,
    semantic_sha256 BLOB NOT NULL CHECK (length(semantic_sha256) = 32),
    state TEXT NOT NULL CHECK (
        state IN ('prepared', 'dispatching', 'applied', 'not_applied', 'indeterminate')
    ),
    observed_sha256 BLOB CHECK (observed_sha256 IS NULL OR length(observed_sha256) = 32),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX secret_lease_operations_recovery_idx
    ON secret_lease_operations(state, created_at_ms, operation_id);
