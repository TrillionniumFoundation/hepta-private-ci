-- Monotonic issuer-trust acceptance, authenticated by the same independently
-- signed external frontier that pins the registry digest.  Registry generation
-- rollback and predecessor substitution remain rejected across daemon restart.

CREATE TABLE evidence_trust_acceptance (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    agent_id TEXT NOT NULL CHECK (
        length(agent_id) BETWEEN 1 AND 128
        AND agent_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    registry_generation BLOB NOT NULL CHECK (length(registry_generation) = 8),
    registry_sha256 TEXT NOT NULL CHECK (
        length(registry_sha256) = 64
        AND registry_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_sha256 TEXT CHECK (
        predecessor_sha256 IS NULL OR (
            length(predecessor_sha256) = 64
            AND predecessor_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    accepted_frontier_generation BLOB NOT NULL CHECK (
        length(accepted_frontier_generation) = 8
    ),
    accepted_frontier_sha256 TEXT NOT NULL CHECK (
        length(accepted_frontier_sha256) = 64
        AND accepted_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    backend_identity_sha256 TEXT NOT NULL CHECK (
        length(backend_identity_sha256) = 64
        AND backend_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    accepted_at_ms BLOB NOT NULL CHECK (length(accepted_at_ms) = 8),
    UNIQUE(store_id, registry_generation),
    CHECK (
        (registry_generation = X'0000000000000001' AND predecessor_sha256 IS NULL)
        OR
        (registry_generation != X'0000000000000001' AND predecessor_sha256 IS NOT NULL)
    ),
    FOREIGN KEY(store_id) REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX evidence_trust_acceptance_store_seq
    ON evidence_trust_acceptance(store_id, seq);

CREATE TRIGGER evidence_trust_acceptance_no_update
BEFORE UPDATE ON evidence_trust_acceptance
BEGIN
    SELECT RAISE(ABORT, 'accepted evidence trust generations are immutable');
END;

CREATE TRIGGER evidence_trust_acceptance_no_delete
BEFORE DELETE ON evidence_trust_acceptance
BEGIN
    SELECT RAISE(ABORT, 'accepted evidence trust generations cannot be deleted');
END;
