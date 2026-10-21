-- Redaction cannot assert that an already admitted Core effect was cancelled.
-- Preserve raw effect identity and quarantine this exact room scope.
CREATE TABLE matrix_redaction_quarantines (
    room_id TEXT NOT NULL,
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    source_redaction_event_id TEXT NOT NULL UNIQUE,
    target_event_id TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK (reason_code = 'dispatched_source_redaction'),
    quarantined_at_ms INTEGER NOT NULL CHECK (quarantined_at_ms >= 0),
    PRIMARY KEY (room_id, binding_revision, generation),
    FOREIGN KEY (source_redaction_event_id)
        REFERENCES matrix_sync_mutations_v2(source_event_id) ON DELETE RESTRICT,
    FOREIGN KEY (target_event_id) REFERENCES inbox_dispatches(event_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER matrix_redaction_quarantines_guard_insert
BEFORE INSERT ON matrix_redaction_quarantines BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM matrix_sync_mutations_v2 AS source
        JOIN inbox_dispatches AS dispatch ON dispatch.event_id = NEW.target_event_id
        WHERE source.source_event_id = NEW.source_redaction_event_id
          AND source.mutation_kind = 'redaction'
          AND source.room_id = NEW.room_id
          AND source.binding_revision = NEW.binding_revision
          AND source.generation = NEW.generation
          AND source.tombstone_scope_id = NEW.target_event_id
          AND dispatch.room_id = NEW.room_id
          AND dispatch.binding_revision = NEW.binding_revision
          AND dispatch.generation = NEW.generation
          AND dispatch.state IN ('begun', 'queued', 'admitted', 'completed')
    ) THEN RAISE(ABORT, 'Matrix quarantine must retain an exact redacted dispatch') END;
END;

CREATE TRIGGER matrix_redaction_quarantines_no_update
BEFORE UPDATE ON matrix_redaction_quarantines BEGIN
    SELECT RAISE(ABORT, 'Matrix redaction quarantine is immutable');
END;

CREATE TRIGGER matrix_redaction_quarantines_no_delete
BEFORE DELETE ON matrix_redaction_quarantines BEGIN
    SELECT RAISE(ABORT, 'Matrix redaction quarantine cannot self-clear');
END;

DROP VIEW matrix_visible_inbox_events_v2;
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
) AND NOT EXISTS (
    SELECT 1 FROM matrix_redaction_quarantines AS quarantine
    WHERE quarantine.room_id = inbox_events.room_id
      AND quarantine.binding_revision = inbox_events.binding_revision
      AND quarantine.generation = inbox_events.generation
);

DROP VIEW matrix_actionable_inbox_dispatches_v2;
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
) AND NOT EXISTS (
    SELECT 1 FROM matrix_redaction_quarantines AS quarantine
    WHERE quarantine.room_id = dispatch.room_id
      AND quarantine.binding_revision = dispatch.binding_revision
      AND quarantine.generation = dispatch.generation
);

DROP VIEW matrix_sendable_outbox_v2;
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
) AND NOT EXISTS (
    SELECT 1 FROM matrix_redaction_quarantines AS quarantine
    WHERE quarantine.room_id = outbox_messages.room_id
      AND quarantine.binding_revision = outbox_messages.binding_revision
      AND quarantine.generation = outbox_messages.generation
);
