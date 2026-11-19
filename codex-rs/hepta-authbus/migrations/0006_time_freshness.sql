ALTER TABLE authbus_trusted_time ADD COLUMN valid_until_ms BLOB
    CHECK (valid_until_ms IS NULL OR length(valid_until_ms) = 8);
CREATE TABLE authbus_time_challenge (
    nonce BLOB PRIMARY KEY CHECK (length(nonce) = 32),
    issued_at_ms BLOB NOT NULL CHECK (length(issued_at_ms) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8)
) WITHOUT ROWID;
CREATE TRIGGER authbus_dirty_challenge_insert AFTER INSERT ON authbus_time_challenge
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_challenge_delete AFTER DELETE ON authbus_time_challenge
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_challenge_immutable BEFORE UPDATE ON authbus_time_challenge
BEGIN SELECT RAISE(ABORT, 'AuthBus time challenge is immutable'); END;
