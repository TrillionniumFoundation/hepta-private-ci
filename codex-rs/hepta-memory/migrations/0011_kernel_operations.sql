-- Durable kernel.operations semantic identity bound to the existing
-- Agent-local event/outbox transaction owner.
--
-- The row is immutable. Current effect state is derived from the verified
-- append-only event journal; lease generations/fences remain owned by the
-- existing lease chain. This avoids a second mutable state machine while
-- making prepare-intent + outbox publication one SQLite transaction.

CREATE TABLE cognitive_operation_ledger (
    operation_id TEXT NOT NULL CHECK (
        length(trim(operation_id)) BETWEEN 1 AND 128 AND
        instr(operation_id, char(0)) = 0
    ),
    semantic_sha256 TEXT NOT NULL CHECK (
        length(semantic_sha256) = 64 AND semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scope_id TEXT NOT NULL CHECK (
        length(trim(scope_id)) BETWEEN 1 AND 128 AND
        instr(scope_id, char(0)) = 0
    ),
    owner_id TEXT NOT NULL CHECK (
        length(trim(owner_id)) BETWEEN 1 AND 128 AND
        instr(owner_id, char(0)) = 0
    ),
    destination_id TEXT NOT NULL CHECK (
        length(trim(destination_id)) BETWEEN 1 AND 128 AND
        instr(destination_id, char(0)) = 0
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expected_predecessor_sha256 TEXT CHECK (
        expected_predecessor_sha256 IS NULL OR (
            length(expected_predecessor_sha256) = 64 AND
            expected_predecessor_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    lease_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    outbox_id TEXT NOT NULL,
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
    prepared_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (operation_id),
    UNIQUE (semantic_sha256),
    UNIQUE (lease_id, event_id),
    UNIQUE (lease_id, outbox_id),
    FOREIGN KEY (lease_id, event_id)
        REFERENCES cognitive_local_events(lease_id, event_id) ON DELETE RESTRICT,
    FOREIGN KEY (lease_id, outbox_id)
        REFERENCES cognitive_local_outbox(lease_id, outbox_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER cognitive_operation_ledger_no_update
BEFORE UPDATE ON cognitive_operation_ledger BEGIN
    SELECT RAISE(ABORT, 'operation ledger is immutable');
END;

CREATE TRIGGER cognitive_operation_ledger_no_delete
BEFORE DELETE ON cognitive_operation_ledger BEGIN
    SELECT RAISE(ABORT, 'operation ledger is immutable');
END;

CREATE INDEX cognitive_operation_ledger_destination_lookup
ON cognitive_operation_ledger(destination_id, operation_id);

CREATE INDEX cognitive_operation_ledger_lease_lookup
ON cognitive_operation_ledger(lease_id, generation, operation_id);
