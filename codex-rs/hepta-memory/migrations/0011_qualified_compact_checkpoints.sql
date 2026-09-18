-- Canonical Lane C compact checkpoint publication.
--
-- This is the durable physical owner for compact.engine checkpoint metadata.
-- Source facts remain in their existing ledgers. Rows are immutable and one
-- scope/purpose generation can be published only once.
CREATE TABLE cognitive_qualified_compact_checkpoints (
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    scope_id TEXT NOT NULL CHECK (
        length(trim(scope_id)) BETWEEN 1 AND 128 AND instr(scope_id, char(0)) = 0
    ),
    purpose_id TEXT NOT NULL CHECK (
        length(trim(purpose_id)) BETWEEN 1 AND 128 AND instr(purpose_id, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    checkpoint_digest TEXT NOT NULL CHECK (
        length(checkpoint_digest) = 64 AND checkpoint_digest NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_digest TEXT CHECK (
        predecessor_digest IS NULL OR
        (length(predecessor_digest) = 64 AND predecessor_digest NOT GLOB '*[^0-9a-f]*')
    ),
    candidate_digest TEXT NOT NULL CHECK (
        length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'
    ),
    proof_digest TEXT NOT NULL CHECK (
        length(proof_digest) = 64 AND proof_digest NOT GLOB '*[^0-9a-f]*'
    ),
    source_snapshot_digest TEXT NOT NULL CHECK (
        length(source_snapshot_digest) = 64 AND source_snapshot_digest NOT GLOB '*[^0-9a-f]*'
    ),
    tokenizer_digest TEXT NOT NULL CHECK (
        length(tokenizer_digest) = 64 AND tokenizer_digest NOT GLOB '*[^0-9a-f]*'
    ),
    publication_digest TEXT NOT NULL CHECK (
        length(publication_digest) = 64 AND publication_digest NOT GLOB '*[^0-9a-f]*'
    ),
    checkpoint_json TEXT NOT NULL CHECK (
        length(checkpoint_json) BETWEEN 1 AND 32768 AND instr(checkpoint_json, char(0)) = 0
    ),
    proof_json TEXT NOT NULL CHECK (
        length(proof_json) BETWEEN 1 AND 32768 AND instr(proof_json, char(0)) = 0
    ),
    published_at_unix_seconds INTEGER NOT NULL CHECK (published_at_unix_seconds > 0),
    PRIMARY KEY (owner_agent_id, scope_id, purpose_id, generation),
    UNIQUE (owner_agent_id, scope_id, purpose_id, checkpoint_digest)
) STRICT;

CREATE TRIGGER cognitive_qualified_compact_checkpoints_no_update
BEFORE UPDATE ON cognitive_qualified_compact_checkpoints BEGIN
    SELECT RAISE(ABORT, 'qualified compact checkpoints are immutable');
END;

CREATE TRIGGER cognitive_qualified_compact_checkpoints_no_delete
BEFORE DELETE ON cognitive_qualified_compact_checkpoints BEGIN
    SELECT RAISE(ABORT, 'qualified compact checkpoints are immutable');
END;

CREATE INDEX cognitive_qualified_compact_checkpoints_latest
ON cognitive_qualified_compact_checkpoints(
    owner_agent_id, scope_id, purpose_id, generation DESC
);
