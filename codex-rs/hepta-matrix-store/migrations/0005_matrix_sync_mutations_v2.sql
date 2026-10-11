-- V2 is an owner-local source candidate with a fixed lifetime journal budget.
-- AUTOINCREMENT plus immutable rows makes every explicit ceiling non-reusable;
-- exhaustion rejects the enclosing transaction before its cursor can advance.
CREATE TABLE matrix_sync_mutations_v2 (
    ledger_seq INTEGER PRIMARY KEY AUTOINCREMENT CHECK (ledger_seq BETWEEN 1 AND 65536),
    source_event_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    sender_user_id TEXT NOT NULL,
    mutation_kind TEXT NOT NULL CHECK (
        mutation_kind IN ('timeline', 'redaction', 'room_leave', 'room_tombstone')
    ),
    mutation_sha256 TEXT NOT NULL CHECK (
        length(mutation_sha256) = 64 AND mutation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    tombstone_scope_kind TEXT CHECK (tombstone_scope_kind IN ('event', 'room')),
    tombstone_scope_id TEXT,
    tombstone_reason_kind TEXT CHECK (
        tombstone_reason_kind IN ('redaction', 'room_leave', 'room_replacement')
    ),
    replacement_room_id TEXT,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    origin_server_ts_ms INTEGER NOT NULL CHECK (origin_server_ts_ms >= 0),
    received_at_ms INTEGER NOT NULL CHECK (received_at_ms >= 0),
    FOREIGN KEY (room_id) REFERENCES room_bindings(room_id) ON DELETE RESTRICT,
    CHECK (
        (mutation_kind = 'timeline' AND tombstone_scope_kind IS NULL
            AND tombstone_scope_id IS NULL AND tombstone_reason_kind IS NULL
            AND replacement_room_id IS NULL) OR
        (mutation_kind = 'redaction' AND tombstone_scope_kind = 'event'
            AND tombstone_scope_id IS NOT NULL AND tombstone_reason_kind = 'redaction'
            AND replacement_room_id IS NULL AND tombstone_scope_id != source_event_id) OR
        (mutation_kind = 'room_leave' AND tombstone_scope_kind = 'room'
            AND tombstone_scope_id = room_id AND tombstone_reason_kind = 'room_leave'
            AND replacement_room_id IS NULL) OR
        (mutation_kind = 'room_tombstone' AND tombstone_scope_kind = 'room'
            AND tombstone_scope_id = room_id AND tombstone_reason_kind = 'room_replacement'
            AND replacement_room_id IS NOT NULL AND replacement_room_id != room_id)
    )
) STRICT;

CREATE TABLE matrix_sync_decisions_v2 (
    decision_seq INTEGER PRIMARY KEY AUTOINCREMENT CHECK (decision_seq BETWEEN 1 AND 65536),
    operation_id TEXT NOT NULL UNIQUE CHECK (
        length(operation_id) BETWEEN 1 AND 128
        AND operation_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    decision_kind TEXT NOT NULL CHECK (decision_kind IN ('commit', 'cancel')),
    decision_sha256 TEXT NOT NULL CHECK (
        length(decision_sha256) = 64 AND decision_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version INTEGER NOT NULL CHECK (schema_version = 2),
    checkpoint_revision INTEGER NOT NULL CHECK (checkpoint_revision > 0),
    checkpoint_generation INTEGER NOT NULL CHECK (checkpoint_generation > 0),
    expected_next_batch TEXT,
    next_batch TEXT,
    retained_next_batch TEXT,
    outcome_count INTEGER NOT NULL CHECK (outcome_count BETWEEN 0 AND 512),
    CHECK (
        (decision_kind = 'commit' AND next_batch IS NOT NULL
            AND retained_next_batch IS NULL) OR
        (decision_kind = 'cancel' AND next_batch IS NULL AND outcome_count = 0)
    )
) STRICT;

CREATE TABLE matrix_sync_decision_outcomes_v2 (
    outcome_seq INTEGER PRIMARY KEY AUTOINCREMENT CHECK (
        outcome_seq BETWEEN 1 AND 33554432
    ),
    decision_seq INTEGER NOT NULL,
    outcome_index INTEGER NOT NULL CHECK (outcome_index BETWEEN 0 AND 511),
    source_event_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (
        disposition IN ('applied', 'duplicate', 'missing', 'tombstoned')
    ),
    UNIQUE (decision_seq, outcome_index),
    UNIQUE (decision_seq, source_event_id),
    FOREIGN KEY (decision_seq) REFERENCES matrix_sync_decisions_v2(decision_seq)
        ON DELETE RESTRICT,
    FOREIGN KEY (source_event_id) REFERENCES matrix_sync_mutations_v2(source_event_id)
        ON DELETE RESTRICT
) STRICT;

CREATE INDEX matrix_sync_mutations_v2_by_tombstone
ON matrix_sync_mutations_v2(
    tombstone_scope_kind, tombstone_scope_id, received_at_ms, source_event_id
);

-- Room-wide revocation runs inside the cursor writer transaction. Index only
-- rows which can still require work; event redaction already uses the unique
-- event_id index from migration 0001.
CREATE INDEX inbox_events_by_room_actionable
ON inbox_events(room_id, inbox_cursor)
WHERE length(payload) > 0 OR state != 'processed';

CREATE INDEX inbox_dispatches_by_room_active
ON inbox_dispatches(room_id, state, event_id)
WHERE state IN ('begun', 'queued', 'admitted');

CREATE INDEX outbox_messages_by_room_active
ON outbox_messages(room_id, state, outbox_id)
WHERE state IN ('pending', 'in_flight', 'retry_scheduled');

-- Logical tombstones are the immediate read/send fence. Physical payload
-- scrubbing is bounded cleanup and is not required for semantic deletion.
CREATE VIEW matrix_visible_inbox_events_v2 AS
SELECT inbox_events.* FROM inbox_events
WHERE NOT EXISTS (
    SELECT 1 FROM matrix_sync_mutations_v2 AS tombstone
    WHERE (tombstone.tombstone_scope_kind = 'event'
           AND tombstone.tombstone_scope_id = inbox_events.event_id
           AND tombstone.room_id = inbox_events.room_id)
       OR (tombstone.tombstone_scope_kind = 'room'
           AND tombstone.tombstone_scope_id = inbox_events.room_id
           AND (tombstone.tombstone_reason_kind = 'room_replacement'
                OR (tombstone.tombstone_reason_kind = 'room_leave'
                    AND tombstone.binding_revision = inbox_events.binding_revision
                    AND tombstone.generation = inbox_events.generation)))
);

CREATE VIEW matrix_actionable_inbox_dispatches_v2 AS
SELECT dispatch.* FROM inbox_dispatches AS dispatch
WHERE NOT EXISTS (
    SELECT 1 FROM matrix_sync_mutations_v2 AS tombstone
    WHERE (tombstone.tombstone_scope_kind = 'event'
           AND tombstone.tombstone_scope_id = dispatch.event_id
           AND tombstone.room_id = dispatch.room_id)
       OR (tombstone.tombstone_scope_kind = 'room'
           AND tombstone.tombstone_scope_id = dispatch.room_id
           AND (tombstone.tombstone_reason_kind = 'room_replacement'
                OR (tombstone.tombstone_reason_kind = 'room_leave'
                    AND tombstone.binding_revision = dispatch.binding_revision
                    AND tombstone.generation = dispatch.generation)))
);

CREATE VIEW matrix_sendable_outbox_v2 AS
SELECT outbox_messages.* FROM outbox_messages
WHERE NOT EXISTS (
    SELECT 1 FROM matrix_sync_mutations_v2 AS tombstone
    WHERE tombstone.tombstone_scope_kind = 'room'
      AND tombstone.tombstone_scope_id = outbox_messages.room_id
      AND (tombstone.tombstone_reason_kind = 'room_replacement'
           OR (tombstone.tombstone_reason_kind = 'room_leave'
               AND tombstone.binding_revision = outbox_messages.binding_revision
               AND tombstone.generation = outbox_messages.generation))
);

CREATE TRIGGER matrix_sync_decisions_v2_no_update
BEFORE UPDATE ON matrix_sync_decisions_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 decision is immutable');
END;

CREATE TRIGGER matrix_sync_decisions_v2_no_delete
BEFORE DELETE ON matrix_sync_decisions_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 decision is immutable');
END;

CREATE TRIGGER matrix_sync_decision_outcomes_v2_no_update
BEFORE UPDATE ON matrix_sync_decision_outcomes_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 decision outcome is immutable');
END;

CREATE TRIGGER matrix_sync_decision_outcomes_v2_no_delete
BEFORE DELETE ON matrix_sync_decision_outcomes_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 decision outcome is immutable');
END;

CREATE TRIGGER matrix_sync_decision_outcomes_v2_guard_insert
BEFORE INSERT ON matrix_sync_decision_outcomes_v2 BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM matrix_sync_decisions_v2
        WHERE decision_seq = NEW.decision_seq
          AND decision_kind = 'commit'
          AND NEW.outcome_index < outcome_count
    ) THEN RAISE(ABORT, 'Matrix sync V2 outcome is outside its commit decision') END;
END;

CREATE TRIGGER matrix_sync_mutations_v2_no_update
BEFORE UPDATE ON matrix_sync_mutations_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 mutation is immutable');
END;

CREATE TRIGGER matrix_sync_mutations_v2_no_delete
BEFORE DELETE ON matrix_sync_mutations_v2 BEGIN
    SELECT RAISE(ABORT, 'Matrix sync V2 mutation is immutable');
END;
