-- H8 local-development-only authoritative lease and intent/outbox journal.
--
-- Every row is append-only.  The current lease is the last row for a
-- lease_id; rotations and release/rollback are represented by another row,
-- never by an UPDATE.  Event and outbox admissions are paired by the writer
-- in one BEGIN IMMEDIATE transaction.  The outbox is only a local intent /
-- dispatch record: it is not an external-effect acknowledgement.

CREATE TABLE cognitive_local_leases (
    lease_id TEXT NOT NULL CHECK (
        length(trim(lease_id)) BETWEEN 1 AND 512 AND
        instr(lease_id, char(0)) = 0
    ),
    lease_sequence INTEGER NOT NULL CHECK (lease_sequence > 0),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    state TEXT NOT NULL CHECK (state IN ('active', 'released', 'rolled_back')),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    lease_sha256 TEXT NOT NULL CHECK (
        length(lease_sha256) = 64 AND lease_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (lease_id, lease_sequence),
    UNIQUE (lease_id, lease_sha256)
) STRICT;

CREATE TRIGGER cognitive_local_leases_no_update
BEFORE UPDATE ON cognitive_local_leases BEGIN
    SELECT RAISE(ABORT, 'local lease journal is immutable');
END;

CREATE TRIGGER cognitive_local_leases_no_delete
BEFORE DELETE ON cognitive_local_leases BEGIN
    SELECT RAISE(ABORT, 'local lease journal is immutable');
END;

-- The journal is append-only, so a historical active row cannot be updated
-- when a release/rotation is appended.  Keep a named lookup index rather than
-- a UNIQUE partial index; the writer's BEGIN IMMEDIATE + latest-head CAS is
-- the authoritative single-active invariant.
CREATE INDEX cognitive_local_leases_one_active
ON cognitive_local_leases(lease_id, state, lease_sequence);

CREATE INDEX cognitive_local_leases_owner_lookup
ON cognitive_local_leases(owner_agent_id, lease_id, lease_sequence);

CREATE TABLE cognitive_local_events (
    lease_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    event_id TEXT NOT NULL CHECK (
        length(trim(event_id)) BETWEEN 1 AND 512 AND
        instr(event_id, char(0)) = 0
    ),
    occurrence_key TEXT NOT NULL CHECK (
        length(trim(occurrence_key)) BETWEEN 1 AND 512 AND
        instr(occurrence_key, char(0)) = 0
    ),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    event_kind TEXT NOT NULL CHECK (
        event_kind IN (
            'admitted', 'indeterminate', 'reconcile_committed',
            'reconcile_rejected', 'reconcile_still_indeterminate', 'rolled_back'
        )
    ),
    payload_json TEXT NOT NULL CHECK (
        length(payload_json) BETWEEN 1 AND 65536 AND
        instr(payload_json, char(0)) = 0
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_sha256 TEXT NOT NULL CHECK (
        length(event_sha256) = 64 AND event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (lease_id, event_sequence),
    UNIQUE (lease_id, event_id)
) STRICT;

CREATE TRIGGER cognitive_local_events_no_update
BEFORE UPDATE ON cognitive_local_events BEGIN
    SELECT RAISE(ABORT, 'local events are immutable');
END;

CREATE TRIGGER cognitive_local_events_no_delete
BEFORE DELETE ON cognitive_local_events BEGIN
    SELECT RAISE(ABORT, 'local events are immutable');
END;

CREATE UNIQUE INDEX cognitive_local_events_admission_occurrence
ON cognitive_local_events(lease_id, occurrence_key)
WHERE event_kind = 'admitted';

CREATE UNIQUE INDEX cognitive_local_events_transition_kind
ON cognitive_local_events(lease_id, occurrence_key, event_kind);

CREATE INDEX cognitive_local_events_owner_lookup
ON cognitive_local_events(owner_agent_id, lease_id, event_sequence);

CREATE TABLE cognitive_local_outbox (
    lease_id TEXT NOT NULL,
    outbox_sequence INTEGER NOT NULL CHECK (outbox_sequence > 0),
    outbox_id TEXT NOT NULL CHECK (
        length(trim(outbox_id)) BETWEEN 1 AND 512 AND
        instr(outbox_id, char(0)) = 0
    ),
    event_id TEXT NOT NULL,
    occurrence_key TEXT NOT NULL CHECK (
        length(trim(occurrence_key)) BETWEEN 1 AND 512 AND
        instr(occurrence_key, char(0)) = 0
    ),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    topic TEXT NOT NULL CHECK (
        length(trim(topic)) BETWEEN 1 AND 256 AND
        instr(topic, char(0)) = 0
    ),
    payload_json TEXT NOT NULL CHECK (
        length(payload_json) BETWEEN 1 AND 65536 AND
        instr(payload_json, char(0)) = 0
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    outbox_sha256 TEXT NOT NULL CHECK (
        length(outbox_sha256) = 64 AND outbox_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dispatch_state TEXT NOT NULL CHECK (dispatch_state = 'queued'),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (lease_id, outbox_sequence),
    UNIQUE (lease_id, outbox_id),
    UNIQUE (lease_id, occurrence_key),
    FOREIGN KEY (lease_id, event_id)
        REFERENCES cognitive_local_events(lease_id, event_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER cognitive_local_outbox_no_update
BEFORE UPDATE ON cognitive_local_outbox BEGIN
    SELECT RAISE(ABORT, 'local outbox rows are immutable');
END;

CREATE TRIGGER cognitive_local_outbox_no_delete
BEFORE DELETE ON cognitive_local_outbox BEGIN
    SELECT RAISE(ABORT, 'local outbox rows are immutable');
END;

CREATE INDEX cognitive_local_outbox_owner_lookup
ON cognitive_local_outbox(owner_agent_id, lease_id, outbox_sequence);

CREATE INDEX cognitive_local_outbox_occurrence_lookup
ON cognitive_local_outbox(lease_id, occurrence_key, outbox_sequence);
