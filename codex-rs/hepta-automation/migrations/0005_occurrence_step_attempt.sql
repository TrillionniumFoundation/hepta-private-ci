-- Bind each provider-dispatch attempt to a distinct durable TaskFlow step chain.
-- A new attempt is allocated only when a safely retryable occurrence is
-- reclaimed by a newer scheduler generation. Unknown provider outcomes remain
-- quarantined and therefore never allocate a blind retry attempt.
ALTER TABLE automation_occurrence_lifecycle
ADD COLUMN step_attempt INTEGER NOT NULL DEFAULT 1
    CHECK (step_attempt > 0 AND step_attempt <= 1000000);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 5 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
