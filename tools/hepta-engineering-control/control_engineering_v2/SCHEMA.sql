PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;

CREATE TABLE work_envelopes(
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

CREATE TABLE path_leases(
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

CREATE INDEX path_leases_active ON path_leases(state, expires_unix_ns);

CREATE TABLE assignment_generations(
  generation_id TEXT PRIMARY KEY,
  envelope_id TEXT NOT NULL REFERENCES work_envelopes(envelope_id),
  semantic_digest TEXT NOT NULL,
  assigned_json BLOB NOT NULL,
  blocked_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);

CREATE TABLE integration_decisions(
  decision_id TEXT PRIMARY KEY,
  evidence_digest TEXT NOT NULL,
  eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
  reasons_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);

CREATE TABLE audit_events(
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  previous_digest TEXT NOT NULL,
  event_digest TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  payload_json BLOB NOT NULL,
  created_unix_ns INTEGER NOT NULL
);
