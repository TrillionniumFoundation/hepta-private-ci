-- Durable Matrix egress truth. The existing outbox remains the queue/lease
-- owner; this ledger owns dispatch identity, boundary uncertainty and observed
-- terminality. A transport response is evidence, never terminal success.
CREATE TABLE matrix_dispatch_ledger (
    stable_txn_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id) BETWEEN 1 AND 255),
    homeserver_id TEXT,
    room_id TEXT NOT NULL,
    device_id TEXT,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    authority_epoch INTEGER CHECK (authority_epoch > 0),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    grant_payload_sha256 TEXT CHECK (
        grant_payload_sha256 IS NULL OR (
            length(grant_payload_sha256) = 64
            AND grant_payload_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    deadline_ms INTEGER CHECK (deadline_ms IS NULL OR deadline_ms > 0),
    state TEXT NOT NULL CHECK (
        state IN (
            'prepared', 'dispatched', 'retry_scheduled', 'accepted',
            'indeterminate', 'succeeded', 'failed', 'redacted',
            'legacy_unverified'
        )
    ),
    last_attempt INTEGER NOT NULL CHECK (last_attempt >= 0),
    accepted_event_id TEXT,
    terminal_event_id TEXT,
    send_observation_sha256 TEXT CHECK (
        send_observation_sha256 IS NULL OR (
            length(send_observation_sha256) = 64
            AND send_observation_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    redaction_observation_sha256 TEXT CHECK (
        redaction_observation_sha256 IS NULL OR (
            length(redaction_observation_sha256) = 64
            AND redaction_observation_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= prepared_at_ms),
    terminal_at_ms INTEGER CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= prepared_at_ms),
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NOT NULL)
        OR (state NOT IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NULL)
    ),
    CHECK (
        (state IN ('succeeded', 'redacted') AND terminal_event_id IS NOT NULL)
        OR (state NOT IN ('succeeded', 'redacted') OR terminal_event_id IS NOT NULL)
    ),
    CHECK (
        state != 'redacted' OR redaction_observation_sha256 IS NOT NULL
    )
) STRICT;

CREATE INDEX matrix_dispatch_ledger_by_state
ON matrix_dispatch_ledger(state, updated_at_ms, stable_txn_id);

CREATE INDEX matrix_dispatch_ledger_by_accepted_event
ON matrix_dispatch_ledger(accepted_event_id)
WHERE accepted_event_id IS NOT NULL;

CREATE INDEX matrix_dispatch_ledger_by_terminal_event
ON matrix_dispatch_ledger(terminal_event_id)
WHERE terminal_event_id IS NOT NULL;

CREATE TABLE matrix_dispatch_observations (
    observation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'transport_accepted', 'transport_retryable', 'transport_rejected',
            'homeserver_event', 'redaction', 'manual_terminal'
        )
    ),
    evidence_sha256 TEXT NOT NULL CHECK (
        length(evidence_sha256) = 64 AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    server_event_id TEXT,
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id)
        ON DELETE RESTRICT
) STRICT;

CREATE UNIQUE INDEX matrix_dispatch_observations_identity
ON matrix_dispatch_observations(
    stable_txn_id,
    observation_kind,
    evidence_sha256,
    COALESCE(server_event_id, '')
);

CREATE INDEX matrix_dispatch_observations_by_txn
ON matrix_dispatch_observations(stable_txn_id, observation_seq);

CREATE TRIGGER matrix_dispatch_ledger_no_delete
BEFORE DELETE ON matrix_dispatch_ledger BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch ledger is durable');
END;

CREATE TRIGGER matrix_dispatch_observations_no_update
BEFORE UPDATE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation is immutable');
END;

CREATE TRIGGER matrix_dispatch_observations_no_delete
BEFORE DELETE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation is immutable');
END;

-- Existing transport-era "sent" rows did not have an independent homeserver
-- observation. Preserve them without inventing terminal evidence. A later sync
-- observation can upgrade legacy_unverified to succeeded.
INSERT INTO matrix_dispatch_ledger (
    stable_txn_id, operation_id, homeserver_id, room_id, device_id,
    binding_revision, session_generation, authority_epoch,
    payload_sha256, grant_payload_sha256, deadline_ms, state, last_attempt,
    accepted_event_id, terminal_event_id, send_observation_sha256,
    redaction_observation_sha256, prepared_at_ms, updated_at_ms, terminal_at_ms
)
SELECT
    stable_txn_id,
    'matrix-send:' || stable_txn_id,
    NULL,
    room_id,
    NULL,
    binding_revision,
    generation,
    NULL,
    payload_sha256,
    NULL,
    NULL,
    CASE state
        WHEN 'pending' THEN 'prepared'
        WHEN 'in_flight' THEN 'indeterminate'
        WHEN 'retry_scheduled' THEN 'retry_scheduled'
        WHEN 'sent' THEN 'legacy_unverified'
        WHEN 'permanent_failure' THEN 'failed'
    END,
    attempts,
    CASE WHEN state = 'sent' THEN sent_event_id ELSE NULL END,
    NULL,
    NULL,
    NULL,
    created_at_ms,
    updated_at_ms,
    CASE WHEN state = 'permanent_failure' THEN updated_at_ms ELSE NULL END
FROM outbox_messages;
