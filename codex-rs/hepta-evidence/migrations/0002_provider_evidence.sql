CREATE TABLE provider_invocation_intents (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL UNIQUE,
    request_binding_id TEXT NOT NULL,
    attempt_nonce_sha256 TEXT NOT NULL CHECK (
        length(attempt_nonce_sha256) = 64
        AND attempt_nonce_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    request_kind TEXT NOT NULL
        CHECK (request_kind IN ('turn', 'prewarm', 'compaction', 'memory')),
    provider_id TEXT NOT NULL,
    provider_config_sha256 TEXT NOT NULL CHECK (
        length(provider_config_sha256) = 64
        AND provider_config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    model TEXT NOT NULL,
    transport TEXT NOT NULL CHECK (transport IN ('http', 'web_socket')),
    endpoint_sha256 TEXT NOT NULL CHECK (
        length(endpoint_sha256) = 64
        AND endpoint_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    logical_request_sha256 TEXT NOT NULL CHECK (
        length(logical_request_sha256) = 64
        AND logical_request_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    wire_semantic_sha256 TEXT NOT NULL CHECK (
        length(wire_semantic_sha256) = 64
        AND wire_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_response_id_sha256 TEXT CHECK (
        previous_response_id_sha256 IS NULL
        OR (
            length(previous_response_id_sha256) = 64
            AND previous_response_id_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    generate INTEGER NOT NULL CHECK (generate IN (0, 1)),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    UNIQUE(attempt_id, request_binding_id)
);

CREATE INDEX provider_invocation_intents_thread_seq
    ON provider_invocation_intents(thread_id, seq);

CREATE INDEX provider_invocation_intents_binding_seq
    ON provider_invocation_intents(request_binding_id, seq);

CREATE TABLE provider_invocation_terminals (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    attempt_id TEXT NOT NULL UNIQUE,
    request_binding_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    terminal_kind TEXT NOT NULL CHECK (
        terminal_kind IN ('completed', 'rejected', 'not_dispatched', 'indeterminate')
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    FOREIGN KEY(attempt_id, request_binding_id)
        REFERENCES provider_invocation_intents(attempt_id, request_binding_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX provider_invocation_terminals_thread_seq
    ON provider_invocation_terminals(thread_id, seq);

CREATE TRIGGER provider_invocation_intents_no_update
BEFORE UPDATE ON provider_invocation_intents
BEGIN
    SELECT RAISE(ABORT, 'provider invocation intents are immutable');
END;

CREATE TRIGGER provider_invocation_intents_no_delete
BEFORE DELETE ON provider_invocation_intents
BEGIN
    SELECT RAISE(ABORT, 'provider invocation intents are immutable');
END;

CREATE TRIGGER provider_invocation_terminals_no_update
BEFORE UPDATE ON provider_invocation_terminals
BEGIN
    SELECT RAISE(ABORT, 'provider invocation terminals are immutable');
END;

CREATE TRIGGER provider_invocation_terminals_no_delete
BEFORE DELETE ON provider_invocation_terminals
BEGIN
    SELECT RAISE(ABORT, 'provider invocation terminals are immutable');
END;
