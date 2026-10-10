-- H7 local-development-only compact checkpoint journal.
--
-- This table is an Agent-local append-only journal.  It is deliberately
-- separate from KG/projection tables: a compact checkpoint is not a memory
-- fact and this journal never grants KG or external-effect authority.
CREATE TABLE cognitive_compact_events (
    journal_id TEXT NOT NULL CHECK (
        length(trim(journal_id)) BETWEEN 1 AND 512 AND
        instr(journal_id, char(0)) = 0
    ),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    event_json TEXT NOT NULL CHECK (
        length(event_json) BETWEEN 1 AND 65536 AND
        instr(event_json, char(0)) = 0
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_sha256 TEXT NOT NULL CHECK (
        length(event_sha256) = 64 AND event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (journal_id, sequence),
    UNIQUE (journal_id, event_sha256)
) STRICT;

CREATE TRIGGER cognitive_compact_events_no_update
BEFORE UPDATE ON cognitive_compact_events BEGIN
    SELECT RAISE(ABORT, 'cognitive compact events are immutable');
END;

CREATE TRIGGER cognitive_compact_events_no_delete
BEFORE DELETE ON cognitive_compact_events BEGIN
    SELECT RAISE(ABORT, 'cognitive compact events are immutable');
END;

CREATE INDEX cognitive_compact_events_owner_lookup
ON cognitive_compact_events(owner_agent_id, journal_id, sequence);
