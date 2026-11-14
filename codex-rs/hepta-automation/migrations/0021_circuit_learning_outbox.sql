-- Delivery metadata only. Neither this queue nor its ACK grants learning authority.
CREATE TABLE circuit_learning_outbox_v1 (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    intent_json TEXT NOT NULL CHECK(length(intent_json) <= 2048),
    request_digest TEXT,
    acknowledged_head TEXT,
    PRIMARY KEY(owner_agent_id, run_id),
    FOREIGN KEY(owner_agent_id, run_id) REFERENCES circuit_v2_runs(owner_agent_id, run_id),
    CHECK(request_digest IS NULL OR length(request_digest) = 64),
    CHECK(acknowledged_head IS NULL OR (request_digest IS NOT NULL AND length(acknowledged_head) = 64))
);
