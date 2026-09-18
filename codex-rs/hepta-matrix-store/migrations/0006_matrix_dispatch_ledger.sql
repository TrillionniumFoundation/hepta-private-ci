CREATE TABLE matrix_dispatch_ledger (
    operation_id TEXT PRIMARY KEY,
    stable_txn_id TEXT NOT NULL UNIQUE,
    homeserver_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    authority_identity TEXT NOT NULL,
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    grant_payload_digest TEXT NOT NULL CHECK (
        length(grant_payload_digest) = 64 AND grant_payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    deadline_ms INTEGER NOT NULL CHECK (deadline_ms >= 0),
    state TEXT NOT NULL CHECK (
        state IN (
            'prepared', 'dispatched', 'accepted', 'indeterminate',
            'succeeded', 'failed', 'redacted'
        )
    ),
    accepted_event_id TEXT,
    server_event_id TEXT,
    transport_observation_digest TEXT CHECK (
        transport_observation_digest IS NULL OR (
            length(transport_observation_digest) = 64
            AND transport_observation_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
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
    terminal_at_ms INTEGER CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= created_at_ms),
    CHECK (
        (state IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NOT NULL)
        OR
        (state NOT IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NULL)
    ),
    CHECK (
        (state IN ('succeeded', 'redacted') AND server_event_id IS NOT NULL)
        OR
        (state NOT IN ('succeeded', 'redacted') AND server_event_id IS NULL)
    ),
    CHECK (
        (state = 'failed' AND send_observation_digest IS NOT NULL)
        OR state != 'failed'
    )
) STRICT;

CREATE UNIQUE INDEX matrix_dispatch_ledger_by_accepted_event
ON matrix_dispatch_ledger(accepted_event_id)
WHERE accepted_event_id IS NOT NULL;

CREATE UNIQUE INDEX matrix_dispatch_ledger_by_server_event
ON matrix_dispatch_ledger(server_event_id)
WHERE server_event_id IS NOT NULL;

CREATE INDEX matrix_dispatch_ledger_unresolved
ON matrix_dispatch_ledger(state, updated_at_ms, operation_id);

CREATE TABLE matrix_dispatch_observations (
    observation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'dispatch_attempt', 'transport_accepted', 'transport_indeterminate',
            'server_succeeded', 'server_failed', 'redaction'
        )
    ),
    observation_digest TEXT NOT NULL CHECK (
        length(observation_digest) = 64
        AND observation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    event_id TEXT NOT NULL DEFAULT '',
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    FOREIGN KEY (operation_id) REFERENCES matrix_dispatch_ledger(operation_id) ON DELETE RESTRICT,
    UNIQUE(operation_id, observation_kind, observation_digest, event_id)
) STRICT;

CREATE TRIGGER matrix_dispatch_observations_no_update
BEFORE UPDATE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation evidence is append-only');
END;

CREATE TRIGGER matrix_dispatch_observations_no_delete
BEFORE DELETE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation evidence is append-only');
END;

CREATE TABLE matrix_server_event_observations (
    event_id TEXT PRIMARY KEY,
    stable_txn_id TEXT,
    room_id TEXT NOT NULL,
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    observation_digest TEXT NOT NULL CHECK (
        length(observation_digest) = 64
        AND observation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0)
) STRICT;

CREATE UNIQUE INDEX matrix_server_event_observations_by_txn
ON matrix_server_event_observations(stable_txn_id)
WHERE stable_txn_id IS NOT NULL;

CREATE TRIGGER matrix_server_event_observations_no_update
BEFORE UPDATE ON matrix_server_event_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix server-event observation evidence is append-only');
END;

CREATE TRIGGER matrix_server_event_observations_no_delete
BEFORE DELETE ON matrix_server_event_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix server-event observation evidence is append-only');
END;
