-- Extend the ORIGINAL immutable event chain with the typed Notes fence
-- exclusion terminal. This is source-side settlement evidence only: it does
-- not mint or imitate an application NotApplied receipt.
--
-- As in 0018, retain every original row and foreign-key edge while rebuilding
-- the STRICT table with the additive CHECK member.
PRAGMA defer_foreign_keys = ON;

CREATE TABLE cognitive_local_events_notes_fence_upgrade (
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
            'retirement_acknowledged', 'notes_fence_excluded'
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
INSERT INTO cognitive_local_events_notes_fence_upgrade SELECT * FROM cognitive_local_events;
DROP TABLE cognitive_local_events;
ALTER TABLE cognitive_local_events_notes_fence_upgrade RENAME TO cognitive_local_events;

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

CREATE TEMP TABLE notes_fence_migration_fk_guard (
    violations INTEGER NOT NULL CHECK (violations = 0)
) STRICT;
INSERT INTO notes_fence_migration_fk_guard
SELECT COUNT(*) FROM pragma_foreign_key_check;
DROP TABLE notes_fence_migration_fk_guard;
PRAGMA defer_foreign_keys = OFF;
