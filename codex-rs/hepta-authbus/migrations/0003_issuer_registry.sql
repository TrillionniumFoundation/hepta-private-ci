-- Durable issuer lifecycle for signed AuthBus messages, settlement evidence and
-- trusted-time attestations. Revoked/retired epochs are retained permanently.
CREATE TABLE authbus_issuer_registry (
    issuer_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('message', 'settlement', 'trusted_time')),
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    public_key BLOB NOT NULL CHECK (length(public_key) = 32),
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked', 'retired')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    PRIMARY KEY (issuer_id, purpose, key_epoch)
) WITHOUT ROWID;

CREATE UNIQUE INDEX authbus_one_active_issuer_epoch
    ON authbus_issuer_registry(issuer_id, purpose) WHERE state = 'active';
