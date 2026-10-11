-- Freeze the schedule revision at the same durable transaction that creates a
-- scheduler run.  Prior schemas froze revision only once
-- automation_occurrence_lifecycle existed, leaving a claim -> materialize
-- window where a policy update could relabel an old due instant.
ALTER TABLE automation_runs
ADD COLUMN schedule_revision INTEGER
CHECK (schedule_revision IS NULL OR schedule_revision > 0);

-- Materialized occurrences already carry the authoritative revision.
UPDATE automation_runs
SET schedule_revision = (
    SELECT o.schedule_revision
    FROM automation_occurrence_lifecycle o
    WHERE o.task_id = automation_runs.task_id
      AND o.occurrence = automation_runs.occurrence
)
WHERE schedule_revision IS NULL
  AND EXISTS (
      SELECT 1
      FROM automation_occurrence_lifecycle o
      WHERE o.task_id = automation_runs.task_id
        AND o.occurrence = automation_runs.occurrence
  );

-- A pending/leased compatibility run with no occurrence and no dispatch
-- observation is provably pre-provider in the current scheduler topology.
-- Cancel it rather than guessing which historical revision produced its due
-- instant; the task remains due and will be claimed again under the current
-- revision with a fresh occurrence number.
UPDATE automation_runs
SET state = 'cancelled',
    lease_generation = NULL,
    lease_token = NULL,
    lease_expires_at_ms = NULL
WHERE schedule_revision IS NULL
  AND state IN ('pending', 'leased')
  AND NOT EXISTS (
      SELECT 1
      FROM automation_dispatch_outcomes o
      WHERE o.task_id = automation_runs.task_id
        AND o.occurrence = automation_runs.occurrence
  );

-- Every new run must carry the immutable revision selected by claim_due().
CREATE TRIGGER automation_runs_schedule_revision_required_insert
BEFORE INSERT ON automation_runs
WHEN NEW.schedule_revision IS NULL OR NEW.schedule_revision <= 0
BEGIN
    SELECT RAISE(ABORT, 'automation run schedule revision is required');
END;

CREATE TRIGGER automation_runs_schedule_revision_no_update
BEFORE UPDATE OF schedule_revision ON automation_runs
WHEN NEW.schedule_revision IS NOT OLD.schedule_revision
BEGIN
    SELECT RAISE(ABORT, 'automation run schedule revision is immutable');
END;

-- Freeze policy changes from the first durable pending/leased run, not only
-- after occurrence materialization. This closes the async claim/materialize
-- race and also fences old dispatch-uncertain leases during upgrade.
DROP TRIGGER automation_schedule_policy_no_inflight_update;
CREATE TRIGGER automation_schedule_policy_no_inflight_update
BEFORE UPDATE OF revision, missed_run_policy, max_catch_up_occurrences, overlap_policy
ON automation_schedule_metadata
WHEN EXISTS (
    SELECT 1 FROM automation_occurrence_lifecycle o
     WHERE o.task_id = NEW.task_id
       AND o.state IN ('claimed', 'admitted', 'running', 'indeterminate')
)
OR EXISTS (
    SELECT 1 FROM automation_runs r
     WHERE r.task_id = NEW.task_id
       AND r.state IN ('pending', 'leased')
)
BEGIN
    SELECT RAISE(ABORT, 'automation schedule revision is frozen while work is active');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 14 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
