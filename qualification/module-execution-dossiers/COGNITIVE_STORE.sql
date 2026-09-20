-- Qualification DDL only. Not an installed product schema or authority store.
PRAGMA foreign_keys = ON;
CREATE TABLE frontier (
  scope TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence >= 0),
  digest BLOB NOT NULL CHECK(typeof(digest)='blob' AND length(digest)=32)
);
CREATE TABLE event (
  scope TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence > 0),
  record_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision > 0),
  kind TEXT NOT NULL CHECK(kind IN ('fact','correction','tombstone')),
  predecessor_digest BLOB CHECK(predecessor_digest IS NULL OR (typeof(predecessor_digest)='blob' AND length(predecessor_digest)=32)),
  payload_digest BLOB NOT NULL CHECK(typeof(payload_digest)='blob' AND length(payload_digest)=32),
  payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload)<=262144),
  PRIMARY KEY(scope,sequence),
  UNIQUE(scope,record_id,revision),
  UNIQUE(scope,record_id,sequence),
  FOREIGN KEY(scope) REFERENCES frontier(scope)
);
CREATE TABLE current_record (
  scope TEXT NOT NULL,
  record_id TEXT NOT NULL,
  event_sequence INTEGER NOT NULL,
  PRIMARY KEY(scope,record_id),
  FOREIGN KEY(scope,record_id,event_sequence) REFERENCES event(scope,record_id,sequence)
);
CREATE TABLE revocation (
  scope TEXT NOT NULL,
  revocation_sequence INTEGER NOT NULL CHECK(typeof(revocation_sequence)='integer' AND revocation_sequence > 0),
  source_id TEXT NOT NULL,
  cutoff_event_sequence INTEGER NOT NULL CHECK(typeof(cutoff_event_sequence)='integer' AND cutoff_event_sequence >= 0),
  proof_digest BLOB NOT NULL CHECK(typeof(proof_digest)='blob' AND length(proof_digest)=32),
  PRIMARY KEY(scope,revocation_sequence),
  FOREIGN KEY(scope) REFERENCES frontier(scope)
);
CREATE INDEX revocation_source ON revocation(scope,source_id,cutoff_event_sequence);
CREATE TABLE mutation (
  scope TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  semantic_digest BLOB NOT NULL CHECK(typeof(semantic_digest)='blob' AND length(semantic_digest)=32),
  committed_sequence INTEGER NOT NULL CHECK(typeof(committed_sequence)='integer' AND committed_sequence > 0),
  receipt_digest BLOB NOT NULL CHECK(typeof(receipt_digest)='blob' AND length(receipt_digest)=32),
  PRIMARY KEY(scope,operation_id),
  FOREIGN KEY(scope,committed_sequence) REFERENCES event(scope,sequence)
);
CREATE TABLE publication_intent (
  scope TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  destination_owner TEXT NOT NULL,
  payload_digest BLOB NOT NULL CHECK(typeof(payload_digest)='blob' AND length(payload_digest)=32),
  disposition TEXT NOT NULL CHECK(disposition IN ('pending','acknowledged','quarantined')),
  PRIMARY KEY(scope,operation_id,destination_owner),
  FOREIGN KEY(scope,operation_id) REFERENCES mutation(scope,operation_id)
);
