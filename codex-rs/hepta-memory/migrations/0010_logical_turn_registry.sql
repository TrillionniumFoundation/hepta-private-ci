-- E33 local-qualification-only stable logical-turn registry.
--
-- A logical turn identity is stable across physical attempts/spawns.  Attempt
-- rows are an immutable transition stream: the initial `active` row is never
-- updated; an expired, unadmitted attempt is superseded by appending a
-- `superseded` row, a terminal lease marker, and a new `active` row in one
-- BEGIN IMMEDIATE transaction.  The Rust loader verifies the stream/head CAS
-- and binds every attempt to its exact historical lease witness.  This
-- registry grants no provider, scheduler, rollout, or external-effect
-- authority.

CREATE TABLE cognitive_logical_turns (
    owner_agent_id TEXT NOT NULL CHECK (
        length(owner_agent_id) = 36 AND instr(owner_agent_id, char(0)) = 0
    ),
    logical_turn_id TEXT NOT NULL CHECK (
        length(trim(logical_turn_id)) BETWEEN 1 AND 512 AND
        instr(logical_turn_id, char(0)) = 0
    ),
    scope_key TEXT NOT NULL CHECK (
        length(trim(scope_key)) BETWEEN 1 AND 512 AND
        instr(scope_key, char(0)) = 0
    ),
    logical_binding_sha256 TEXT NOT NULL CHECK (
        length(logical_binding_sha256) = 64 AND
        logical_binding_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    identity_sha256 TEXT NOT NULL CHECK (
        length(identity_sha256) = 64 AND
        identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL CHECK (recorded_at_unix_seconds >= 0),
    PRIMARY KEY (owner_agent_id, logical_turn_id)
) STRICT;

CREATE TRIGGER cognitive_logical_turns_no_update
BEFORE UPDATE ON cognitive_logical_turns BEGIN
    SELECT RAISE(ABORT, 'logical-turn identities are immutable');
END;

CREATE TRIGGER cognitive_logical_turns_no_delete
BEFORE DELETE ON cognitive_logical_turns BEGIN
    SELECT RAISE(ABORT, 'logical-turn identities are immutable');
END;

CREATE TABLE cognitive_logical_turn_attempts (
    owner_agent_id TEXT NOT NULL CHECK (
        length(owner_agent_id) = 36 AND instr(owner_agent_id, char(0)) = 0
    ),
    logical_turn_id TEXT NOT NULL CHECK (
        length(trim(logical_turn_id)) BETWEEN 1 AND 512 AND
        instr(logical_turn_id, char(0)) = 0
    ),
    registry_sequence INTEGER NOT NULL CHECK (registry_sequence > 0),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    attempt_id TEXT NOT NULL CHECK (
        length(trim(attempt_id)) BETWEEN 1 AND 512 AND
        instr(attempt_id, char(0)) = 0
    ),
    transition TEXT NOT NULL CHECK (transition IN ('active', 'superseded')),
    superseded_by_attempt_id TEXT CHECK (
        superseded_by_attempt_id IS NULL OR (
            length(trim(superseded_by_attempt_id)) BETWEEN 1 AND 512 AND
            instr(superseded_by_attempt_id, char(0)) = 0
        )
    ),
    logical_binding_sha256 TEXT NOT NULL CHECK (
        length(logical_binding_sha256) = 64 AND
        logical_binding_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    lease_id TEXT NOT NULL CHECK (
        length(trim(lease_id)) BETWEEN 1 AND 512 AND
        instr(lease_id, char(0)) = 0
    ),
    lease_sequence INTEGER NOT NULL CHECK (lease_sequence > 0),
    lease_head_sha256 TEXT NOT NULL CHECK (
        length(lease_head_sha256) = 64 AND
        lease_head_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    journal_id TEXT NOT NULL CHECK (
        length(trim(journal_id)) BETWEEN 1 AND 512 AND
        instr(journal_id, char(0)) = 0
    ),
    trajectory_id TEXT NOT NULL CHECK (
        length(trim(trajectory_id)) BETWEEN 1 AND 512 AND
        instr(trajectory_id, char(0)) = 0
    ),
    occurrence_key TEXT NOT NULL CHECK (
        length(trim(occurrence_key)) BETWEEN 1 AND 512 AND
        instr(occurrence_key, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    lease_expires_at_unix_seconds INTEGER NOT NULL CHECK (
        lease_expires_at_unix_seconds > 0
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND
        previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    attempt_sha256 TEXT NOT NULL CHECK (
        length(attempt_sha256) = 64 AND
        attempt_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL CHECK (recorded_at_unix_seconds >= 0),
    PRIMARY KEY (owner_agent_id, logical_turn_id, registry_sequence),
    FOREIGN KEY (owner_agent_id, logical_turn_id)
        REFERENCES cognitive_logical_turns(owner_agent_id, logical_turn_id)
        ON DELETE RESTRICT,
    CHECK (
        (transition = 'active' AND superseded_by_attempt_id IS NULL) OR
        (transition = 'superseded' AND superseded_by_attempt_id IS NOT NULL)
    ),
    CHECK (
        (registry_sequence = 1 AND transition = 'active' AND attempt_no = 1) OR
        registry_sequence > 1
    )
) STRICT;

CREATE TRIGGER cognitive_logical_turn_attempts_no_update
BEFORE UPDATE ON cognitive_logical_turn_attempts BEGIN
    SELECT RAISE(ABORT, 'logical-turn attempts are immutable');
END;

CREATE TRIGGER cognitive_logical_turn_attempts_no_delete
BEFORE DELETE ON cognitive_logical_turn_attempts BEGIN
    SELECT RAISE(ABORT, 'logical-turn attempts are immutable');
END;

CREATE UNIQUE INDEX cognitive_logical_turn_attempts_record_digest
ON cognitive_logical_turn_attempts(
    owner_agent_id, logical_turn_id, registry_sequence, attempt_sha256
);

CREATE INDEX cognitive_logical_turn_attempts_lookup
ON cognitive_logical_turn_attempts(
    owner_agent_id, logical_turn_id, registry_sequence
);

CREATE INDEX cognitive_logical_turn_attempts_attempt_lookup
ON cognitive_logical_turn_attempts(owner_agent_id, attempt_id, registry_sequence);

CREATE INDEX cognitive_logical_turn_attempts_lease_lookup
ON cognitive_logical_turn_attempts(owner_agent_id, lease_id, lease_sequence);

CREATE INDEX cognitive_logical_turn_attempts_journal_lookup
ON cognitive_logical_turn_attempts(owner_agent_id, journal_id, registry_sequence);

CREATE INDEX cognitive_logical_turn_attempts_trajectory_lookup
ON cognitive_logical_turn_attempts(owner_agent_id, trajectory_id, registry_sequence);
