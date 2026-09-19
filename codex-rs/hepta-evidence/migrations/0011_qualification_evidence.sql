-- Qualification evidence is an append-only, exact-candidate evidence chain.
-- Every append is content-bound to an authenticated issuer witness and to the
-- previous global chain head. External checkpoints retain the store identity
-- and an observed chain frontier so rollback/replacement can fail closed.
CREATE TABLE qualification_evidence_meta (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    store_instance_id TEXT NOT NULL UNIQUE CHECK (
        length(store_instance_id) = 64
        AND store_instance_id NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
);

CREATE TABLE qualification_evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE CHECK (length(receipt_id) BETWEEN 1 AND 128),
    candidate_id TEXT NOT NULL CHECK (length(candidate_id) BETWEEN 1 AND 128),
    source_commit TEXT NOT NULL CHECK (length(source_commit) IN (40, 64)),
    source_tree TEXT NOT NULL CHECK (length(source_tree) IN (40, 64)),
    claim_class TEXT NOT NULL CHECK (length(claim_class) BETWEEN 1 AND 64),
    issuer_role TEXT NOT NULL CHECK (length(issuer_role) BETWEEN 1 AND 64),
    issuer_principal_id TEXT NOT NULL CHECK (length(issuer_principal_id) BETWEEN 1 AND 128),
    signing_identity_sha256 TEXT NOT NULL CHECK (
        length(signing_identity_sha256) = 64
        AND signing_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    trust_policy_sha256 TEXT NOT NULL CHECK (
        length(trust_policy_sha256) = 64
        AND trust_policy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_receipt_id TEXT,
    revokes_receipt_id TEXT,
    revokes_issuer_key_sha256 TEXT CHECK (
        revokes_issuer_key_sha256 IS NULL OR (
            length(revokes_issuer_key_sha256) = 64
            AND revokes_issuer_key_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    expires_at_ms INTEGER CHECK (expires_at_ms IS NULL OR expires_at_ms > observed_at_ms),
    envelope_json TEXT NOT NULL,
    issuer_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64
        AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_chain_sha256 TEXT NOT NULL CHECK (
        length(previous_chain_sha256) = 64
        AND previous_chain_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    chain_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(chain_sha256) = 64
        AND chain_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    FOREIGN KEY(predecessor_receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(revokes_receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE independent_decision_receipts (
    decision_id TEXT PRIMARY KEY CHECK (length(decision_id) BETWEEN 1 AND 128),
    evidence_receipt_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL CHECK (length(candidate_id) BETWEEN 1 AND 128),
    role TEXT NOT NULL CHECK (length(role) BETWEEN 1 AND 64),
    principal_id TEXT NOT NULL CHECK (length(principal_id) BETWEEN 1 AND 128),
    signing_identity_sha256 TEXT NOT NULL CHECK (
        length(signing_identity_sha256) = 64
        AND signing_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    evidence_set_sha256 TEXT NOT NULL CHECK (
        length(evidence_set_sha256) = 64
        AND evidence_set_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    decision TEXT NOT NULL CHECK (
        decision IN ('accept', 'reject', 'conditional', 'abstain')
    ),
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms >= 0),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    FOREIGN KEY(evidence_receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX qualification_evidence_candidate_claim_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, claim_class, seq);

CREATE INDEX qualification_evidence_candidate_role_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, issuer_role, seq);

CREATE INDEX qualification_evidence_revoked_key_seq
    ON qualification_evidence(revokes_issuer_key_sha256, seq)
    WHERE revokes_issuer_key_sha256 IS NOT NULL;

CREATE TRIGGER qualification_evidence_meta_no_update
BEFORE UPDATE ON qualification_evidence_meta
BEGIN
    SELECT RAISE(ABORT, 'qualification evidence store identity is immutable');
END;

CREATE TRIGGER qualification_evidence_meta_no_delete
BEFORE DELETE ON qualification_evidence_meta
BEGIN
    SELECT RAISE(ABORT, 'qualification evidence store identity is immutable');
END;

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

CREATE TRIGGER independent_decision_receipts_no_update
BEFORE UPDATE ON independent_decision_receipts
BEGIN
    SELECT RAISE(ABORT, 'independent decision receipts are immutable');
END;

CREATE TRIGGER independent_decision_receipts_no_delete
BEFORE DELETE ON independent_decision_receipts
BEGIN
    SELECT RAISE(ABORT, 'independent decision receipts are immutable');
END;
