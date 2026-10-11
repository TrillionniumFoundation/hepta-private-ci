-- H7a local-qualification-only trajectory event journal.
--
-- This Agent-local chain records replayable observation/feedback lineage for
-- the H7 shadow runtime.  It is deliberately not an effect receipt and does
-- not grant KG, production, model-promotion, or external-effect authority.
-- The typed writer verifies the lease/compact binding and event/hash-chain
-- digests inside one BEGIN IMMEDIATE transaction; SQLite supplies durable
-- shape, bounds, and append-only protection here.
CREATE TABLE cognitive_h7_trajectory_events (
    owner_agent_id TEXT NOT NULL CHECK (
        length(owner_agent_id) = 36 AND instr(owner_agent_id, char(0)) = 0
    ),
    trajectory_id TEXT NOT NULL CHECK (
        length(trim(trajectory_id)) BETWEEN 1 AND 512 AND
        instr(trajectory_id, char(0)) = 0
    ),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    event_id TEXT NOT NULL CHECK (
        length(trim(event_id)) BETWEEN 1 AND 512 AND
        instr(event_id, char(0)) = 0
    ),
    occurrence_key TEXT NOT NULL CHECK (
        length(trim(occurrence_key)) BETWEEN 1 AND 512 AND
        instr(occurrence_key, char(0)) = 0
    ),
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('turn_start', 'feedback', 'terminal')
    ),
    turn_id TEXT NOT NULL CHECK (
        length(trim(turn_id)) BETWEEN 1 AND 512 AND instr(turn_id, char(0)) = 0
    ),
    causal_parent_sha256 TEXT CHECK (
        causal_parent_sha256 IS NULL OR (
            length(causal_parent_sha256) = 64 AND
            causal_parent_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    causal_parent_seq INTEGER CHECK (
        causal_parent_seq IS NULL OR causal_parent_seq > 0
    ),
    receipt_sha256 TEXT NOT NULL CHECK (
        length(receipt_sha256) = 64 AND
        receipt_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    outcome TEXT NOT NULL CHECK (
        length(trim(outcome)) BETWEEN 1 AND 2048 AND
        instr(outcome, char(0)) = 0
    ),
    reward_bps INTEGER NOT NULL CHECK (
        reward_bps BETWEEN -2147483648 AND 2147483647
    ),
    safety_ok INTEGER NOT NULL DEFAULT 0 CHECK (safety_ok IN (0, 1)),
    terminal INTEGER NOT NULL DEFAULT 0 CHECK (terminal IN (0, 1)),
    propensity_json TEXT CHECK (
        propensity_json IS NULL OR (
            length(propensity_json) BETWEEN 1 AND 65536 AND
            instr(propensity_json, char(0)) = 0
        )
    ),
    support_json TEXT CHECK (
        support_json IS NULL OR (
            length(support_json) BETWEEN 1 AND 65536 AND
            instr(support_json, char(0)) = 0
        )
    ),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (
        length(metadata_json) BETWEEN 1 AND 65536 AND
        instr(metadata_json, char(0)) = 0
    ),
    reason TEXT NOT NULL DEFAULT 'not_applicable' CHECK (
        length(trim(reason)) BETWEEN 1 AND 512 AND
        instr(reason, char(0)) = 0
    ),
    external_effect_executed INTEGER NOT NULL DEFAULT 0 CHECK (
        external_effect_executed IN (0, 1)
    ),
    kg_write_authority INTEGER NOT NULL DEFAULT 0 CHECK (kg_write_authority IN (0, 1)),
    production_caller INTEGER NOT NULL DEFAULT 0 CHECK (production_caller IN (0, 1)),
    lease_id TEXT NOT NULL CHECK (
        length(trim(lease_id)) BETWEEN 1 AND 512 AND
        instr(lease_id, char(0)) = 0
    ),
    lease_head_sha256 TEXT NOT NULL CHECK (
        length(lease_head_sha256) = 64 AND
        lease_head_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token_sha256 TEXT NOT NULL CHECK (
        length(fencing_token_sha256) = 64 AND
        fencing_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    state_digest TEXT NOT NULL CHECK (
        length(state_digest) = 64 AND state_digest NOT GLOB '*[^0-9a-f]*'
    ),
    policy_digest TEXT NOT NULL CHECK (
        length(policy_digest) = 64 AND policy_digest NOT GLOB '*[^0-9a-f]*'
    ),
    model_receipt_digest TEXT NOT NULL CHECK (
        length(model_receipt_digest) = 64 AND
        model_receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    payload_json TEXT NOT NULL CHECK (
        length(payload_json) BETWEEN 1 AND 262144 AND
        instr(payload_json, char(0)) = 0
    ),
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64 AND
        payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND
        previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_sha256 TEXT NOT NULL CHECK (
        length(event_sha256) = 64 AND
        event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_seconds INTEGER NOT NULL CHECK (recorded_at_unix_seconds >= 0),
    PRIMARY KEY (owner_agent_id, trajectory_id, event_seq),
    UNIQUE (owner_agent_id, trajectory_id, event_id),
    UNIQUE (owner_agent_id, trajectory_id, occurrence_key),
    CHECK (
        (event_seq = 1 AND event_kind = 'turn_start' AND terminal = 0 AND
         causal_parent_seq IS NULL AND causal_parent_sha256 IS NULL) OR
        (event_seq > 1 AND causal_parent_seq = event_seq - 1)
    ),
    CHECK (
        (terminal = 1 AND event_kind = 'terminal') OR
        (terminal = 0 AND event_kind <> 'terminal')
    ),
    CHECK (
        external_effect_executed = 0 AND
        kg_write_authority = 0 AND
        production_caller = 0
    )
) STRICT;

CREATE TRIGGER cognitive_h7_trajectory_events_no_update
BEFORE UPDATE ON cognitive_h7_trajectory_events BEGIN
    SELECT RAISE(ABORT, 'H7 trajectory events are immutable');
END;

CREATE TRIGGER cognitive_h7_trajectory_events_no_delete
BEFORE DELETE ON cognitive_h7_trajectory_events BEGIN
    SELECT RAISE(ABORT, 'H7 trajectory events are immutable');
END;

CREATE INDEX cognitive_h7_trajectory_events_trajectory_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, trajectory_id, event_seq);

CREATE INDEX cognitive_h7_trajectory_events_turn_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, turn_id, trajectory_id, event_seq);

CREATE INDEX cognitive_h7_trajectory_events_lease_binding
ON cognitive_h7_trajectory_events(
    owner_agent_id, lease_id, lease_head_sha256, trajectory_id, event_seq
);

CREATE INDEX cognitive_h7_trajectory_events_causal_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, causal_parent_sha256);

CREATE INDEX cognitive_h7_trajectory_events_occurrence_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, trajectory_id, occurrence_key);

CREATE INDEX cognitive_h7_trajectory_events_receipt_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, receipt_sha256, trajectory_id, event_seq);

CREATE INDEX cognitive_h7_trajectory_events_kind_lookup
ON cognitive_h7_trajectory_events(owner_agent_id, trajectory_id, event_kind, event_seq);
