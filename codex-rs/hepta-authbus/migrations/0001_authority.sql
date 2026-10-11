-- auth.authbus owns trusted-time and authorization-policy state.
-- Fixed-width big-endian integers preserve the full u64 range.
CREATE TABLE authbus_trusted_time (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    wall_time_ms BLOB NOT NULL CHECK (length(wall_time_ms) = 8),
    source_revision BLOB NOT NULL CHECK (length(source_revision) = 8),
    source_digest BLOB NOT NULL CHECK (length(source_digest) = 32)
) WITHOUT ROWID;

CREATE TABLE authbus_policy (
    policy_id TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    action TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    not_before_ms BLOB NOT NULL CHECK (length(not_before_ms) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)),
    UNIQUE (principal, action, scope_digest)
) WITHOUT ROWID;
