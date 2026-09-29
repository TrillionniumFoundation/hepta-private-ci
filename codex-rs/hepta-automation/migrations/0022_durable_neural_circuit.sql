-- Durable Neural Circuit execution is an extension of the existing TaskFlow run
-- owner. It records pre-call activation intent and budget reservation before any
-- DecisionCell/organ/wait call, then appends an immutable outcome receipt. An
-- executing activation without a receipt is recovery-required and never grants
-- permission to rerun an unknown owner operation.
CREATE TABLE neural_circuit_runs (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL,
    circuit_version INTEGER NOT NULL CHECK (circuit_version > 0),
    circuit_digest TEXT NOT NULL CHECK (
        length(circuit_digest) = 64 AND circuit_digest NOT GLOB '*[^0-9a-f]*'
    ),
    taskflow_definition_digest TEXT NOT NULL CHECK (
        length(taskflow_definition_digest) = 64 AND
        taskflow_definition_digest NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_json TEXT NOT NULL,
    event_digest TEXT NOT NULL CHECK (
        length(event_digest) = 64 AND event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    event_json TEXT NOT NULL,
    runtime_profile_digest TEXT NOT NULL CHECK (
        length(runtime_profile_digest) = 64 AND
        runtime_profile_digest NOT GLOB '*[^0-9a-f]*'
    ),
    runtime_profile_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('admitted', 'executing', 'waiting', 'effect_pending',
                  'terminal', 'recovery_required')
    ),
    activation_seq INTEGER NOT NULL DEFAULT 0 CHECK (activation_seq >= 0),
    cost_budget_units INTEGER NOT NULL CHECK (cost_budget_units > 0),
    consumed_cost_units INTEGER NOT NULL DEFAULT 0 CHECK (consumed_cost_units >= 0),
    reserved_cost_units INTEGER NOT NULL DEFAULT 0 CHECK (reserved_cost_units >= 0),
    checkpoint_json TEXT,
    checkpoint_digest TEXT,
    outcome_json TEXT,
    outcome_digest TEXT,
    projection_pending INTEGER NOT NULL DEFAULT 0 CHECK (projection_pending IN (0, 1)),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id),
    CHECK (consumed_cost_units + reserved_cost_units <= cost_budget_units),
    CHECK ((checkpoint_json IS NULL) = (checkpoint_digest IS NULL)),
    CHECK (checkpoint_digest IS NULL OR (
        length(checkpoint_digest) = 64 AND checkpoint_digest NOT GLOB '*[^0-9a-f]*'
    )),
    CHECK ((outcome_json IS NULL) = (outcome_digest IS NULL)),
    CHECK (outcome_digest IS NULL OR (
        length(outcome_digest) = 64 AND outcome_digest NOT GLOB '*[^0-9a-f]*'
    )),
    CHECK ((state = 'executing') = (reserved_cost_units > 0)),
    CHECK (state != 'admitted' OR activation_seq = 0),
    CHECK (state NOT IN ('waiting', 'effect_pending') OR checkpoint_json IS NOT NULL),
    CHECK (state NOT IN ('waiting', 'effect_pending', 'terminal') OR outcome_json IS NOT NULL),
    CHECK (state != 'recovery_required' OR reserved_cost_units = 0)
);

CREATE INDEX neural_circuit_runs_state_lookup
    ON neural_circuit_runs(owner_agent_id, state, updated_at_ms, run_id);

CREATE TRIGGER neural_circuit_runs_guard_update
BEFORE UPDATE ON neural_circuit_runs
WHEN NEW.owner_agent_id != OLD.owner_agent_id
    OR NEW.run_id != OLD.run_id
    OR NEW.circuit_id != OLD.circuit_id
    OR NEW.circuit_version != OLD.circuit_version
    OR NEW.circuit_digest != OLD.circuit_digest
    OR NEW.taskflow_definition_digest != OLD.taskflow_definition_digest
    OR NEW.candidate_json != OLD.candidate_json
    OR NEW.event_digest != OLD.event_digest
    OR NEW.event_json != OLD.event_json
    OR NEW.runtime_profile_digest != OLD.runtime_profile_digest
    OR NEW.runtime_profile_json != OLD.runtime_profile_json
    OR NEW.cost_budget_units != OLD.cost_budget_units
    OR NEW.created_at_ms != OLD.created_at_ms
    OR NEW.activation_seq < OLD.activation_seq
    OR NEW.activation_seq > OLD.activation_seq + 1
    OR NEW.consumed_cost_units < OLD.consumed_cost_units
    OR NEW.updated_at_ms < OLD.updated_at_ms
    OR (OLD.state = 'terminal' AND NEW.state != 'terminal')
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit identity, budget or monotone state changed');
END;

CREATE TRIGGER neural_circuit_runs_no_delete
BEFORE DELETE ON neural_circuit_runs
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit run evidence is retained');
END;

CREATE TABLE neural_circuit_activation_intents (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_seq INTEGER NOT NULL CHECK (activation_seq > 0),
    activation_kind TEXT NOT NULL CHECK (
        activation_kind IN ('start', 'resume_wait', 'resolve_effect')
    ),
    command_id TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK (
        length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_checkpoint_digest TEXT,
    reserved_cost_units INTEGER NOT NULL CHECK (reserved_cost_units > 0),
    recorded_choice_count_before INTEGER NOT NULL CHECK (recorded_choice_count_before >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_seq),
    UNIQUE (owner_agent_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES neural_circuit_runs(owner_agent_id, run_id),
    CHECK (predecessor_checkpoint_digest IS NULL OR (
        length(predecessor_checkpoint_digest) = 64 AND
        predecessor_checkpoint_digest NOT GLOB '*[^0-9a-f]*'
    ))
);

CREATE TRIGGER neural_circuit_activation_intents_no_update
BEFORE UPDATE ON neural_circuit_activation_intents
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit activation intents are immutable');
END;

CREATE TRIGGER neural_circuit_activation_intents_no_delete
BEFORE DELETE ON neural_circuit_activation_intents
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit activation intents are immutable');
END;

CREATE TABLE neural_circuit_activation_receipts (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_seq INTEGER NOT NULL CHECK (activation_seq > 0),
    outcome_kind TEXT NOT NULL CHECK (
        outcome_kind IN ('terminal', 'wait_pending', 'effect_pending')
    ),
    outcome_json TEXT NOT NULL,
    outcome_digest TEXT NOT NULL CHECK (
        length(outcome_digest) = 64 AND outcome_digest NOT GLOB '*[^0-9a-f]*'
    ),
    consumed_cost_delta INTEGER NOT NULL CHECK (consumed_cost_delta >= 0),
    recovery_evidence_digest TEXT,
    committed_at_ms INTEGER NOT NULL CHECK (committed_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_seq),
    FOREIGN KEY (owner_agent_id, run_id, activation_seq)
        REFERENCES neural_circuit_activation_intents(owner_agent_id, run_id, activation_seq),
    CHECK (recovery_evidence_digest IS NULL OR (
        length(recovery_evidence_digest) = 64 AND
        recovery_evidence_digest NOT GLOB '*[^0-9a-f]*'
    ))
);

CREATE TRIGGER neural_circuit_activation_receipts_no_update
BEFORE UPDATE ON neural_circuit_activation_receipts
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit activation receipts are immutable');
END;

CREATE TRIGGER neural_circuit_activation_receipts_no_delete
BEFORE DELETE ON neural_circuit_activation_receipts
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit activation receipts are immutable');
END;

CREATE TABLE neural_circuit_recorded_choices (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_seq INTEGER NOT NULL CHECK (activation_seq > 0),
    choice_index INTEGER NOT NULL CHECK (choice_index >= 0),
    choice_json TEXT NOT NULL,
    receipt_digest TEXT NOT NULL CHECK (
        length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    PRIMARY KEY (owner_agent_id, run_id, activation_seq, choice_index),
    UNIQUE (owner_agent_id, run_id, receipt_digest),
    FOREIGN KEY (owner_agent_id, run_id, activation_seq)
        REFERENCES neural_circuit_activation_receipts(owner_agent_id, run_id, activation_seq)
);

CREATE TRIGGER neural_circuit_recorded_choices_no_update
BEFORE UPDATE ON neural_circuit_recorded_choices
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit recorded choices are immutable');
END;

CREATE TRIGGER neural_circuit_recorded_choices_no_delete
BEFORE DELETE ON neural_circuit_recorded_choices
BEGIN
    SELECT RAISE(ABORT, 'Neural Circuit recorded choices are immutable');
END;


-- Circuit owner contact is an unresolved owner operation until an immutable
-- receipt is committed. Writer handoff must not cross an executing or
-- quarantined activation merely because the legacy dispatch tables are drained.
DROP TRIGGER automation_timer_lifecycle_drain;
CREATE TRIGGER automation_timer_lifecycle_drain
BEFORE UPDATE OF writer_epoch ON automation_timer_lifecycle
WHEN NEW.writer_epoch != OLD.writer_epoch AND (
    EXISTS (SELECT 1 FROM automation_runs WHERE state = 'leased')
    OR EXISTS (SELECT 1 FROM automation_dispatch_outcomes WHERE outcome = 'uncertain')
    OR EXISTS (
        SELECT 1 FROM neural_circuit_runs
        WHERE state IN ('executing', 'recovery_required')
    )
)
BEGIN
    SELECT RAISE(ABORT, 'timer owner still has unresolved dispatches');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
