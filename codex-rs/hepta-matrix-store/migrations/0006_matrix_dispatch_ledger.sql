-- Durable Matrix egress truth model.
--
-- The existing outbox remains the sole sender queue and stable_txn_id remains
-- the canonical Matrix transaction identity. This ledger records the effect
-- lifecycle and trusted observations without creating a second sender.
CREATE TABLE matrix_dispatch_ledger (
    stable_txn_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE CHECK (
        length(operation_id) BETWEEN 1 AND 128
        AND operation_id NOT GLOB '*[^A-Za-z0-9._:/-]*'
    ),
    room_id TEXT NOT NULL,
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority_epoch INTEGER CHECK (authority_epoch IS NULL OR authority_epoch > 0),
    authority_binding_digest TEXT CHECK (
        authority_binding_digest IS NULL OR (
            length(authority_binding_digest) = 64
            AND authority_binding_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    grant_id TEXT CHECK (
        grant_id IS NULL OR (
            length(grant_id) BETWEEN 1 AND 128
            AND grant_id NOT GLOB '*[^A-Za-z0-9._:/-]*'
        )
    ),
    grant_payload_sha256 TEXT CHECK (
        grant_payload_sha256 IS NULL OR (
            length(grant_payload_sha256) = 64
            AND grant_payload_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    state TEXT NOT NULL CHECK (
        state IN (
            'prepared', 'dispatched', 'accepted', 'indeterminate',
            'observed_succeeded', 'observed_failed', 'redacted'
        )
    ),
    attempt INTEGER NOT NULL CHECK (attempt >= 0),
    accepted_event_id TEXT,
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
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    dispatched_at_ms INTEGER,
    accepted_at_ms INTEGER,
    terminal_observed_at_ms INTEGER,
    redacted_at_ms INTEGER,
    archived_at_ms INTEGER,
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (grant_id IS NULL AND grant_payload_sha256 IS NULL)
        OR (grant_id IS NOT NULL AND grant_payload_sha256 IS NOT NULL)
    ),
    CHECK (
        grant_payload_sha256 IS NULL OR grant_payload_sha256 = payload_sha256
    ),
    CHECK (
        accepted_event_id IS NULL OR state IN (
            'accepted', 'observed_succeeded', 'redacted'
        )
    ),
    CHECK (
        terminal_event_id IS NULL OR state IN ('observed_succeeded', 'redacted')
    ),
    CHECK (
        redaction_observation_digest IS NULL OR state = 'redacted'
    )
) STRICT;

CREATE INDEX matrix_dispatch_unresolved
ON matrix_dispatch_ledger(state, prepared_at_ms, stable_txn_id)
WHERE state IN ('prepared', 'dispatched', 'accepted', 'indeterminate');

CREATE UNIQUE INDEX matrix_dispatch_terminal_event
ON matrix_dispatch_ledger(terminal_event_id)
WHERE terminal_event_id IS NOT NULL;

CREATE TABLE matrix_dispatch_observations (
    observation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'dispatched', 'accepted', 'retryable', 'indeterminate',
            'terminal_success', 'terminal_failure', 'redaction'
        )
    ),
    observation_digest TEXT NOT NULL CHECK (
        length(observation_digest) = 64
        AND observation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    server_event_id TEXT,
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    UNIQUE (stable_txn_id, observation_kind, observation_digest),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER matrix_dispatch_observations_no_update
BEFORE UPDATE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation is immutable');
END;

CREATE TRIGGER matrix_dispatch_observations_no_delete
BEFORE DELETE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observation is immutable');
END;

CREATE TRIGGER matrix_dispatch_ledger_no_delete
BEFORE DELETE ON matrix_dispatch_ledger BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch ledger is append-preserving');
END;
