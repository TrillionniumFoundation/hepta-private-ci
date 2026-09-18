-- AuthBus policy/quota/reservation owner state. All counters are fixed-width
-- big-endian u64 blobs; mutation is performed under BEGIN IMMEDIATE.
CREATE TABLE authbus_policy_heads (
    policy_id TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    policy_digest BLOB NOT NULL CHECK(length(policy_digest) = 32),
    revoked INTEGER NOT NULL CHECK(revoked IN (0,1)),
    updated_at_ms INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE authbus_policy_rules (
    policy_id TEXT NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    allow INTEGER NOT NULL CHECK(allow IN (0,1)),
    PRIMARY KEY(policy_id, revision, principal_id, action_id, scope_digest)
) WITHOUT ROWID;

CREATE TABLE authbus_quota_registry (
    quota_key TEXT PRIMARY KEY NOT NULL,
    revision BLOB NOT NULL CHECK(length(revision) = 8),
    endowment BLOB NOT NULL CHECK(length(endowment) = 8),
    reserved BLOB NOT NULL CHECK(length(reserved) = 8),
    consumed BLOB NOT NULL CHECK(length(consumed) = 8),
    updated_at_ms INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE authbus_quota_reservations (
    reservation_id TEXT PRIMARY KEY NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    quota_key TEXT NOT NULL,
    amount BLOB NOT NULL CHECK(length(amount) = 8),
    expires_at_ms BLOB NOT NULL CHECK(length(expires_at_ms) = 8),
    policy_id TEXT NOT NULL,
    policy_revision BLOB NOT NULL CHECK(length(policy_revision) = 8),
    state TEXT NOT NULL CHECK(state IN ('active','settled','cancelled','expired','quarantined')),
    observed_cost BLOB CHECK(observed_cost IS NULL OR length(observed_cost) = 8),
    terminal_evidence BLOB CHECK(terminal_evidence IS NULL OR length(terminal_evidence) = 32),
    settlement_digest BLOB CHECK(settlement_digest IS NULL OR length(settlement_digest) = 32),
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(quota_key) REFERENCES authbus_quota_registry(quota_key) ON UPDATE RESTRICT ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX authbus_quota_reservations_state
ON authbus_quota_reservations(quota_key, state, updated_at_ms, reservation_id);
