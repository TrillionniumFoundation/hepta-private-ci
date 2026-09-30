-- Remediate pre-canonicalization outbound attempts without replaying them.
-- Migration 9 sealed their identity as legacy holds. This migration gives each
-- hold a durable unresolved ledger row, closes any stale local claim, and parks
-- the queue row. Only authenticated /sync evidence may later settle it.
--
-- The maximum signed SQLite integer is used as a non-runnable schedule marker;
-- it is not a deadline or a claim that reconciliation completed.

INSERT INTO matrix_dispatch_ledger (
    stable_txn_id, operation_id, logical_outbox_id, room_id,
    binding_revision, generation, payload_sha256,
    authority_epoch, grant_id, grant_payload_sha256,
    state, accepted_event_id, terminal_event_id,
    transport_observation_sha256, send_observation_sha256,
    redaction_observation_sha256, attempts, prepared_at_ms,
    updated_at_ms, terminal_observed_at_ms
)
SELECT
    message.stable_txn_id,
    'matrix.send:' || message.stable_txn_id,
    message.logical_outbox_id,
    message.room_id,
    message.binding_revision,
    message.generation,
    message.payload_sha256,
    NULL,
    NULL,
    NULL,
    CASE
        WHEN message.state = 'sent' AND message.sent_event_id IS NOT NULL
            THEN 'accepted'
        ELSE 'indeterminate'
    END,
    CASE
        WHEN message.state = 'sent' AND message.sent_event_id IS NOT NULL
            THEN message.sent_event_id
        ELSE NULL
    END,
    NULL,
    NULL,
    NULL,
    NULL,
    message.attempts,
    message.created_at_ms,
    message.updated_at_ms,
    NULL
FROM matrix_dispatch_legacy_content_holds AS hold
JOIN outbox_messages AS message USING (stable_txn_id)
LEFT JOIN matrix_dispatch_ledger AS dispatch USING (stable_txn_id)
WHERE dispatch.stable_txn_id IS NULL;

-- An intermediate binary may already have created an unresolved or failed
-- ledger row before canonical pinning rejected the inherited item. Preserve
-- every observation row, but reopen the logical result as unresolved because
-- the sealed hold proves that an earlier attempt cannot be safely disproved.
UPDATE matrix_dispatch_ledger
SET
    state = CASE
        WHEN accepted_event_id IS NOT NULL
          OR (
            SELECT message.state = 'sent' AND message.sent_event_id IS NOT NULL
            FROM outbox_messages AS message
            WHERE message.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
          )
            THEN 'accepted'
        ELSE 'indeterminate'
    END,
    accepted_event_id = COALESCE(
        accepted_event_id,
        (
            SELECT CASE
                WHEN message.state = 'sent' AND message.sent_event_id IS NOT NULL
                    THEN message.sent_event_id
                ELSE NULL
            END
            FROM outbox_messages AS message
            WHERE message.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
        )
    ),
    terminal_event_id = NULL,
    attempts = (
        SELECT message.attempts
        FROM outbox_messages AS message
        WHERE message.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
    ),
    updated_at_ms = MAX(
        updated_at_ms,
        (
            SELECT message.updated_at_ms
            FROM outbox_messages AS message
            WHERE message.stable_txn_id = matrix_dispatch_ledger.stable_txn_id
        )
    ),
    terminal_observed_at_ms = NULL
WHERE stable_txn_id IN (
    SELECT hold.stable_txn_id
    FROM matrix_dispatch_legacy_content_holds AS hold
)
AND state IN ('dispatched', 'accepted', 'indeterminate', 'failed');

-- A stale claim from a pre-remediation process must not keep the startup
-- invariant tied to an in-flight queue row. Claimed-only work is known not to
-- have crossed the current final-use entry and expires. Any later phase is
-- conservatively recorded as indeterminate.
INSERT INTO matrix_dispatch_attempt_events (
    stable_txn_id, attempt, lease_epoch, claim_token_sha256,
    event_kind, failure_class, retry_after_ms, event_id,
    detail_sha256, recorded_at_ms
)
SELECT
    active.stable_txn_id,
    active.attempt,
    active.lease_epoch,
    active.claim_token_sha256,
    CASE WHEN active.phase = 'claimed' THEN 'expired' ELSE 'indeterminate' END,
    CASE WHEN active.phase = 'claimed' THEN NULL ELSE 'response_lost' END,
    NULL,
    NULL,
    NULL,
    MAX(
        CASE
            WHEN active.phase = 'claimed' THEN active.lease_until_ms
            ELSE message.updated_at_ms
        END,
        COALESCE(
            (
                SELECT MAX(event.recorded_at_ms)
                FROM matrix_dispatch_attempt_events AS event
                WHERE event.stable_txn_id = active.stable_txn_id
                  AND event.attempt = active.attempt
                  AND event.lease_epoch = active.lease_epoch
                  AND event.claim_token_sha256 = active.claim_token_sha256
            ),
            active.claimed_at_ms
        )
    )
FROM matrix_dispatch_active_claims AS active
JOIN matrix_dispatch_legacy_content_holds AS hold USING (stable_txn_id)
JOIN outbox_messages AS message USING (stable_txn_id)
WHERE NOT EXISTS (
    SELECT 1
    FROM matrix_dispatch_attempt_events AS event
    WHERE event.stable_txn_id = active.stable_txn_id
      AND event.attempt = active.attempt
      AND event.lease_epoch = active.lease_epoch
      AND event.claim_token_sha256 = active.claim_token_sha256
      AND event.event_kind = CASE
          WHEN active.phase = 'claimed' THEN 'expired'
          ELSE 'indeterminate'
      END
);

DELETE FROM matrix_dispatch_active_claims
WHERE stable_txn_id IN (
    SELECT stable_txn_id FROM matrix_dispatch_legacy_content_holds
);

UPDATE outbox_messages
SET
    state = 'retry_scheduled',
    next_attempt_at_ms = 9223372036854775807,
    lease_until_ms = NULL
WHERE stable_txn_id IN (
    SELECT stable_txn_id FROM matrix_dispatch_legacy_content_holds
)
AND state IN ('pending', 'in_flight', 'retry_scheduled');

CREATE TRIGGER matrix_dispatch_legacy_hold_no_reactivate
BEFORE UPDATE OF state, next_attempt_at_ms, lease_until_ms ON outbox_messages
WHEN EXISTS (
        SELECT 1 FROM matrix_dispatch_legacy_content_holds AS hold
        WHERE hold.stable_txn_id = NEW.stable_txn_id
     )
     AND NEW.state IN ('pending', 'in_flight', 'retry_scheduled')
     AND NOT (
        NEW.state = 'retry_scheduled'
        AND NEW.next_attempt_at_ms = 9223372036854775807
        AND NEW.lease_until_ms IS NULL
     )
BEGIN
    SELECT RAISE(ABORT, 'legacy Matrix send remains held for authenticated reconciliation');
END;
