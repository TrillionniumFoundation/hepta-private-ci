-- Retire only delivery capacity. Original identities and exact ACKs remain
-- durable in this same owner database and continue to fence every retry.
ALTER TABLE circuit_learning_outbox_v1 ADD COLUMN retired INTEGER NOT NULL DEFAULT 0
    CHECK(retired IN (0, 1) AND (retired = 0 OR acknowledged_head IS NOT NULL));

-- Active admission and pending polling must not scan cumulative retired history.
CREATE INDEX circuit_learning_outbox_active_v1
    ON circuit_learning_outbox_v1(owner_agent_id, run_id) WHERE retired = 0;
CREATE INDEX circuit_learning_outbox_pending_v1
    ON circuit_learning_outbox_v1(owner_agent_id, run_id) WHERE acknowledged_head IS NULL;
