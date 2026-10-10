-- Replay anti-rollback handshake. The durable evidence owner stages every
-- replay-frontier mutation as pending until an independently retained witness
-- confirms the exact next generation and frontier digest.
CREATE TABLE authbus_restore_checkpoint (
    singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
    generation BLOB NOT NULL CHECK (length(generation) = 8),
    checkpoint_digest BLOB NOT NULL CHECK (length(checkpoint_digest) = 32),
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE authbus_restore_checkpoint_pending (
    singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
    generation BLOB NOT NULL CHECK (length(generation) = 8),
    checkpoint_digest BLOB NOT NULL CHECK (length(checkpoint_digest) = 32),
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE authbus_retired_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    retirement_digest BLOB NOT NULL CHECK (length(retirement_digest) = 32),
    retired_at_ms INTEGER NOT NULL,
    PRIMARY KEY(issuer_id, key_epoch)
) WITHOUT ROWID;
