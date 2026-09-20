CREATE TABLE memory_mutation_shadow_observations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    dry_run_id TEXT NOT NULL UNIQUE,
    proposal_id TEXT NOT NULL,
    turn_sha256 TEXT NOT NULL CHECK (
        length(turn_sha256) = 64
        AND turn_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64
        AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    snapshot_sha256 TEXT NOT NULL CHECK (
        length(snapshot_sha256) = 64
        AND snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    disposition TEXT NOT NULL CHECK (
        disposition IN (
            'would_create',
            'would_supersede',
            'would_tombstone',
            'no_op',
            'blocked'
        )
    ),
    reason TEXT NOT NULL CHECK (
        reason IN (
            'ready',
            'exact_revision_already_present',
            'proposal_invalid',
            'unexpected_existing_revision',
            'expected_revision_missing',
            'scope_mismatch',
            'revision_mismatch',
            'current_revision_invalid',
            'current_revision_inactive',
            'source_binding_mismatch',
            'source_revision_not_newer'
        )
    ),
    projected_memory_writes INTEGER NOT NULL CHECK (
        projected_memory_writes BETWEEN 0 AND 2
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (
        length(evidence_sha256) = 64
        AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    UNIQUE(proposal_id, snapshot_sha256),
    CHECK (
        (disposition IN ('would_create', 'would_tombstone') AND projected_memory_writes = 1)
        OR (disposition = 'would_supersede' AND projected_memory_writes = 2)
        OR (disposition IN ('no_op', 'blocked') AND projected_memory_writes = 0)
    ),
    CHECK (
        (disposition IN ('would_create', 'would_supersede', 'would_tombstone') AND reason = 'ready')
        OR (disposition = 'no_op' AND reason = 'exact_revision_already_present')
        OR (
            disposition = 'blocked'
            AND reason NOT IN ('ready', 'exact_revision_already_present')
        )
    )
);

CREATE INDEX memory_mutation_shadow_proposal_seq
    ON memory_mutation_shadow_observations(proposal_id, seq);

CREATE INDEX memory_mutation_shadow_turn_seq
    ON memory_mutation_shadow_observations(turn_sha256, seq);

CREATE TRIGGER memory_mutation_shadow_no_update
BEFORE UPDATE ON memory_mutation_shadow_observations
BEGIN
    SELECT RAISE(ABORT, 'memory mutation shadow observations are immutable');
END;

CREATE TRIGGER memory_mutation_shadow_no_delete
BEFORE DELETE ON memory_mutation_shadow_observations
BEGIN
    SELECT RAISE(ABORT, 'memory mutation shadow observations are immutable');
END;
