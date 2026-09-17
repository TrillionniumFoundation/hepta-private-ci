-- Canonical compact.engine checkpoint publication owned by the Agent-local
-- cognitive SQLite store. Generations are immutable; only the current head may
-- advance. A head is foreign-key bound to the exact generation+digest row.

CREATE TABLE canonical_compact_checkpoint_generations (
    scope_id TEXT NOT NULL CHECK (length(scope_id) BETWEEN 1 AND 128),
    generation INTEGER NOT NULL CHECK (generation > 0),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    predecessor_digest TEXT CHECK (predecessor_digest IS NULL OR length(predecessor_digest) = 64),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    proof_digest TEXT NOT NULL CHECK (length(proof_digest) = 64),
    semantic_artifact_digest TEXT NOT NULL CHECK (length(semantic_artifact_digest) = 64),
    bundle_json TEXT NOT NULL CHECK (length(bundle_json) > 0),
    payload BLOB NOT NULL CHECK (length(payload) > 0),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) > 0),
    grant_digest TEXT NOT NULL CHECK (length(grant_digest) = 64),
    authority_fence_digest TEXT NOT NULL CHECK (length(authority_fence_digest) = 64),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
    created_at_unix_seconds INTEGER NOT NULL CHECK (created_at_unix_seconds > 0),
    PRIMARY KEY (scope_id, generation),
    UNIQUE (scope_id, generation, checkpoint_digest),
    UNIQUE (scope_id, checkpoint_digest)
);

CREATE TRIGGER canonical_compact_checkpoint_generations_no_update
BEFORE UPDATE ON canonical_compact_checkpoint_generations
BEGIN
    SELECT RAISE(ABORT, 'canonical compact checkpoint generations are immutable');
END;

CREATE TRIGGER canonical_compact_checkpoint_generations_no_delete
BEFORE DELETE ON canonical_compact_checkpoint_generations
BEGIN
    SELECT RAISE(ABORT, 'canonical compact checkpoint generations are append-only');
END;

CREATE TABLE canonical_compact_checkpoint_heads (
    scope_id TEXT PRIMARY KEY CHECK (length(scope_id) BETWEEN 1 AND 128),
    generation INTEGER NOT NULL CHECK (generation > 0),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    updated_at_unix_seconds INTEGER NOT NULL CHECK (updated_at_unix_seconds > 0),
    FOREIGN KEY (scope_id, generation, checkpoint_digest)
        REFERENCES canonical_compact_checkpoint_generations(scope_id, generation, checkpoint_digest)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX canonical_compact_checkpoint_generations_checkpoint_lookup
    ON canonical_compact_checkpoint_generations(scope_id, checkpoint_digest);
