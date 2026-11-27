-- Extend the ORIGINAL immutable event chain with one metadata ACK kind.
-- This normal migration is never applied to an already authenticated Current
-- during recovery. Old protected images remain bound to their compiled lineage.
-- SQLite keeps deferred counters for DROP/recreate of a referenced parent even
-- when the same rows and parent name are restored. Audit every real FK first;
-- only then clear those bookkeeping counters. foreign_keys remains enabled.
PRAGMA defer_foreign_keys = ON;

CREATE TABLE cognitive_local_events_retirement_upgrade (
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
            'reconcile_rejected', 'reconcile_still_indeterminate', 'rolled_back',
            'retirement_acknowledged'
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
INSERT INTO cognitive_local_events_retirement_upgrade SELECT * FROM cognitive_local_events;
DROP TABLE cognitive_local_events;
ALTER TABLE cognitive_local_events_retirement_upgrade RENAME TO cognitive_local_events;


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


CREATE TEMP TABLE retirement_ack_migration_fk_guard (
    violations INTEGER NOT NULL CHECK (violations = 0)
) STRICT;
INSERT INTO retirement_ack_migration_fk_guard
SELECT COUNT(*) FROM pragma_foreign_key_check;
DROP TABLE retirement_ack_migration_fk_guard;
PRAGMA defer_foreign_keys = OFF;
