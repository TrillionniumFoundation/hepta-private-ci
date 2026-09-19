-- Safe replay-key retirement keeps a permanent issuer/epoch tombstone while
-- allowing high-water rows for that retired epoch to be deleted.
CREATE TABLE authbus_retired_epochs (
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    retirement_digest BLOB NOT NULL CHECK (length(retirement_digest) = 32),
    PRIMARY KEY (issuer_id, key_epoch)
) WITHOUT ROWID;
