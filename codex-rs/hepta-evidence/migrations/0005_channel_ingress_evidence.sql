CREATE TABLE channel_ingress_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64
        AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    adapter_id TEXT NOT NULL,
    source_event_sha256 TEXT NOT NULL CHECK (
        length(source_event_sha256) = 64
        AND source_event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_payload_sha256 TEXT NOT NULL CHECK (
        length(event_payload_sha256) = 64
        AND event_payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    target_thread_sha256 TEXT NOT NULL CHECK (
        length(target_thread_sha256) = 64
        AND target_thread_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_cursor_sha256 TEXT CHECK (
        predecessor_cursor_sha256 IS NULL
        OR (
            length(predecessor_cursor_sha256) = 64
            AND predecessor_cursor_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    next_cursor_sha256 TEXT NOT NULL CHECK (
        length(next_cursor_sha256) = 64
        AND next_cursor_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    received_at_unix_ms INTEGER NOT NULL CHECK (received_at_unix_ms > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (
        length(evidence_sha256) = 64
        AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    UNIQUE(scope_sha256, source_event_sha256)
);

CREATE INDEX channel_ingress_events_scope_seq
    ON channel_ingress_events(scope_sha256, seq);

CREATE TABLE channel_ingress_receipts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL UNIQUE,
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64
        AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    terminal_kind TEXT NOT NULL CHECK (
        terminal_kind IN ('accepted', 'rejected', 'indeterminate')
    ),
    thread_id TEXT,
    turn_id TEXT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (
        length(evidence_sha256) = 64
        AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    CHECK (
        (terminal_kind = 'accepted' AND thread_id IS NOT NULL AND turn_id IS NOT NULL)
        OR
        (terminal_kind IN ('rejected', 'indeterminate') AND thread_id IS NULL AND turn_id IS NULL)
    ),
    FOREIGN KEY(event_id)
        REFERENCES channel_ingress_events(event_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX channel_ingress_receipts_scope_seq
    ON channel_ingress_receipts(scope_sha256, seq);

CREATE TRIGGER channel_ingress_events_no_update
BEFORE UPDATE ON channel_ingress_events
BEGIN
    SELECT RAISE(ABORT, 'channel ingress events are immutable');
END;

CREATE TRIGGER channel_ingress_events_no_delete
BEFORE DELETE ON channel_ingress_events
BEGIN
    SELECT RAISE(ABORT, 'channel ingress events are immutable');
END;

CREATE TRIGGER channel_ingress_receipts_no_update
BEFORE UPDATE ON channel_ingress_receipts
BEGIN
    SELECT RAISE(ABORT, 'channel ingress receipts are immutable');
END;

CREATE TRIGGER channel_ingress_receipts_no_delete
BEFORE DELETE ON channel_ingress_receipts
BEGIN
    SELECT RAISE(ABORT, 'channel ingress receipts are immutable');
END;
