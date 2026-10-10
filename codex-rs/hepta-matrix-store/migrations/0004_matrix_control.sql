CREATE TABLE pending_approvals (
    approval_key TEXT PRIMARY KEY,
    pending_json TEXT NOT NULL CHECK (length(pending_json) BETWEEN 2 AND 8192),
    request_id_json TEXT NOT NULL UNIQUE CHECK (length(request_id_json) BETWEEN 1 AND 1024),
    request_kind TEXT NOT NULL CHECK (request_kind IN ('command_execution', 'file_change')),
    attached_agent_generation INTEGER NOT NULL CHECK (attached_agent_generation > 0),
    process_incarnation TEXT NOT NULL CHECK (length(process_incarnation) BETWEEN 1 AND 512),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
    resolution_decision TEXT CHECK (
        resolution_decision IS NULL OR
        resolution_decision IN ('accept', 'accept_for_session', 'decline', 'cancel')
    ),
    resolving_at_ms INTEGER,
    CHECK ((resolution_decision IS NULL) = (resolving_at_ms IS NULL)),
    CHECK (resolving_at_ms IS NULL OR resolving_at_ms >= created_at_ms)
) STRICT;

CREATE TABLE matrix_control_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_thread_id TEXT,
    active_turn_id TEXT,
    CHECK ((active_thread_id IS NULL) = (active_turn_id IS NULL))
) STRICT;

INSERT INTO matrix_control_state (singleton, active_thread_id, active_turn_id)
VALUES (1, NULL, NULL);

CREATE TABLE matrix_control_events (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    event_json TEXT NOT NULL CHECK (length(event_json) BETWEEN 2 AND 8192),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms > 0)
) STRICT;
