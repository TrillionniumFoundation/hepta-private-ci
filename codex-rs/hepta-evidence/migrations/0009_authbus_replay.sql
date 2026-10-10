-- Replay admission shares the evidence lineage and its durable SQLite owner.
-- Big-endian fixed-width integers preserve the complete u64 range.
CREATE TABLE authbus_replay_sequences (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    subject_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK(length(scope_digest) = 32),
    sequence BLOB NOT NULL CHECK(length(sequence) = 8),
    envelope_digest BLOB NOT NULL CHECK(length(envelope_digest) = 32),
    PRIMARY KEY(issuer_id, key_epoch, subject_id, scope_digest)
) WITHOUT ROWID;
