-- Minimal real DecisionCell runtime on the existing TaskFlow owner.
-- Candidate, parameter, and choice records are create-only. A choice is
-- committed before the TaskFlow projection takes the selected edge.
CREATE TABLE automation_circuit_candidates (
    owner_agent_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL CHECK (length(circuit_id) BETWEEN 1 AND 256),
    version INTEGER NOT NULL CHECK (version > 0 AND version <= 4294967295),
    candidate_json TEXT NOT NULL CHECK (length(candidate_json) BETWEEN 2 AND 1048576),
    circuit_digest TEXT NOT NULL CHECK (length(circuit_digest) = 64 AND circuit_digest NOT GLOB '*[^0-9a-f]*'),
    predecessor_digest TEXT,
    definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64 AND definition_digest NOT GLOB '*[^0-9a-f]*'),
    registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, circuit_id, version),
    UNIQUE(owner_agent_id, circuit_digest)
);

CREATE TABLE automation_threshold_cell_parameters (
    owner_agent_id TEXT NOT NULL,
    cell_id TEXT NOT NULL CHECK (length(cell_id) BETWEEN 1 AND 256),
    version INTEGER NOT NULL CHECK (version > 0 AND version <= 4294967295),
    parameter_json TEXT NOT NULL CHECK (length(parameter_json) BETWEEN 2 AND 65536),
    parameter_digest TEXT NOT NULL CHECK (length(parameter_digest) = 64 AND parameter_digest NOT GLOB '*[^0-9a-f]*'),
    predecessor_digest TEXT,
    threshold_ppm INTEGER NOT NULL CHECK (threshold_ppm BETWEEN -1000000 AND 1000000),
    high_node TEXT NOT NULL CHECK (length(high_node) BETWEEN 1 AND 256),
    low_node TEXT NOT NULL CHECK (length(low_node) BETWEEN 1 AND 256),
    registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, cell_id, version),
    UNIQUE(owner_agent_id, parameter_digest)
);

CREATE TABLE automation_circuit_decisions (
    owner_agent_id TEXT NOT NULL,
    operation_id TEXT NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 256),
    run_id TEXT NOT NULL CHECK (length(run_id) BETWEEN 1 AND 256),
    circuit_digest TEXT NOT NULL,
    parameter_digest TEXT NOT NULL,
    input_value_ppm INTEGER NOT NULL CHECK (input_value_ppm BETWEEN -1000000 AND 1000000),
    selected_node TEXT NOT NULL CHECK (length(selected_node) BETWEEN 1 AND 256),
    disposition TEXT NOT NULL CHECK (disposition IN ('succeeded', 'failed')),
    choice_digest TEXT NOT NULL CHECK (length(choice_digest) = 64 AND choice_digest NOT GLOB '*[^0-9a-f]*'),
    chosen_at_ms INTEGER NOT NULL CHECK (chosen_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, operation_id),
    UNIQUE(owner_agent_id, run_id),
    FOREIGN KEY(owner_agent_id, run_id) REFERENCES taskflow_runs(owner_agent_id, run_id),
    FOREIGN KEY(owner_agent_id, circuit_digest) REFERENCES automation_circuit_candidates(owner_agent_id, circuit_digest),
    FOREIGN KEY(owner_agent_id, parameter_digest) REFERENCES automation_threshold_cell_parameters(owner_agent_id, parameter_digest)
);

CREATE TRIGGER automation_circuit_candidates_no_update
BEFORE UPDATE ON automation_circuit_candidates BEGIN
    SELECT RAISE(ABORT, 'circuit candidates are immutable');
END;
CREATE TRIGGER automation_circuit_candidates_no_delete
BEFORE DELETE ON automation_circuit_candidates BEGIN
    SELECT RAISE(ABORT, 'circuit candidates are immutable');
END;
CREATE TRIGGER automation_threshold_cell_parameters_no_update
BEFORE UPDATE ON automation_threshold_cell_parameters BEGIN
    SELECT RAISE(ABORT, 'threshold cell parameters are immutable');
END;
CREATE TRIGGER automation_threshold_cell_parameters_no_delete
BEFORE DELETE ON automation_threshold_cell_parameters BEGIN
    SELECT RAISE(ABORT, 'threshold cell parameters are immutable');
END;
CREATE TRIGGER automation_circuit_decisions_no_update
BEFORE UPDATE ON automation_circuit_decisions BEGIN
    SELECT RAISE(ABORT, 'circuit decisions are immutable');
END;
CREATE TRIGGER automation_circuit_decisions_no_delete
BEFORE DELETE ON automation_circuit_decisions BEGIN
    SELECT RAISE(ABORT, 'circuit decisions are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
