-- External restore checkpoint binding and replay-epoch tombstones.
CREATE TABLE authbus_restore_checkpoint (
    singleton INTEGER PRIMARY KEY NOT NULL CHECK(singleton = 1),
    generation BLOB NOT NULL CHECK(length(generation) = 8),
    checkpoint_digest BLOB NOT NULL CHECK(length(checkpoint_digest) = 32),
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE authbus_retired_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK(length(key_epoch) = 8),
    checkpoint_generation BLOB NOT NULL CHECK(length(checkpoint_generation) = 8),
    checkpoint_digest BLOB NOT NULL CHECK(length(checkpoint_digest) = 32),
    retired_at_ms INTEGER NOT NULL,
    PRIMARY KEY(issuer_id, key_epoch)
) WITHOUT ROWID;
