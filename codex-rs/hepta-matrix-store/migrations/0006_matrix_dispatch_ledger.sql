-- Durable Matrix dispatch ledger. The outbox remains the transport queue; this
-- ledger is the terminal-truth owner for one stable Matrix transaction.
CREATE TABLE matrix_dispatch_ledger (
    stable_txn_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE CHECK (
        length(operation_id) BETWEEN 1 AND 512
        AND operation_id NOT GLOB '*[^ -~]*'
    ),
    logical_outbox_id TEXT NOT NULL CHECK (
        length(logical_outbox_id) BETWEEN 1 AND 512
        AND logical_outbox_id NOT GLOB '*[^ -~]*'
    ),
    room_id TEXT NOT NULL,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority_epoch INTEGER CHECK (authority_epoch > 0),
    grant_id TEXT CHECK (
        grant_id IS NULL OR (
            length(grant_id) BETWEEN 1 AND 512
            AND grant_id NOT GLOB '*[^ -~]*'
        )
    ),
    grant_payload_sha256 TEXT CHECK (
        grant_payload_sha256 IS NULL OR (
            length(grant_payload_sha256) = 64
            AND grant_payload_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    state TEXT NOT NULL CHECK (
        state IN ('dispatched', 'accepted', 'indeterminate', 'succeeded', 'failed', 'redacted')
    ),
    accepted_event_id TEXT,
    terminal_event_id TEXT,
    transport_observation_sha256 TEXT CHECK (
        transport_observation_sha256 IS NULL OR (
            length(transport_observation_sha256) = 64
            AND transport_observation_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
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
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= prepared_at_ms),
    terminal_observed_at_ms INTEGER,
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (authority_epoch IS NULL AND grant_id IS NULL AND grant_payload_sha256 IS NULL)
        OR
        (authority_epoch IS NOT NULL AND grant_id IS NOT NULL
            AND grant_payload_sha256 = payload_sha256)
    ),
    CHECK (
        (state = 'accepted' AND accepted_event_id IS NOT NULL)
        OR state != 'accepted'
    ),
    CHECK (
        (state = 'succeeded' AND terminal_event_id IS NOT NULL
            AND send_observation_sha256 IS NOT NULL
            AND terminal_observed_at_ms IS NOT NULL)
        OR state != 'succeeded'
    ),
    CHECK (
        (state = 'redacted' AND terminal_event_id IS NOT NULL
            AND redaction_observation_sha256 IS NOT NULL
            AND terminal_observed_at_ms IS NOT NULL)
        OR state != 'redacted'
    ),
    CHECK (
        (state = 'failed' AND terminal_observed_at_ms IS NOT NULL)
        OR state != 'failed'
    ),
    CHECK (
        (state IN ('succeeded', 'failed', 'redacted') AND terminal_observed_at_ms IS NOT NULL)
        OR
        (state IN ('dispatched', 'accepted', 'indeterminate') AND terminal_observed_at_ms IS NULL)
    )
) STRICT;

CREATE INDEX matrix_dispatch_unresolved
ON matrix_dispatch_ledger(state, updated_at_ms, stable_txn_id)
WHERE state IN ('dispatched', 'accepted', 'indeterminate');

CREATE UNIQUE INDEX matrix_dispatch_accepted_event_unique
ON matrix_dispatch_ledger(accepted_event_id)
WHERE accepted_event_id IS NOT NULL;

CREATE UNIQUE INDEX matrix_dispatch_terminal_event_unique
ON matrix_dispatch_ledger(terminal_event_id)
WHERE terminal_event_id IS NOT NULL;

CREATE TABLE matrix_dispatch_observations (
    observation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'dispatch_started',
            'transport_accepted',
            'transport_indeterminate',
            'transport_rejected',
            'homeserver_event',
            'redaction'
        )
    ),
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    event_id TEXT,
    observation_sha256 TEXT NOT NULL CHECK (
        length(observation_sha256) = 64
        AND observation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id)
        ON DELETE RESTRICT,
    UNIQUE (stable_txn_id, observation_kind, observation_sha256)
) STRICT;

CREATE INDEX matrix_dispatch_observations_by_txn
ON matrix_dispatch_observations(stable_txn_id, observation_seq);

CREATE TABLE matrix_dispatch_authority_claims (
    stable_txn_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
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
    homeserver_id TEXT NOT NULL CHECK (length(homeserver_id) BETWEEN 1 AND 2048),
    matrix_user_id TEXT NOT NULL CHECK (length(matrix_user_id) BETWEEN 1 AND 255),
    device_id TEXT NOT NULL CHECK (length(device_id) BETWEEN 1 AND 255),
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    revocation_revision INTEGER NOT NULL CHECK (revocation_revision > 0),
    grant_id TEXT NOT NULL UNIQUE CHECK (
        length(grant_id) BETWEEN 1 AND 128
        AND grant_id NOT GLOB '*[^A-Za-z0-9_.:/-]*'
    ),
    request_sha256 TEXT NOT NULL CHECK (
        length(request_sha256) = 64
        AND request_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64
        AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > 0),
    claimed_at_ms INTEGER NOT NULL CHECK (claimed_at_ms >= 0),
    CHECK (expires_at_ms > claimed_at_ms),
    PRIMARY KEY (stable_txn_id, attempt),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id)
        ON DELETE RESTRICT
) STRICT;

CREATE INDEX matrix_dispatch_authority_claims_by_txn
ON matrix_dispatch_authority_claims(stable_txn_id, attempt);

CREATE TRIGGER matrix_dispatch_authority_claims_no_update
BEFORE UPDATE ON matrix_dispatch_authority_claims BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch authority claim is immutable');
END;

CREATE TRIGGER matrix_dispatch_authority_claims_no_delete
BEFORE DELETE ON matrix_dispatch_authority_claims BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch authority claim is immutable');
END;

CREATE TRIGGER matrix_dispatch_ledger_identity_immutable
BEFORE UPDATE OF
    stable_txn_id, operation_id, logical_outbox_id, room_id,
    binding_revision, generation, payload_sha256,
    authority_epoch, grant_id, grant_payload_sha256
ON matrix_dispatch_ledger BEGIN
    SELECT RAISE(ABORT, 'Matrix dispatch identity is immutable');
END;

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
