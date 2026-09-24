-- Destination-owned terminal proof for one exact kernel.operations identity.
-- Absence is never a negative proof: observers may terminalize NotApplied only
-- from an immutable row committed by the destination owner.
CREATE TABLE cognitive_operation_destination_terminal (
    destination_id TEXT NOT NULL CHECK (
        length(trim(destination_id)) BETWEEN 1 AND 128 AND
        instr(destination_id, char(0)) = 0
    ),
    operation_id TEXT NOT NULL CHECK (
        length(trim(operation_id)) BETWEEN 1 AND 128 AND
        instr(operation_id, char(0)) = 0
    ),
    semantic_sha256 TEXT NOT NULL CHECK (
        length(semantic_sha256) = 64 AND
        semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    disposition TEXT NOT NULL CHECK (
        disposition IN ('applied', 'not_applied', 'quarantined')
    ),
    evidence TEXT NOT NULL CHECK (
        length(trim(evidence)) BETWEEN 1 AND 4096 AND
        instr(evidence, char(0)) = 0
    ),
    recorded_at_unix_ms INTEGER NOT NULL CHECK (recorded_at_unix_ms > 0),
    PRIMARY KEY (destination_id, operation_id)
) STRICT;

CREATE TRIGGER cognitive_operation_destination_terminal_no_update
BEFORE UPDATE ON cognitive_operation_destination_terminal BEGIN
    SELECT RAISE(ABORT, 'operation destination terminal proof is immutable');
END;

CREATE TRIGGER cognitive_operation_destination_terminal_no_delete
BEFORE DELETE ON cognitive_operation_destination_terminal BEGIN
    SELECT RAISE(ABORT, 'operation destination terminal proof is immutable');
END;

CREATE INDEX cognitive_operation_destination_terminal_disposition_lookup
ON cognitive_operation_destination_terminal(
    destination_id, disposition, recorded_at_unix_ms, operation_id
);
