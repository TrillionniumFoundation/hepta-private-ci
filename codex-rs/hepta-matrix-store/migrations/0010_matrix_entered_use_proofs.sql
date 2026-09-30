-- Persist the exact non-constructible final-use proof after it crosses the
-- kernel-owned revocation/expiry check and before constructing the Matrix I/O
-- future. This is authorization-entry evidence, not remote-effect terminality.
-- Caller-filled authority metadata is not enough to qualify a remote effect.

CREATE TABLE matrix_dispatch_use_entries (
    stable_txn_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_token_sha256 TEXT NOT NULL CHECK (
        length(claim_token_sha256) = 64
        AND claim_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    operation_id TEXT NOT NULL CHECK (
        length(operation_id) BETWEEN 1 AND 512
        AND operation_id NOT GLOB '*[^ -~]*'
    ),
    subject_id TEXT NOT NULL CHECK (
        length(subject_id) BETWEEN 1 AND 128
        AND subject_id NOT GLOB '*[^A-Za-z0-9_.:/-]*'
    ),
    destination_id TEXT NOT NULL CHECK (
        length(destination_id) BETWEEN 1 AND 128
        AND destination_id NOT GLOB '*[^A-Za-z0-9_.:/-]*'
    ),
    request_sha256 TEXT NOT NULL CHECK (
        length(request_sha256) = 64
        AND request_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64
        AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_payload_sha256 TEXT NOT NULL CHECK (
        length(canonical_payload_sha256) = 64
        AND canonical_payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    entered_use_witness_sha256 TEXT NOT NULL CHECK (
        length(entered_use_witness_sha256) = 64
        AND entered_use_witness_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    entered_at_ms INTEGER NOT NULL CHECK (entered_at_ms >= 0),
    PRIMARY KEY (stable_txn_id, attempt),
    FOREIGN KEY (stable_txn_id, attempt, lease_epoch, claim_token_sha256)
        REFERENCES matrix_dispatch_attempt_claims(
            stable_txn_id, attempt, lease_epoch, claim_token_sha256
        ) ON DELETE RESTRICT,
    FOREIGN KEY (stable_txn_id, attempt)
        REFERENCES matrix_dispatch_authority_claims(stable_txn_id, attempt)
        ON DELETE RESTRICT,
    FOREIGN KEY (stable_txn_id, attempt)
        REFERENCES matrix_dispatch_authority_witnesses(stable_txn_id, attempt)
        ON DELETE RESTRICT,
    FOREIGN KEY (stable_txn_id)
        REFERENCES matrix_dispatch_content_bindings(stable_txn_id)
        ON DELETE RESTRICT,
    CHECK (lease_epoch = attempt)
) STRICT;

CREATE INDEX matrix_dispatch_use_entries_by_witness
ON matrix_dispatch_use_entries(entered_use_witness_sha256, stable_txn_id, attempt);

CREATE TRIGGER matrix_dispatch_use_entries_guard_insert
BEFORE INSERT ON matrix_dispatch_use_entries
WHEN NOT EXISTS (
    SELECT 1
    FROM matrix_dispatch_attempt_claims AS attempt_claim
    JOIN matrix_dispatch_active_claims AS active
      ON active.stable_txn_id = attempt_claim.stable_txn_id
     AND active.attempt = attempt_claim.attempt
     AND active.lease_epoch = attempt_claim.lease_epoch
     AND active.claim_token_sha256 = attempt_claim.claim_token_sha256
    JOIN matrix_dispatch_ledger AS dispatch
      ON dispatch.stable_txn_id = attempt_claim.stable_txn_id
     AND dispatch.attempts = attempt_claim.attempt
    JOIN matrix_dispatch_authority_claims AS authority_claim
      ON authority_claim.stable_txn_id = attempt_claim.stable_txn_id
     AND authority_claim.attempt = attempt_claim.attempt
    JOIN matrix_dispatch_authority_witnesses AS authority_witness
      ON authority_witness.stable_txn_id = attempt_claim.stable_txn_id
     AND authority_witness.attempt = attempt_claim.attempt
     AND authority_witness.lease_epoch = attempt_claim.lease_epoch
     AND authority_witness.claim_token_sha256 = attempt_claim.claim_token_sha256
    JOIN matrix_dispatch_content_bindings AS content
      ON content.stable_txn_id = attempt_claim.stable_txn_id
    WHERE attempt_claim.stable_txn_id = NEW.stable_txn_id
      AND attempt_claim.attempt = NEW.attempt
      AND attempt_claim.lease_epoch = NEW.lease_epoch
      AND attempt_claim.claim_token_sha256 = NEW.claim_token_sha256
      AND active.phase = 'dispatching'
      AND active.lease_until_ms > NEW.entered_at_ms
      AND dispatch.operation_id = NEW.operation_id
      AND authority_claim.operation_id = NEW.operation_id
      AND authority_claim.subject_id = NEW.subject_id
      AND authority_claim.destination_id = NEW.destination_id
      AND authority_claim.request_sha256 = NEW.request_sha256
      AND authority_claim.scope_sha256 = NEW.scope_sha256
      AND authority_claim.payload_sha256 = dispatch.payload_sha256
      AND authority_claim.expires_at_ms > NEW.entered_at_ms
      AND authority_witness.authority_epoch = authority_claim.authority_epoch
      AND authority_witness.revocation_revision = authority_claim.revocation_revision
      AND authority_witness.grant_id = authority_claim.grant_id
      AND authority_witness.verified_use_witness_sha256 = NEW.entered_use_witness_sha256
      AND content.scope_sha256 = NEW.scope_sha256
      AND content.canonical_content_sha256 = NEW.canonical_payload_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'Matrix entered-use proof is not bound to the live claim and verified use');
END;

CREATE TRIGGER matrix_dispatch_use_entries_no_update
BEFORE UPDATE ON matrix_dispatch_use_entries BEGIN
    SELECT RAISE(ABORT, 'Matrix entered-use proof is immutable');
END;

CREATE TRIGGER matrix_dispatch_use_entries_no_delete
BEFORE DELETE ON matrix_dispatch_use_entries BEGIN
    SELECT RAISE(ABORT, 'Matrix entered-use proof is durable');
END;

-- Replace the migration-6 metadata-only guards. A qualified terminal fact now
-- requires the proof produced only by consuming a real kernel VerifiedUseToken
-- at the final adapter boundary.
DROP TRIGGER matrix_dispatch_succeeded_requires_authority_claim;
DROP TRIGGER matrix_dispatch_redacted_requires_authority_claim;

CREATE TRIGGER matrix_dispatch_succeeded_requires_authority_claim
BEFORE UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'succeeded'
     AND NOT EXISTS (
         SELECT 1
         FROM matrix_dispatch_use_entries AS entry
         JOIN matrix_dispatch_authority_claims AS authority_claim
           ON authority_claim.stable_txn_id = entry.stable_txn_id
          AND authority_claim.attempt = entry.attempt
         JOIN matrix_dispatch_authority_witnesses AS authority_witness
           ON authority_witness.stable_txn_id = entry.stable_txn_id
          AND authority_witness.attempt = entry.attempt
         JOIN matrix_dispatch_content_bindings AS content
           ON content.stable_txn_id = entry.stable_txn_id
         WHERE entry.stable_txn_id = NEW.stable_txn_id
           AND entry.attempt = NEW.attempts
           AND entry.operation_id = NEW.operation_id
           AND authority_claim.operation_id = NEW.operation_id
           AND authority_claim.subject_id = entry.subject_id
           AND authority_claim.destination_id = entry.destination_id
           AND authority_claim.request_sha256 = entry.request_sha256
           AND authority_claim.scope_sha256 = entry.scope_sha256
           AND authority_claim.payload_sha256 = NEW.payload_sha256
           AND authority_witness.authority_epoch = authority_claim.authority_epoch
           AND authority_witness.revocation_revision = authority_claim.revocation_revision
           AND authority_witness.grant_id = authority_claim.grant_id
           AND authority_witness.verified_use_witness_sha256 = entry.entered_use_witness_sha256
           AND content.scope_sha256 = entry.scope_sha256
           AND content.canonical_content_sha256 = entry.canonical_payload_sha256
     )
BEGIN
    SELECT RAISE(ABORT, 'qualified Matrix success requires a durable entered-use proof');
END;

CREATE TRIGGER matrix_dispatch_redacted_requires_authority_claim
BEFORE UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'redacted'
     AND NOT EXISTS (
         SELECT 1
         FROM matrix_dispatch_use_entries AS entry
         JOIN matrix_dispatch_authority_claims AS authority_claim
           ON authority_claim.stable_txn_id = entry.stable_txn_id
          AND authority_claim.attempt = entry.attempt
         JOIN matrix_dispatch_authority_witnesses AS authority_witness
           ON authority_witness.stable_txn_id = entry.stable_txn_id
          AND authority_witness.attempt = entry.attempt
         JOIN matrix_dispatch_content_bindings AS content
           ON content.stable_txn_id = entry.stable_txn_id
         WHERE entry.stable_txn_id = NEW.stable_txn_id
           AND entry.attempt = NEW.attempts
           AND entry.operation_id = NEW.operation_id
           AND authority_claim.operation_id = NEW.operation_id
           AND authority_claim.subject_id = entry.subject_id
           AND authority_claim.destination_id = entry.destination_id
           AND authority_claim.request_sha256 = entry.request_sha256
           AND authority_claim.scope_sha256 = entry.scope_sha256
           AND authority_claim.payload_sha256 = NEW.payload_sha256
           AND authority_witness.authority_epoch = authority_claim.authority_epoch
           AND authority_witness.revocation_revision = authority_claim.revocation_revision
           AND authority_witness.grant_id = authority_claim.grant_id
           AND authority_witness.verified_use_witness_sha256 = entry.entered_use_witness_sha256
           AND content.scope_sha256 = entry.scope_sha256
           AND content.canonical_content_sha256 = entry.canonical_payload_sha256
     )
BEGIN
    SELECT RAISE(ABORT, 'qualified Matrix redaction requires a durable entered-use proof');
END;
