-- Operational scheduling only: these rows never authorize an Agent submission.
-- Identity and quarantine survive restart; payloads and error prose do not enter
-- this table. The visible-inbox view remains the admission/revocation boundary.
CREATE TABLE matrix_inbox_recovery (
    event_id TEXT NOT NULL PRIMARY KEY REFERENCES inbox_events(event_id),
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    last_started_at_ms INTEGER NOT NULL CHECK (last_started_at_ms >= 0),
    next_attempt_at_ms INTEGER NOT NULL CHECK (next_attempt_at_ms >= last_started_at_ms),
    outcome TEXT NOT NULL CHECK (outcome IN ('running', 'ready', 'retry', 'quarantined')),
    failure_class TEXT CHECK (failure_class IN (
        'dependency_unavailable', 'identity_conflict', 'binding_unrecoverable', 'invalid_input'
    )),
    CHECK ((outcome IN ('running', 'ready') AND failure_class IS NULL)
        OR (outcome IN ('retry', 'quarantined') AND failure_class IS NOT NULL))
) STRICT;

CREATE INDEX matrix_inbox_recovery_by_schedule
    ON matrix_inbox_recovery(outcome, next_attempt_at_ms, last_started_at_ms);

CREATE TRIGGER matrix_inbox_recovery_identity_guard
BEFORE UPDATE ON matrix_inbox_recovery
WHEN NEW.event_id != OLD.event_id
  OR NEW.attempts < OLD.attempts
  OR NEW.last_started_at_ms < OLD.last_started_at_ms
  OR (OLD.outcome = 'quarantined' AND (
      NEW.outcome != OLD.outcome OR NEW.failure_class != OLD.failure_class
      OR NEW.attempts != OLD.attempts))
BEGIN
    SELECT RAISE(ABORT, 'Matrix recovery identity/history/quarantine cannot be reset');
END;

CREATE TRIGGER matrix_inbox_recovery_no_delete
BEFORE DELETE ON matrix_inbox_recovery
BEGIN
    SELECT RAISE(ABORT, 'Matrix recovery history cannot be deleted');
END;
