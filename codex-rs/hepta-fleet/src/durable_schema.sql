CREATE TABLE IF NOT EXISTS fleet_schema (
 singleton INTEGER PRIMARY KEY CHECK(singleton = 1), schema_version INTEGER NOT NULL,
 lineage TEXT NOT NULL, created_at_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_clock (
 singleton INTEGER PRIMARY KEY CHECK(singleton = 1), last_now_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_hosts (
 host_id TEXT PRIMARY KEY, failure_domain_id TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation > 0), observed_at_ms INTEGER NOT NULL, valid_until_ms INTEGER NOT NULL,
 cpu_millis INTEGER NOT NULL CHECK(cpu_millis >= 0), memory_bytes INTEGER NOT NULL CHECK(memory_bytes >= 0),
 accelerator_millis INTEGER NOT NULL CHECK(accelerator_millis >= 0), concurrent_turns INTEGER NOT NULL CHECK(concurrent_turns >= 0),
 tool_processes INTEGER NOT NULL CHECK(tool_processes >= 0), turn_queue_slots INTEGER NOT NULL CHECK(turn_queue_slots >= 0),
 capacity_digest TEXT NOT NULL, CHECK(observed_at_ms < valid_until_ms)
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_capacity_observations (
 host_id TEXT NOT NULL, generation INTEGER NOT NULL, observed_at_ms INTEGER NOT NULL, valid_until_ms INTEGER NOT NULL,
 source_id TEXT NOT NULL, cpu_millis INTEGER NOT NULL, memory_bytes INTEGER NOT NULL, accelerator_millis INTEGER NOT NULL,
 concurrent_turns INTEGER NOT NULL, tool_processes INTEGER NOT NULL, turn_queue_slots INTEGER NOT NULL, capacity_digest TEXT NOT NULL,
 PRIMARY KEY(host_id, generation, observed_at_ms)
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_grants (
 allocation_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 host_id TEXT NOT NULL REFERENCES fleet_hosts(host_id), failure_domain_id TEXT NOT NULL,
 host_generation INTEGER NOT NULL, authority_epoch INTEGER NOT NULL, lease_generation INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL,
 cpu_millis INTEGER NOT NULL, memory_bytes INTEGER NOT NULL, accelerator_millis INTEGER NOT NULL,
 concurrent_turns INTEGER NOT NULL, tool_processes INTEGER NOT NULL, turn_queue_slots INTEGER NOT NULL,
 resource_digest TEXT NOT NULL, semantic_digest TEXT NOT NULL, authority_witness_json TEXT NOT NULL,
 created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS fleet_grants_expiry_idx ON fleet_grants(expires_at_ms, allocation_id);
CREATE INDEX IF NOT EXISTS fleet_grants_host_idx ON fleet_grants(host_id, host_generation, allocation_id);
CREATE TABLE IF NOT EXISTS fleet_grant_history (
 allocation_id TEXT PRIMARY KEY, terminal_state TEXT NOT NULL, grant_json TEXT, final_digest TEXT NOT NULL,
 retired_at_ms INTEGER NOT NULL, compacted INTEGER NOT NULL DEFAULT 0 CHECK(compacted IN (0, 1))
) STRICT;
CREATE INDEX IF NOT EXISTS fleet_grant_history_retired_idx ON fleet_grant_history(compacted, retired_at_ms, allocation_id);
CREATE TABLE IF NOT EXISTS fleet_resource_totals (
 host_id TEXT PRIMARY KEY REFERENCES fleet_hosts(host_id), cpu_millis INTEGER NOT NULL, memory_bytes INTEGER NOT NULL,
 accelerator_millis INTEGER NOT NULL, concurrent_turns INTEGER NOT NULL, tool_processes INTEGER NOT NULL,
 turn_queue_slots INTEGER NOT NULL, resource_digest TEXT NOT NULL, updated_at_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_revocation_frontier (
 singleton INTEGER PRIMARY KEY CHECK(singleton = 1), authority_epoch INTEGER NOT NULL, revision INTEGER NOT NULL,
 issued_at_ms INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL, convergence_deadline_ms INTEGER NOT NULL,
 update_digest TEXT NOT NULL, update_json TEXT NOT NULL, updated_at_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_revocation_acks (
 authority_epoch INTEGER NOT NULL, revision INTEGER NOT NULL, node_id TEXT NOT NULL,
 ack_digest TEXT NOT NULL, ack_json TEXT NOT NULL, applied_at_ms INTEGER NOT NULL,
 PRIMARY KEY(authority_epoch, revision, node_id)
) STRICT;
CREATE TABLE IF NOT EXISTS workspace_reservations (
 agent_id TEXT PRIMARY KEY, workspace TEXT NOT NULL UNIQUE, workspace_digest TEXT NOT NULL,
 created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_operation_receipts (
 operation_id TEXT PRIMARY KEY, operation_kind TEXT NOT NULL, subject_id TEXT NOT NULL, outcome TEXT NOT NULL,
 semantic_digest TEXT NOT NULL, authority_witness_json TEXT, payload_json TEXT NOT NULL, committed_at_ms INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS fleet_operation_subject_idx ON fleet_operation_receipts(subject_id, committed_at_ms, operation_id);
CREATE TABLE IF NOT EXISTS fleet_metric_counters (
 operation TEXT NOT NULL, result TEXT NOT NULL, value INTEGER NOT NULL CHECK(value >= 0), PRIMARY KEY(operation, result)
) STRICT;
