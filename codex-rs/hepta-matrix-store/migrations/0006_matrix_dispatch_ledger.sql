CREATE TABLE matrix_dispatch_ledger (
    stable_txn_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    homeserver_id TEXT,
    device_id TEXT,
    session_generation INTEGER CHECK (session_generation IS NULL OR session_generation > 0),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    authority_epoch INTEGER CHECK (authority_epoch IS NULL OR authority_epoch > 0),
    grant_payload_sha256 TEXT CHECK (
        grant_payload_sha256 IS NULL OR
        (length(grant_payload_sha256) = 64 AND grant_payload_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    deadline_ms INTEGER CHECK (deadline_ms IS NULL OR deadline_ms >= 0),
    state TEXT NOT NULL CHECK (
        state IN ('prepared', 'dispatched', 'accepted', 'indeterminate',
                  'succeeded', 'failed', 'redacted')
    ),
    transport_event_id TEXT,
    terminal_event_id TEXT,
    send_observation_digest TEXT CHECK (
        send_observation_digest IS NULL OR
        (length(send_observation_digest) = 64 AND send_observation_digest NOT GLOB '*[^0-9a-f]*')
    ),
    redaction_observation_digest TEXT CHECK (
        redaction_observation_digest IS NULL OR
        (length(redaction_observation_digest) = 64 AND redaction_observation_digest NOT GLOB '*[^0-9a-f]*')
    ),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= prepared_at_ms),
    terminal_at_ms INTEGER,
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NOT NULL)
        OR
        (state NOT IN ('succeeded', 'failed', 'redacted') AND terminal_at_ms IS NULL)
    ),
    CHECK (
        (state IN ('succeeded', 'redacted') AND terminal_event_id IS NOT NULL
            AND send_observation_digest IS NOT NULL)
        OR state NOT IN ('succeeded', 'redacted')
    ),
    CHECK (
        (state = 'redacted' AND redaction_observation_digest IS NOT NULL)
        OR state != 'redacted'
    )
) STRICT;

CREATE INDEX matrix_dispatch_ledger_unresolved
ON matrix_dispatch_ledger(state, updated_at_ms, stable_txn_id)
WHERE state IN ('prepared', 'dispatched', 'accepted', 'indeterminate');

CREATE UNIQUE INDEX matrix_dispatch_ledger_terminal_event
ON matrix_dispatch_ledger(terminal_event_id)
WHERE terminal_event_id IS NOT NULL;

CREATE TABLE matrix_dispatch_observations (
    observation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('dispatched', 'transport_accepted', 'indeterminate',
                 'terminal_success', 'terminal_failure', 'redaction')
    ),
    event_id TEXT NOT NULL DEFAULT '',
    evidence_digest TEXT NOT NULL DEFAULT '',
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id) ON DELETE RESTRICT,
    UNIQUE (stable_txn_id, kind, event_id, evidence_digest, observed_at_ms)
) STRICT;

CREATE INDEX matrix_dispatch_observations_by_txn
ON matrix_dispatch_observations(stable_txn_id, observation_seq);

CREATE TRIGGER matrix_dispatch_observations_no_update
BEFORE UPDATE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observations are append-only');
END;

CREATE TRIGGER matrix_dispatch_observations_no_delete
BEFORE DELETE ON matrix_dispatch_observations BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch observations are append-only');
END;
