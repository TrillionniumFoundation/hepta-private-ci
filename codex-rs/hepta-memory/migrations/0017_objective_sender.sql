-- Objective submission retention belongs to the same CognitiveStore owner.
-- These rows are never FinalUse operations, effect outbox rows or run receipts.
CREATE TABLE cognitive_objective_sender_requests (
    request_sha256 TEXT PRIMARY KEY CHECK (
        length(request_sha256) = 64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    run_id TEXT NOT NULL CHECK (length(CAST(run_id AS BLOB)) BETWEEN 1 AND 256),
    issuer_id TEXT NOT NULL CHECK (length(CAST(issuer_id AS BLOB)) BETWEEN 1 AND 256),
    key_epoch INTEGER NOT NULL CHECK (key_epoch > 0),
    message_id TEXT NOT NULL CHECK (length(CAST(message_id AS BLOB)) BETWEEN 1 AND 256),
    message_sequence INTEGER NOT NULL CHECK (message_sequence > 0),
    original_json TEXT NOT NULL CHECK (
        length(CAST(original_json AS BLOB)) BETWEEN 1 AND 65536 AND json_valid(original_json)
    ),
    binding_json TEXT NOT NULL CHECK (
        length(CAST(binding_json AS BLOB)) BETWEEN 1 AND 4096 AND json_valid(binding_json)
    ),
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64 AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    lease_id TEXT NOT NULL,
    lease_sha256 TEXT NOT NULL,
    permit_sequence INTEGER NOT NULL CHECK (permit_sequence = 1),
    UNIQUE (owner_agent_id, run_id),
    UNIQUE (owner_agent_id, issuer_id, key_epoch, message_id),
    UNIQUE (owner_agent_id, issuer_id, key_epoch, message_sequence),
    FOREIGN KEY (lease_id, lease_sha256)
        REFERENCES cognitive_local_leases(lease_id, lease_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (request_sha256, permit_sequence)
        REFERENCES cognitive_objective_sender_events(request_sha256, event_sequence)
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE cognitive_objective_sender_events (
    request_sha256 TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence BETWEEN 1 AND 64),
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'permit_issued', 'submission_observed', 'history_observed', 'local_cancelled'
    )),
    observation_json TEXT NOT NULL CHECK (
        length(CAST(observation_json AS BLOB)) BETWEEN 1 AND 16384 AND json_valid(observation_json)
    ),
    observation_sha256 TEXT NOT NULL CHECK (
        length(observation_sha256) = 64 AND observation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_json TEXT NOT NULL CHECK (
        length(CAST(binding_json AS BLOB)) BETWEEN 1 AND 4096 AND json_valid(binding_json)
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_sha256 TEXT NOT NULL CHECK (
        length(event_sha256) = 64 AND event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    lease_id TEXT NOT NULL,
    lease_sha256 TEXT NOT NULL,
    PRIMARY KEY (request_sha256, event_sequence),
    UNIQUE (request_sha256, event_kind, observation_sha256),
    FOREIGN KEY (request_sha256)
        REFERENCES cognitive_objective_sender_requests(request_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (lease_id, lease_sha256)
        REFERENCES cognitive_local_leases(lease_id, lease_sha256) ON DELETE RESTRICT,
    CHECK ((event_sequence = 1 AND event_kind = 'permit_issued' AND observation_json = 'null')
        OR (event_sequence > 1 AND event_kind <> 'permit_issued'))
) STRICT;

CREATE TRIGGER cognitive_objective_sender_requests_no_update
BEFORE UPDATE ON cognitive_objective_sender_requests BEGIN
    SELECT RAISE(ABORT, 'Objective sender requests are immutable');
END;
CREATE TRIGGER cognitive_objective_sender_requests_no_delete
BEFORE DELETE ON cognitive_objective_sender_requests BEGIN
    SELECT RAISE(ABORT, 'Objective sender requests are immutable');
END;
CREATE TRIGGER cognitive_objective_sender_events_no_update
BEFORE UPDATE ON cognitive_objective_sender_events BEGIN
    SELECT RAISE(ABORT, 'Objective sender observations are immutable');
END;
CREATE TRIGGER cognitive_objective_sender_events_no_delete
BEFORE DELETE ON cognitive_objective_sender_events BEGIN
    SELECT RAISE(ABORT, 'Objective sender observations are immutable');
END;
CREATE TRIGGER cognitive_objective_sender_events_append
BEFORE INSERT ON cognitive_objective_sender_events BEGIN
    SELECT CASE WHEN NEW.event_sequence <> 1 + COALESCE((
        SELECT MAX(event_sequence) FROM cognitive_objective_sender_events
        WHERE request_sha256 = NEW.request_sha256
    ), 0) THEN RAISE(ABORT, 'Objective sender event sequence is not contiguous') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM cognitive_objective_sender_events
        WHERE request_sha256 = NEW.request_sha256 AND event_kind = 'local_cancelled'
    ) THEN RAISE(ABORT, 'Objective local permission was cancelled') END;
    SELECT CASE WHEN NEW.event_kind = 'local_cancelled' AND NEW.event_sequence <> 2
        THEN RAISE(ABORT, 'Objective local cancellation follows an observation') END;
    SELECT CASE WHEN NEW.event_kind = 'submission_observed' AND EXISTS (
        SELECT 1 FROM cognitive_objective_sender_events
        WHERE request_sha256 = NEW.request_sha256 AND event_kind = 'submission_observed'
    ) THEN RAISE(ABORT, 'Objective submission observation is already retained') END;
END;
