CREATE TABLE matrix_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36)
) STRICT;

CREATE TRIGGER matrix_meta_no_update
BEFORE UPDATE ON matrix_meta BEGIN
    SELECT RAISE(ABORT, 'matrix store owner is immutable');
END;

CREATE TRIGGER matrix_meta_no_delete
BEFORE DELETE ON matrix_meta BEGIN
    SELECT RAISE(ABORT, 'matrix store owner is immutable');
END;

CREATE TABLE room_bindings (
    room_id TEXT PRIMARY KEY,
    owner_agent_id TEXT NOT NULL,
    agent_user_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    changed_at_ms INTEGER NOT NULL CHECK (changed_at_ms >= 0)
) STRICT;

CREATE TABLE room_threads (
    room_id TEXT NOT NULL,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    project_id TEXT NOT NULL,
    thread_id TEXT,
    changed_at_ms INTEGER NOT NULL CHECK (changed_at_ms >= 0),
    PRIMARY KEY (room_id, binding_revision, generation),
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE inbox_events (
    inbox_cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    sender_user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    origin_server_ts_ms INTEGER NOT NULL CHECK (origin_server_ts_ms >= 0),
    received_at_ms INTEGER NOT NULL CHECK (received_at_ms >= 0),
    state TEXT NOT NULL CHECK (state IN ('pending', 'processed')),
    processed_at_ms INTEGER,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'pending' AND processed_at_ms IS NULL) OR
        (state = 'processed' AND processed_at_ms IS NOT NULL)
    )
) STRICT;

CREATE INDEX inbox_pending_order
ON inbox_events(state, inbox_cursor);

CREATE TABLE inbox_dispatches (
    event_id TEXT PRIMARY KEY,
    client_user_message_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    project_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('begun', 'queued', 'admitted', 'completed')),
    thread_id TEXT,
    queued_submission_id TEXT,
    turn_id TEXT,
    begun_at_ms INTEGER NOT NULL CHECK (begun_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= begun_at_ms),
    completed_at_ms INTEGER,
    FOREIGN KEY (event_id) REFERENCES inbox_events(event_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'begun' AND queued_submission_id IS NULL AND turn_id IS NULL) OR
        (state = 'queued' AND thread_id IS NOT NULL
            AND queued_submission_id IS NOT NULL AND turn_id IS NULL) OR
        (state IN ('admitted', 'completed')
            AND thread_id IS NOT NULL AND turn_id IS NOT NULL)
    ),
    CHECK (
        (state = 'completed' AND completed_at_ms IS NOT NULL
            AND completed_at_ms = updated_at_ms) OR
        (state != 'completed' AND completed_at_ms IS NULL)
    )
) STRICT;

CREATE INDEX inbox_dispatch_pending_order
ON inbox_dispatches(state, begun_at_ms, event_id);

CREATE TABLE outbox_messages (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('text_delta', 'final', 'tool_transition', 'approval', 'terminal')
    ),
    payload BLOB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    logical_txn_count INTEGER NOT NULL CHECK (logical_txn_count > 0),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'in_flight', 'retry_scheduled', 'sent', 'permanent_failure')
    ),
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    next_attempt_at_ms INTEGER NOT NULL CHECK (next_attempt_at_ms >= 0),
    lease_until_ms INTEGER,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    sent_event_id TEXT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'in_flight' AND lease_until_ms IS NOT NULL) OR
        (state != 'in_flight' AND lease_until_ms IS NULL)
    ),
    CHECK (
        (state = 'sent' AND sent_event_id IS NOT NULL) OR
        (state != 'sent' AND sent_event_id IS NULL)
    )
) STRICT;

CREATE INDEX outbox_delivery_order
ON outbox_messages(state, next_attempt_at_ms, outbox_id);

CREATE TABLE outbox_txns (
    txn_id TEXT PRIMARY KEY,
    logical_outbox_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    outbox_id INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    fragment BLOB NOT NULL,
    fragment_sha256 TEXT NOT NULL CHECK (
        length(fragment_sha256) = 64 AND fragment_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    FOREIGN KEY (outbox_id) REFERENCES outbox_messages(outbox_id) ON DELETE RESTRICT,
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX outbox_txns_by_message ON outbox_txns(outbox_id, txn_id);
CREATE UNIQUE INDEX outbox_txns_by_logical_revision
ON outbox_txns(logical_outbox_id, revision);

CREATE TABLE change_log (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    room_id TEXT,
    event_id TEXT,
    txn_id TEXT,
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0)
) STRICT;
