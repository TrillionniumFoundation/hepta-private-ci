-- Canonical engineering owner schema, version 5. Applied in one transaction.

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
