-- Durable lifecycle of the timer schedule/occurrence owner, not TaskFlow effects.
-- Schema v5 composes after v4 kernel.operations destination dedupe.
CREATE TABLE automation_timer_lifecycle (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    writer_epoch INTEGER NOT NULL CHECK (writer_epoch > 0),
    phase TEXT NOT NULL CHECK (phase IN ('active', 'draining', 'retired'))
);
INSERT INTO automation_timer_lifecycle VALUES (1, 1, 'active');

CREATE TRIGGER automation_timer_lifecycle_no_delete
BEFORE DELETE ON automation_timer_lifecycle
BEGIN
    SELECT RAISE(ABORT, 'timer lifecycle cannot be reset');
END;

CREATE TRIGGER automation_timer_lifecycle_transition
BEFORE UPDATE ON automation_timer_lifecycle
WHEN NEW.singleton != OLD.singleton OR NOT (
    (NEW.writer_epoch = OLD.writer_epoch AND NEW.phase = OLD.phase)
    OR (NEW.writer_epoch = OLD.writer_epoch AND OLD.phase = 'active' AND NEW.phase = 'draining')
    OR (NEW.writer_epoch = OLD.writer_epoch AND OLD.phase = 'draining' AND NEW.phase = 'active')
    OR (OLD.phase = 'draining' AND NEW.phase IN ('draining', 'retired')
        AND OLD.writer_epoch < 9223372036854775807 AND NEW.writer_epoch = OLD.writer_epoch + 1)
)
BEGIN
    SELECT RAISE(ABORT, 'invalid timer lifecycle transition');
END;

CREATE TRIGGER automation_timer_lifecycle_drain
BEFORE UPDATE OF writer_epoch ON automation_timer_lifecycle
WHEN NEW.writer_epoch != OLD.writer_epoch AND (
    EXISTS (SELECT 1 FROM automation_runs WHERE state = 'leased')
    OR EXISTS (SELECT 1 FROM automation_dispatch_outcomes WHERE outcome = 'uncertain')
)
BEGIN
    SELECT RAISE(ABORT, 'timer owner still has unresolved dispatches');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 5 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
