CREATE TABLE matrix_dispatch_ledger (
    operation_id TEXT PRIMARY KEY,
    stable_txn_id TEXT NOT NULL UNIQUE,
    homeserver_id TEXT,
    room_id TEXT NOT NULL,
    device_id TEXT,
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    authority_epoch INTEGER CHECK (authority_epoch IS NULL OR authority_epoch > 0),
    authority_binding_digest TEXT CHECK (
        authority_binding_digest IS NULL OR
        (length(authority_binding_digest) = 64
         AND authority_binding_digest NOT GLOB '*[^0-9a-f]*')
    ),
    grant_id TEXT,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    grant_payload_sha256 TEXT CHECK (
        grant_payload_sha256 IS NULL OR
        (length(grant_payload_sha256) = 64
         AND grant_payload_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    state TEXT NOT NULL CHECK (
        state IN ('prepared', 'dispatched', 'indeterminate', 'observed_succeeded', 'rejected', 'redacted')
    ),
    accepted_event_id TEXT,
    observed_event_id TEXT,
    send_observation_digest TEXT CHECK (
        send_observation_digest IS NULL OR
        (length(send_observation_digest) = 64
         AND send_observation_digest NOT GLOB '*[^0-9a-f]*')
    ),
    redaction_observation_digest TEXT CHECK (
        redaction_observation_digest IS NULL OR
        (length(redaction_observation_digest) = 64
         AND redaction_observation_digest NOT GLOB '*[^0-9a-f]*')
    ),
    last_attempt INTEGER NOT NULL DEFAULT 0 CHECK (last_attempt >= 0),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= prepared_at_ms),
    terminal_at_ms INTEGER CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= prepared_at_ms),
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK ((grant_id IS NULL) = (grant_payload_sha256 IS NULL)),
    CHECK (grant_payload_sha256 IS NULL OR grant_payload_sha256 = payload_sha256),
    CHECK (
        (state IN ('observed_succeeded', 'rejected', 'redacted') AND terminal_at_ms IS NOT NULL) OR
        (state NOT IN ('observed_succeeded', 'rejected', 'redacted') AND terminal_at_ms IS NULL)
    ),
    CHECK (state != 'observed_succeeded' OR observed_event_id IS NOT NULL),
    CHECK (state != 'redacted' OR (observed_event_id IS NOT NULL AND redaction_observation_digest IS NOT NULL))
) STRICT;

CREATE INDEX matrix_dispatch_unresolved
ON matrix_dispatch_ledger(state, updated_at_ms, stable_txn_id);

CREATE INDEX matrix_dispatch_accepted_event
ON matrix_dispatch_ledger(accepted_event_id)
WHERE accepted_event_id IS NOT NULL;

CREATE TABLE matrix_dispatch_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    stable_txn_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('transport_accepted', 'transport_unknown', 'server_succeeded', 'transport_rejected', 'redaction')
    ),
    event_id TEXT,
    digest TEXT NOT NULL CHECK (
        length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    UNIQUE(operation_id, kind, digest)
) STRICT;

CREATE INDEX matrix_dispatch_observations_by_txn
ON matrix_dispatch_observations(stable_txn_id, observation_id);

CREATE TABLE matrix_dispatch_archive (
    operation_id TEXT PRIMARY KEY,
    stable_txn_id TEXT NOT NULL UNIQUE,
    homeserver_id TEXT,
    room_id TEXT NOT NULL,
    device_id TEXT,
    session_generation INTEGER NOT NULL CHECK (session_generation > 0),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    authority_epoch INTEGER CHECK (authority_epoch IS NULL OR authority_epoch > 0),
    authority_binding_digest TEXT,
    grant_id TEXT,
    payload_sha256 TEXT NOT NULL,
    grant_payload_sha256 TEXT,
    state TEXT NOT NULL CHECK (state IN ('observed_succeeded', 'rejected', 'redacted')),
    accepted_event_id TEXT,
    observed_event_id TEXT,
    send_observation_digest TEXT,
    redaction_observation_digest TEXT,
    last_attempt INTEGER NOT NULL CHECK (last_attempt >= 0),
    prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= prepared_at_ms),
    terminal_at_ms INTEGER NOT NULL CHECK (terminal_at_ms >= prepared_at_ms),
    archived_at_ms INTEGER NOT NULL CHECK (archived_at_ms >= terminal_at_ms),
    CHECK ((grant_id IS NULL) = (grant_payload_sha256 IS NULL)),
    CHECK (grant_payload_sha256 IS NULL OR grant_payload_sha256 = payload_sha256),
    CHECK (state != 'observed_succeeded' OR observed_event_id IS NOT NULL),
    CHECK (state != 'redacted' OR (observed_event_id IS NOT NULL AND redaction_observation_digest IS NOT NULL))
) STRICT;

CREATE INDEX matrix_dispatch_archive_event
ON matrix_dispatch_archive(observed_event_id)
WHERE observed_event_id IS NOT NULL;
