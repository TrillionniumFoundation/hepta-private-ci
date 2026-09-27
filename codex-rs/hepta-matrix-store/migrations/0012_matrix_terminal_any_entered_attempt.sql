-- A trusted homeserver echo is terminal evidence for the stable Matrix
-- transaction. A later retry claim must not hide an earlier attempt that
-- already crossed the final-use boundary under the same immutable content and
-- transaction identity.

DROP TRIGGER matrix_dispatch_succeeded_requires_authority_claim;
DROP TRIGGER matrix_dispatch_redacted_requires_authority_claim;
DROP TRIGGER matrix_dispatch_attempt_confirmed;
DROP TRIGGER matrix_dispatch_attempt_redacted;

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
           AND entry.attempt <= NEW.attempts
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
           AND entry.attempt <= NEW.attempts
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

-- Terminality belongs to the stable transaction. Attribute the append-only
-- terminal attempt event to the newest attempt that actually crossed the
-- entered-use boundary, never to a later claim that merely became current.
CREATE TRIGGER matrix_dispatch_attempt_confirmed
AFTER UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'succeeded' AND OLD.state != 'succeeded'
BEGIN
    INSERT INTO matrix_dispatch_attempt_events (
        stable_txn_id, attempt, lease_epoch, claim_token_sha256,
        event_kind, failure_class, retry_after_ms, event_id,
        detail_sha256, recorded_at_ms
    )
    SELECT NEW.stable_txn_id, entry.attempt, claim.lease_epoch,
           claim.claim_token_sha256, 'confirmed', NULL, NULL,
           NEW.terminal_event_id, NEW.send_observation_sha256,
           NEW.terminal_observed_at_ms
    FROM matrix_dispatch_use_entries AS entry
    JOIN matrix_dispatch_attempt_claims AS claim
      ON claim.stable_txn_id = entry.stable_txn_id
     AND claim.attempt = entry.attempt
    JOIN matrix_dispatch_authority_claims AS authority_claim
      ON authority_claim.stable_txn_id = entry.stable_txn_id
     AND authority_claim.attempt = entry.attempt
    JOIN matrix_dispatch_authority_witnesses AS authority_witness
      ON authority_witness.stable_txn_id = entry.stable_txn_id
     AND authority_witness.attempt = entry.attempt
    JOIN matrix_dispatch_content_bindings AS content
      ON content.stable_txn_id = entry.stable_txn_id
    WHERE entry.stable_txn_id = NEW.stable_txn_id
      AND entry.attempt <= NEW.attempts
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
    ORDER BY entry.attempt DESC
    LIMIT 1;
    DELETE FROM matrix_dispatch_active_claims
    WHERE stable_txn_id = NEW.stable_txn_id;
END;

CREATE TRIGGER matrix_dispatch_attempt_redacted
AFTER UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'redacted' AND OLD.state != 'redacted'
BEGIN
    INSERT INTO matrix_dispatch_attempt_events (
        stable_txn_id, attempt, lease_epoch, claim_token_sha256,
        event_kind, failure_class, retry_after_ms, event_id,
        detail_sha256, recorded_at_ms
    )
    SELECT NEW.stable_txn_id, entry.attempt, claim.lease_epoch,
           claim.claim_token_sha256, 'redacted', NULL, NULL,
           NEW.terminal_event_id, NEW.redaction_observation_sha256,
           NEW.terminal_observed_at_ms
    FROM matrix_dispatch_use_entries AS entry
    JOIN matrix_dispatch_attempt_claims AS claim
      ON claim.stable_txn_id = entry.stable_txn_id
     AND claim.attempt = entry.attempt
    JOIN matrix_dispatch_authority_claims AS authority_claim
      ON authority_claim.stable_txn_id = entry.stable_txn_id
     AND authority_claim.attempt = entry.attempt
    JOIN matrix_dispatch_authority_witnesses AS authority_witness
      ON authority_witness.stable_txn_id = entry.stable_txn_id
     AND authority_witness.attempt = entry.attempt
    JOIN matrix_dispatch_content_bindings AS content
      ON content.stable_txn_id = entry.stable_txn_id
    WHERE entry.stable_txn_id = NEW.stable_txn_id
      AND entry.attempt <= NEW.attempts
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
    ORDER BY entry.attempt DESC
    LIMIT 1;
    DELETE FROM matrix_dispatch_active_claims
    WHERE stable_txn_id = NEW.stable_txn_id;
END;
