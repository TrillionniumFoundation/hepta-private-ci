-- Canonical qualification evidence and independently authenticated decision records.
-- Authentication/replay admission and the evidence append share one BEGIN IMMEDIATE
-- transaction in qualification.rs. Rows are immutable; corrections and revocations
-- append lineage instead of rewriting prior evidence.
CREATE TABLE qualification_evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL UNIQUE CHECK (
        length(evidence_id) BETWEEN 1 AND 128
        AND evidence_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    candidate_id TEXT NOT NULL CHECK (
        length(candidate_id) BETWEEN 1 AND 128
        AND candidate_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    source_commit TEXT NOT NULL CHECK (
        length(source_commit) IN (40, 64)
        AND source_commit NOT GLOB '*[^0-9a-f]*'
    ),
    source_tree TEXT NOT NULL CHECK (
        length(source_tree) IN (40, 64)
        AND source_tree NOT GLOB '*[^0-9a-f]*'
    ),
    claim_class TEXT NOT NULL CHECK (claim_class IN (
        'exact_source',
        'synthetic_merge',
        'mandatory_tests',
        'fixture',
        'hardware',
        'causal',
        'longitudinal',
        'security_resource',
        'provider_effect',
        'independent_decision',
        'conformance',
        'algorithm_fault',
        'runtime',
        'outbox',
        'reconciliation',
        'unlearning',
        'operator_acceptance',
        'registry_snapshot'
    )),
    receipt_kind TEXT NOT NULL CHECK (receipt_kind IN (
        'evidence', 'correction', 'revocation'
    )),
    issuer_role TEXT NOT NULL CHECK (issuer_role IN (
        'generator',
        'evaluator',
        'reviewer',
        'architecture',
        'durability',
        'learning',
        'security',
        'operator',
        'documentation',
        'terminal_observer',
        'product_writer',
        'selector',
        'loader'
    )),
    issuer_principal_id TEXT NOT NULL CHECK (
        length(issuer_principal_id) BETWEEN 1 AND 128
        AND issuer_principal_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    issuer_key_epoch BLOB NOT NULL CHECK (length(issuer_key_epoch) = 8),
    issuer_signing_identity_sha256 TEXT NOT NULL CHECK (
        length(issuer_signing_identity_sha256) = 64
        AND issuer_signing_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    auth_message_id TEXT NOT NULL CHECK (
        length(auth_message_id) BETWEEN 1 AND 128
        AND auth_message_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    auth_sequence BLOB NOT NULL CHECK (length(auth_sequence) = 8),
    auth_expires_at_ms BLOB NOT NULL CHECK (length(auth_expires_at_ms) = 8),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    envelope_sha256 TEXT NOT NULL CHECK (
        length(envelope_sha256) = 64
        AND envelope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_evidence_id TEXT,
    target_evidence_id TEXT,
    observed_at_ms BLOB NOT NULL CHECK (length(observed_at_ms) = 8),
    expires_at_ms BLOB CHECK (expires_at_ms IS NULL OR length(expires_at_ms) = 8),
    asset_count INTEGER NOT NULL CHECK (asset_count BETWEEN 0 AND 64),
    envelope_json TEXT NOT NULL CHECK (json_valid(envelope_json)),
    recorded_at_ms INTEGER NOT NULL,
    CHECK (
        (receipt_kind = 'evidence'
            AND predecessor_evidence_id IS NULL
            AND target_evidence_id IS NULL)
        OR
        (receipt_kind IN ('correction', 'revocation')
            AND predecessor_evidence_id IS NOT NULL
            AND target_evidence_id IS NOT NULL)
    ),
    FOREIGN KEY(predecessor_evidence_id)
        REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(target_evidence_id)
        REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX qualification_evidence_candidate_claim_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, claim_class, seq);

CREATE INDEX qualification_evidence_issuer_seq
    ON qualification_evidence(issuer_principal_id, issuer_role, seq);

CREATE INDEX qualification_evidence_target_seq
    ON qualification_evidence(target_evidence_id, seq);

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
