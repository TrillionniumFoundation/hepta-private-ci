CREATE TABLE authbus_issuer_floor (
    issuer_id TEXT PRIMARY KEY,
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    public_key BLOB NOT NULL CHECK (length(public_key) = 1974),
    revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)),
    wall_time_floor_ms INTEGER NOT NULL CHECK (wall_time_floor_ms >= 0)
) WITHOUT ROWID;
CREATE TRIGGER authbus_issuer_floor_monotonic BEFORE UPDATE ON authbus_issuer_floor
WHEN NEW.issuer_id != OLD.issuer_id OR NEW.key_epoch < OLD.key_epoch
    OR NEW.wall_time_floor_ms < OLD.wall_time_floor_ms
    OR (NEW.key_epoch = OLD.key_epoch AND
        (NEW.public_key != OLD.public_key OR NEW.revoked < OLD.revoked))
BEGIN SELECT RAISE(ABORT, 'AuthBus issuer floor cannot regress'); END;
CREATE TRIGGER authbus_issuer_floor_no_delete BEFORE DELETE ON authbus_issuer_floor
BEGIN SELECT RAISE(ABORT, 'AuthBus issuer floor cannot be deleted'); END;
