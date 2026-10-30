-- Pre-v22 rows keep profile 0. An unbound legacy attempt may have lost an
-- Accepted operation, so later evidence must not invent its original identity.
-- Explicit profile 1 is also a compatibility gate for every append: a process
-- with an already-open pre-v22 connection cannot bypass the new owner checks.
ALTER TABLE taskflow_effect_dispatch_attempts
    ADD COLUMN append_profile_version INTEGER NOT NULL DEFAULT 0
    CHECK (append_profile_version IN (0, 1));
ALTER TABLE taskflow_effect_provider_bindings
    ADD COLUMN append_profile_version INTEGER NOT NULL DEFAULT 0
    CHECK (append_profile_version IN (0, 1));
ALTER TABLE taskflow_effect_dispatch_observations
    ADD COLUMN append_profile_version INTEGER NOT NULL DEFAULT 0
    CHECK (append_profile_version IN (0, 1));
ALTER TABLE taskflow_effect_dispatch_reconciliations
    ADD COLUMN append_profile_version INTEGER NOT NULL DEFAULT 0
    CHECK (append_profile_version IN (0, 1));

CREATE TRIGGER taskflow_effect_dispatch_attempts_require_append_profile
BEFORE INSERT ON taskflow_effect_dispatch_attempts
WHEN NEW.append_profile_version != 1
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect append requires the current writer profile');
END;

CREATE TRIGGER taskflow_effect_provider_bindings_require_append_profile
BEFORE INSERT ON taskflow_effect_provider_bindings
WHEN NEW.append_profile_version != 1 OR NOT EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts a
    WHERE a.owner_agent_id=NEW.owner_agent_id AND a.run_id=NEW.run_id
      AND a.step_id=NEW.step_id AND a.attempt=NEW.attempt
      AND a.append_profile_version=1
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow legacy effect cannot acquire a replacement binding');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_require_append_profile
BEFORE INSERT ON taskflow_effect_dispatch_observations
WHEN NEW.append_profile_version != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts a
    WHERE a.owner_agent_id=NEW.owner_agent_id AND a.run_id=NEW.run_id
      AND a.step_id=NEW.step_id AND a.attempt=NEW.attempt
      AND a.append_profile_version=0
      AND (NEW.observation != 'indeterminate' OR NEW.provider_receipt_json IS NOT NULL)
      AND NOT EXISTS (
          SELECT 1 FROM taskflow_effect_provider_bindings b
          WHERE b.owner_agent_id=a.owner_agent_id AND b.run_id=a.run_id
            AND b.step_id=a.step_id AND b.attempt<=a.attempt
      )
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow legacy effect remains recovery-only');
END;

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_require_append_profile
BEFORE INSERT ON taskflow_effect_dispatch_reconciliations
WHEN NEW.append_profile_version != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts a
    WHERE a.owner_agent_id=NEW.owner_agent_id AND a.run_id=NEW.run_id
      AND a.step_id=NEW.step_id AND a.attempt=NEW.attempt
      AND a.append_profile_version=0
      AND NOT EXISTS (
          SELECT 1 FROM taskflow_effect_provider_bindings b
          WHERE b.owner_agent_id=a.owner_agent_id AND b.run_id=a.run_id
            AND b.step_id=a.step_id AND b.attempt<=a.attempt
      )
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow legacy effect remains recovery-only');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
