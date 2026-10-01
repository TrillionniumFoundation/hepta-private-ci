-- Durable Neural Circuit activation/choice evidence layered onto the existing
-- TaskFlow owner. This does not create a second executor or resource authority.
-- Fleet lease identity is referenced, never minted or mutated here.

CREATE TABLE taskflow_circuit_activations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL CHECK (length(activation_id) BETWEEN 1 AND 256),
    round INTEGER NOT NULL CHECK (round > 0 AND round <= 1000000),
    node_id TEXT NOT NULL CHECK (length(node_id) BETWEEN 1 AND 256),
    circuit_digest TEXT NOT NULL CHECK (
        length(circuit_digest) = 64 AND circuit_digest NOT GLOB '*[^0-9a-f]*'
    ),
    taskflow_definition_digest TEXT NOT NULL CHECK (
        length(taskflow_definition_digest) = 64 AND taskflow_definition_digest NOT GLOB '*[^0-9a-f]*'
    ),
    causal_event_digest TEXT NOT NULL CHECK (
        length(causal_event_digest) = 64 AND causal_event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    route_policy_digest TEXT NOT NULL CHECK (
        length(route_policy_digest) = 64 AND route_policy_digest NOT GLOB '*[^0-9a-f]*'
    ),
    parameter_bundle_digest TEXT NOT NULL CHECK (
        length(parameter_bundle_digest) = 64 AND parameter_bundle_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resource_profile_digest TEXT NOT NULL CHECK (
        length(resource_profile_digest) = 64 AND resource_profile_digest NOT GLOB '*[^0-9a-f]*'
    ),
    fleet_lease_id TEXT NOT NULL CHECK (length(fleet_lease_id) BETWEEN 1 AND 256),
    fleet_lease_revision INTEGER NOT NULL CHECK (fleet_lease_revision > 0),
    fleet_authority_epoch INTEGER NOT NULL CHECK (fleet_authority_epoch > 0),
    compute_units INTEGER NOT NULL CHECK (compute_units >= 0),
    inference_units INTEGER NOT NULL CHECK (inference_units >= 0),
    provider_effect_units INTEGER NOT NULL CHECK (provider_effect_units >= 0),
    queue_units INTEGER NOT NULL CHECK (queue_units >= 0),
    child_units INTEGER NOT NULL CHECK (child_units >= 0),
    uncertainty_units INTEGER NOT NULL CHECK (uncertainty_units >= 0),
    command_id TEXT NOT NULL CHECK (length(command_id) BETWEEN 1 AND 256),
    command_digest TEXT NOT NULL CHECK (
        length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
    ),
    activation_digest TEXT NOT NULL CHECK (
        length(activation_digest) = 64 AND activation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    UNIQUE (owner_agent_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE TABLE taskflow_circuit_choices (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    selected_port TEXT NOT NULL CHECK (length(selected_port) BETWEEN 1 AND 256),
    candidate_set_digest TEXT NOT NULL CHECK (
        length(candidate_set_digest) = 64 AND candidate_set_digest NOT GLOB '*[^0-9a-f]*'
    ),
    behavior_policy_digest TEXT NOT NULL CHECK (
        length(behavior_policy_digest) = 64 AND behavior_policy_digest NOT GLOB '*[^0-9a-f]*'
    ),
    decision_receipt_digest TEXT NOT NULL CHECK (
        length(decision_receipt_digest) = 64 AND decision_receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    command_id TEXT NOT NULL CHECK (length(command_id) BETWEEN 1 AND 256),
    command_digest TEXT NOT NULL CHECK (
        length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
    ),
    choice_digest TEXT NOT NULL CHECK (
        length(choice_digest) = 64 AND choice_digest NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    UNIQUE (owner_agent_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id, activation_id)
        REFERENCES taskflow_circuit_activations(owner_agent_id, run_id, activation_id)
);

CREATE TRIGGER taskflow_circuit_activations_no_update
BEFORE UPDATE ON taskflow_circuit_activations
BEGIN
    SELECT RAISE(ABORT, 'circuit activations are append-only');
END;

CREATE TRIGGER taskflow_circuit_activations_no_delete
BEFORE DELETE ON taskflow_circuit_activations
BEGIN
    SELECT RAISE(ABORT, 'circuit activations are append-only');
END;

CREATE TRIGGER taskflow_circuit_choices_no_update
BEFORE UPDATE ON taskflow_circuit_choices
BEGIN
    SELECT RAISE(ABORT, 'circuit choices are append-only');
END;

CREATE TRIGGER taskflow_circuit_choices_no_delete
BEFORE DELETE ON taskflow_circuit_choices
BEGIN
    SELECT RAISE(ABORT, 'circuit choices are append-only');
END;

CREATE INDEX taskflow_circuit_activation_run_round
    ON taskflow_circuit_activations(owner_agent_id, run_id, round, activation_id);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
