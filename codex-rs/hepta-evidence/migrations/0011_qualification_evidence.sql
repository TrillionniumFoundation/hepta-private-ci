CREATE TABLE qualification_evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    source_commit TEXT NOT NULL CHECK (
        length(source_commit) IN (40, 64)
        AND source_commit NOT GLOB '*[^0-9a-f]*'
    ),
    source_tree TEXT NOT NULL CHECK (
        length(source_tree) IN (40, 64)
        AND source_tree NOT GLOB '*[^0-9a-f]*'
    ),
    claim_class TEXT NOT NULL CHECK (
        claim_class IN (
            'source_execution',
            'merge_execution',
            'fixture',
            'hardware',
            'provider_effect',
            'longitudinal',
            'independent_review',
            'operator_acceptance',
            'trust_root',
            'promotion',
            'release'
        )
    ),
    issuer_role TEXT NOT NULL CHECK (
        issuer_role IN (
            'generator',
            'ci_executor',
            'independent_evaluator',
            'architecture_reviewer',
            'security_reviewer',
            'operator',
            'provider',
            'terminal_observer',
            'release_authority'
        )
    ),
    issuer_principal TEXT NOT NULL,
    issuer_key_id TEXT NOT NULL,
    issuer_root_id TEXT NOT NULL,
    issuer_verifying_key BLOB NOT NULL CHECK (length(issuer_verifying_key) = 32),
    issuer_certificate_json TEXT NOT NULL CHECK (json_valid(issuer_certificate_json)),
    issuer_certificate_sha256 TEXT NOT NULL CHECK (
        length(issuer_certificate_sha256) = 64
        AND issuer_certificate_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    issuer_certificate_signature BLOB NOT NULL CHECK (length(issuer_certificate_signature) = 64),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_receipt_id TEXT,
    observed_unix_ms INTEGER NOT NULL CHECK (observed_unix_ms > 0),
    expires_unix_ms INTEGER NOT NULL CHECK (expires_unix_ms > observed_unix_ms),
    revokes_receipt_id TEXT,
    envelope_json TEXT NOT NULL CHECK (json_valid(envelope_json)),
    envelope_sha256 TEXT NOT NULL CHECK (
        length(envelope_sha256) = 64
        AND envelope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    signature BLOB NOT NULL CHECK (length(signature) = 64),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms > 0),
    FOREIGN KEY(predecessor_receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(revokes_receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX qualification_evidence_candidate_claim_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, claim_class, seq);

CREATE INDEX qualification_evidence_candidate_role_seq
    ON qualification_evidence(candidate_id, source_commit, source_tree, issuer_role, seq);

CREATE INDEX qualification_evidence_revocation_target
    ON qualification_evidence(revokes_receipt_id)
    WHERE revokes_receipt_id IS NOT NULL;

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

CREATE TABLE independent_decision_receipts (
    decision_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (
        role IN (
            'independent_evaluator',
            'architecture_reviewer',
            'security_reviewer'
        )
    ),
    principal_id TEXT NOT NULL,
    signing_identity_digest TEXT NOT NULL CHECK (
        length(signing_identity_digest) = 64
        AND signing_identity_digest NOT GLOB '*[^0-9a-f]*'
    ),
    evidence_set_digest TEXT NOT NULL CHECK (
        length(evidence_set_digest) = 64
        AND evidence_set_digest NOT GLOB '*[^0-9a-f]*'
    ),
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'conditional')),
    conditions_json TEXT NOT NULL CHECK (json_valid(conditions_json)),
    expires_unix_ms INTEGER NOT NULL CHECK (expires_unix_ms > 0),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    FOREIGN KEY(receipt_id)
        REFERENCES qualification_evidence(receipt_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX independent_decision_receipts_candidate_role
    ON independent_decision_receipts(candidate_id, role, decision_id);

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

CREATE TABLE qualification_issuer_key_revocations (
    revocation_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    key_id TEXT NOT NULL,
    observed_unix_ms INTEGER NOT NULL CHECK (observed_unix_ms > 0),
    reason_code TEXT NOT NULL,
    authority_principal TEXT NOT NULL,
    authority_key_id TEXT NOT NULL,
    authority_role TEXT NOT NULL CHECK (authority_role = 'security_reviewer'),
    authority_verifying_key BLOB NOT NULL CHECK (length(authority_verifying_key) = 32),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    signature BLOB NOT NULL CHECK (length(signature) = 64),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms > 0)
);

CREATE INDEX qualification_issuer_key_revocations_key
    ON qualification_issuer_key_revocations(root_id, key_id, observed_unix_ms);

CREATE TRIGGER qualification_issuer_key_revocations_no_update
BEFORE UPDATE ON qualification_issuer_key_revocations
BEGIN
    SELECT RAISE(ABORT, 'qualification issuer key revocations are immutable');
END;

CREATE TRIGGER qualification_issuer_key_revocations_no_delete
BEFORE DELETE ON qualification_issuer_key_revocations
BEGIN
    SELECT RAISE(ABORT, 'qualification issuer key revocations are immutable');
END;
