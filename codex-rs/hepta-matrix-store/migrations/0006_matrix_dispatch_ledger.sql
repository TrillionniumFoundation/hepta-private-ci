CREATE TABLE matrix_dispatch_ledger (
    stable_txn_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    authority_identity TEXT NOT NULL,
    authority_epoch INTEGER CHECK (authority_epoch IS NULL OR authority_epoch > 0),
    grant_payload_digest TEXT CHECK (
        grant_payload_digest IS NULL OR (
            length(grant_payload_digest) = 64
            AND grant_payload_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    state TEXT NOT NULL CHECK (
        state IN (
            'dispatched',
            'accepted',
            'indeterminate',
            'observed_terminal',
            'terminal_failure',
            'redacted'
        )
    ),
    last_attempt INTEGER NOT NULL CHECK (last_attempt > 0),
    transport_event_id TEXT,
    terminal_event_id TEXT,
    send_observation_digest TEXT CHECK (
        send_observation_digest IS NULL OR (
            length(send_observation_digest) = 64
            AND send_observation_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    redaction_observation_digest TEXT CHECK (
        redaction_observation_digest IS NULL OR (
            length(redaction_observation_digest) = 64
            AND redaction_observation_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    redacted_at_ms INTEGER,
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'observed_terminal' AND terminal_event_id IS NOT NULL AND terminal_at_ms IS NOT NULL)
        OR (state = 'redacted' AND terminal_event_id IS NOT NULL
            AND terminal_at_ms IS NOT NULL AND redacted_at_ms IS NOT NULL
            AND redaction_observation_digest IS NOT NULL)
        OR (state NOT IN ('observed_terminal', 'redacted') AND redacted_at_ms IS NULL)
    )
) STRICT;

CREATE INDEX matrix_dispatch_unresolved
ON matrix_dispatch_ledger(state, updated_at_ms, stable_txn_id);

CREATE UNIQUE INDEX matrix_dispatch_terminal_event
ON matrix_dispatch_ledger(terminal_event_id)
WHERE terminal_event_id IS NOT NULL;

CREATE TRIGGER matrix_dispatch_ledger_no_delete
BEFORE DELETE ON matrix_dispatch_ledger BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch ledger is append-retained');
END;

CREATE TABLE matrix_dispatch_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('transport_accepted', 'transport_indeterminate', 'server_event', 'redaction')
    ),
    event_id TEXT,
    observation_digest TEXT NOT NULL CHECK (
        length(observation_digest) = 64
        AND observation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id) ON DELETE RESTRICT,
    UNIQUE(stable_txn_id, kind, observation_digest)
) STRICT;

CREATE INDEX matrix_dispatch_observations_by_txn
ON matrix_dispatch_observations(stable_txn_id, observation_id);

CREATE TRIGGER matrix_dispatch_observations_no_update
BEFORE UPDATE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observations are immutable');
END;

CREATE TRIGGER matrix_dispatch_observations_no_delete
BEFORE DELETE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observations are immutable');
END;

INSERT INTO matrix_dispatch_ledger (
    stable_txn_id,
    operation_id,
    room_id,
    payload_sha256,
    binding_revision,
    generation,
    authority_identity,
    authority_epoch,
    grant_payload_digest,
    state,
    last_attempt,
    transport_event_id,
    terminal_event_id,
    send_observation_digest,
    redaction_observation_digest,
    created_at_ms,
    updated_at_ms,
    terminal_at_ms,
    redacted_at_ms
)
SELECT
    stable_txn_id,
    logical_outbox_id,
    room_id,
    payload_sha256,
    binding_revision,
    generation,
    printf('matrix-binding:%lld:%lld', binding_revision, generation),
    NULL,
    NULL,
    CASE state
        WHEN 'sent' THEN 'observed_terminal'
        WHEN 'permanent_failure' THEN 'terminal_failure'
        ELSE 'indeterminate'
    END,
    CASE WHEN attempts > 0 THEN attempts ELSE 1 END,
    sent_event_id,
    sent_event_id,
    NULL,
    NULL,
    created_at_ms,
    updated_at_ms,
    CASE WHEN state IN ('sent', 'permanent_failure') THEN updated_at_ms ELSE NULL END,
    NULL
FROM outbox_messages
WHERE logical_outbox_id IS NOT NULL;
