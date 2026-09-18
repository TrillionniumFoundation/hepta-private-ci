CREATE TABLE qualification_evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    source_commit TEXT NOT NULL CHECK (
        length(source_commit) = 40
        AND source_commit NOT GLOB '*[^0-9a-f]*'
    ),
    source_tree TEXT NOT NULL CHECK (
        length(source_tree) = 40
        AND source_tree NOT GLOB '*[^0-9a-f]*'
    ),
    claim_class TEXT NOT NULL CHECK (
        claim_class IN (
            'algorithm_fault',
            'candidate_evaluation',
            'conformance',
            'evaluation',
            'independent_decision',
            'local_model_runtime',
            'longitudinal_evaluation',
            'unlearning_compliance'
        )
    ),
    protocol_id TEXT NOT NULL,
    issuer_principal_id TEXT NOT NULL,
    issuer_controller_id TEXT NOT NULL,
    issuer_role TEXT NOT NULL CHECK (
        issuer_role IN (
            'generator',
            'evaluator',
            'reviewer',
            'selector',
            'loader',
            'operator',
            'terminal_observer'
        )
    ),
    signing_identity_sha256 TEXT NOT NULL CHECK (
        length(signing_identity_sha256) = 64
        AND signing_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    credential_chain_sha256 TEXT NOT NULL CHECK (
        length(credential_chain_sha256) = 64
        AND credential_chain_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    evidence_set_sha256 TEXT NOT NULL CHECK (
        length(evidence_set_sha256) = 64
        AND evidence_set_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_evidence_id TEXT,
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms >= observed_at_ms),
    revokes_evidence_id TEXT,
    supersedes_evidence_id TEXT,
    payload_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64
        AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    FOREIGN KEY(predecessor_evidence_id)
        REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(revokes_evidence_id)
        REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_evidence_id)
        REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX qualification_evidence_candidate_claim_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, claim_class, seq);

CREATE INDEX qualification_evidence_candidate_role_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, issuer_role, seq);

CREATE TRIGGER qualification_evidence_no_update
BEFORE UPDATE ON qualification_evidence
BEGIN
    SELECT RAISE(ABORT, 'qualification evidence is immutable');
END;

CREATE TRIGGER qualification_evidence_no_delete
BEFORE DELETE ON qualification_evidence
BEGIN
    SELECT RAISE(ABORT, 'qualification evidence is immutable');
END;
