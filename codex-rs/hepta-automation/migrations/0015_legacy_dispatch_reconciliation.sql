-- Preserve explicit evidence when a pre-v14 dispatch-unknown row has no
-- authoritative schedule revision or materialized occurrence.
--
-- Such rows cannot be upgraded into a qualified TaskFlow occurrence: the old
-- claim->materialize window did not freeze the schedule revision, so assigning
-- the current revision would rewrite history.  A provider-proven absence can,
-- however, safely retire the old unqualified run.  This append-only record
-- retains that negative evidence while a later scheduler claim allocates a new
-- occurrence number under the then-current frozen revision.
CREATE TABLE automation_legacy_dispatch_reconciliations (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK (occurrence > 0),
    client_user_message_id TEXT NOT NULL,
    proof_digest TEXT NOT NULL CHECK (
        length(proof_digest) = 64
        AND proof_digest NOT GLOB '*[^0-9a-f]*'
        AND proof_digest != '0000000000000000000000000000000000000000000000000000000000000000'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY (task_id, occurrence),
    UNIQUE (client_user_message_id),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence)
);

CREATE TRIGGER automation_legacy_dispatch_reconciliations_no_update
BEFORE UPDATE ON automation_legacy_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'legacy dispatch reconciliation evidence is append-only');
END;

CREATE TRIGGER automation_legacy_dispatch_reconciliations_no_delete
BEFORE DELETE ON automation_legacy_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'legacy dispatch reconciliation evidence is append-only');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 15 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
