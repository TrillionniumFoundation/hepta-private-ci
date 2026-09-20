-- Canonical engineering owner schema, version 7. Applied in one transaction.

CREATE TABLE IF NOT EXISTS work_envelopes(
  envelope_id TEXT PRIMARY KEY,
  semantic_digest TEXT NOT NULL,
  source_commit TEXT NOT NULL,
  source_tree TEXT NOT NULL,
  objective_digest TEXT NOT NULL,
  contract_digest TEXT NOT NULL,
  owner TEXT NOT NULL,
  allowed_paths_json BLOB NOT NULL,
  denied_authorities_json BLOB NOT NULL,
  maximum_assignments INTEGER NOT NULL CHECK(maximum_assignments BETWEEN 1 AND 128),
  expires_unix_ns INTEGER NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 1),
  created_unix_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS path_leases(
  lease_id TEXT PRIMARY KEY,
  envelope_id TEXT NOT NULL REFERENCES work_envelopes(envelope_id),
  holder TEXT NOT NULL,
  paths_json BLOB NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('active','released','revoked','expired')),
  authority_epoch INTEGER NOT NULL CHECK(authority_epoch >= 1),
  fencing_token INTEGER NOT NULL UNIQUE CHECK(fencing_token >= 1),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  issued_unix_ns INTEGER NOT NULL,
  expires_unix_ns INTEGER NOT NULL,
  semantic_digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS path_leases_active
  ON path_leases(state, expires_unix_ns);
CREATE TABLE IF NOT EXISTS assignment_generations(
  generation_id TEXT PRIMARY KEY,
  envelope_id TEXT NOT NULL REFERENCES work_envelopes(envelope_id),
  semantic_digest TEXT NOT NULL,
  assigned_json BLOB NOT NULL,
  blocked_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS orchestration_generations(
  generation_id TEXT PRIMARY KEY,
  semantic_digest TEXT NOT NULL,
  plan_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL,
  FOREIGN KEY(generation_id)
    REFERENCES assignment_generations(generation_id)
    DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS worker_registrations(
  worker_id TEXT PRIMARY KEY,
  profile_digest TEXT NOT NULL,
  worker_signing_identity TEXT NOT NULL,
  skills_json BLOB NOT NULL,
  allowed_paths_json BLOB NOT NULL,
  capacity_units INTEGER NOT NULL CHECK(capacity_units BETWEEN 1 AND 1000000),
  issuer TEXT NOT NULL,
  authority_signing_identity TEXT NOT NULL,
  observed_unix_ns INTEGER NOT NULL,
  expires_unix_ns INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('active','revoked')),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  last_heartbeat_unix_ns INTEGER,
  recorded_unix_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_claims(
  claim_id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL REFERENCES orchestration_generations(generation_id),
  package_id TEXT NOT NULL,
  worker_id TEXT NOT NULL REFERENCES worker_registrations(worker_id),
  lease_id TEXT NOT NULL REFERENCES path_leases(lease_id),
  attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 3),
  state TEXT NOT NULL CHECK(state IN (
    'claimed','running','result_submitted','retryable','failed','completed_observed'
  )),
  claim_fence INTEGER NOT NULL UNIQUE CHECK(claim_fence >= 1),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  claimed_unix_ns INTEGER NOT NULL,
  last_heartbeat_unix_ns INTEGER NOT NULL,
  heartbeat_deadline_unix_ns INTEGER NOT NULL,
  result_digest TEXT,
  failure_class TEXT,
  semantic_digest TEXT NOT NULL,
  updated_unix_ns INTEGER NOT NULL,
  UNIQUE(generation_id, package_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_worker_claims_assignment
  ON worker_claims(generation_id, package_id, state, attempt);
CREATE INDEX IF NOT EXISTS idx_worker_claims_worker
  ON worker_claims(worker_id, state, heartbeat_deadline_unix_ns);
CREATE TABLE IF NOT EXISTS distributed_cluster_frontiers(
  cluster_id TEXT PRIMARY KEY,
  leader_id TEXT NOT NULL,
  leader_term INTEGER NOT NULL CHECK(leader_term >= 1),
  revocation_frontier_sequence INTEGER NOT NULL CHECK(revocation_frontier_sequence >= 1),
  revocation_frontier_digest TEXT NOT NULL,
  updated_unix_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS distributed_fence_frontiers(
  cluster_id TEXT NOT NULL,
  holder TEXT NOT NULL,
  leader_id TEXT NOT NULL,
  leader_term INTEGER NOT NULL CHECK(leader_term >= 1),
  revocation_frontier_sequence INTEGER NOT NULL CHECK(revocation_frontier_sequence >= 1),
  revocation_frontier_digest TEXT NOT NULL,
  fence_receipt_digest TEXT NOT NULL,
  lease_id TEXT NOT NULL,
  authority_epoch INTEGER NOT NULL CHECK(authority_epoch >= 1),
  fencing_token INTEGER NOT NULL CHECK(fencing_token >= 1),
  lease_revision INTEGER NOT NULL CHECK(lease_revision >= 1),
  source_commit TEXT NOT NULL,
  source_tree TEXT NOT NULL,
  observed_unix_ns INTEGER NOT NULL,
  expires_unix_ns INTEGER NOT NULL,
  updated_unix_ns INTEGER NOT NULL,
  PRIMARY KEY(cluster_id, holder)
);
CREATE INDEX IF NOT EXISTS idx_distributed_fence_frontiers_order
  ON distributed_fence_frontiers(cluster_id, leader_term, revocation_frontier_sequence);

CREATE TABLE IF NOT EXISTS integration_decisions(
  decision_id TEXT PRIMARY KEY,
  evidence_digest TEXT NOT NULL,
  eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
  reasons_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events(
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  previous_digest TEXT NOT NULL,
  event_digest TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  payload_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS engineering_schema_meta(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  schema_version INTEGER NOT NULL CHECK(schema_version>=1),
  updated_unix_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS assignment_generation_frontiers(
  generation_id TEXT PRIMARY KEY,
  envelope_id TEXT NOT NULL,
  envelope_revision INTEGER NOT NULL CHECK(envelope_revision>=1),
  source_commit TEXT NOT NULL,
  source_tree TEXT NOT NULL,
  frontier_digest TEXT NOT NULL,
  created_unix_ns INTEGER NOT NULL,
  FOREIGN KEY(generation_id)
    REFERENCES assignment_generations(generation_id)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(envelope_id) REFERENCES work_envelopes(envelope_id)
);

CREATE TABLE IF NOT EXISTS integration_decision_bindings(
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL,
  candidate_digest TEXT NOT NULL,
  sandbox_receipt_digest TEXT NOT NULL,
  binding_receipt_digest TEXT NOT NULL,
  bound_evidence_digest TEXT NOT NULL,
  recorded_unix_ns INTEGER NOT NULL,
  semantic_digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_integration_decision_bindings_candidate
  ON integration_decision_bindings(candidate_id);

CREATE TABLE IF NOT EXISTS integration_decision_seals(
  decision_id TEXT PRIMARY KEY,
  seal_digest TEXT NOT NULL UNIQUE,
  sealed_evidence_digest TEXT NOT NULL UNIQUE,
  issuer TEXT NOT NULL,
  signing_identity TEXT NOT NULL,
  observed_unix_ns INTEGER NOT NULL,
  expires_unix_ns INTEGER NOT NULL,
  signature_digest TEXT NOT NULL,
  recorded_unix_ns INTEGER NOT NULL,
  semantic_digest TEXT NOT NULL,
  FOREIGN KEY(decision_id)
    REFERENCES integration_decision_bindings(decision_id)
    DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS idx_integration_decision_seals_identity
  ON integration_decision_seals(issuer,signing_identity,observed_unix_ns);
