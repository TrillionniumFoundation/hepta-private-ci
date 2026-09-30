-- Persistent monotonic time floor for AuthBus admission, delivery leases and
-- retention. Host-clock rollback clamps to this owner-held floor instead of
-- extending a message or blocking delivery until wall time catches up.
CREATE TABLE authbus_time_floor (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    revision INTEGER NOT NULL CHECK (revision >= 1)
) WITHOUT ROWID;

INSERT INTO authbus_time_floor(singleton, observed_at_ms, revision)
VALUES (1, 0, 1);

CREATE TRIGGER authbus_time_floor_identity_immutable
BEFORE UPDATE OF singleton ON authbus_time_floor
BEGIN
    SELECT RAISE(ABORT, 'AuthBus time-floor identity is immutable');
END;

CREATE TRIGGER authbus_time_floor_monotonic
BEFORE UPDATE OF observed_at_ms, revision ON authbus_time_floor
WHEN NEW.observed_at_ms <= OLD.observed_at_ms
  OR NEW.revision != OLD.revision + 1
BEGIN
    SELECT RAISE(ABORT, 'AuthBus time floor must advance monotonically');
END;

CREATE TRIGGER authbus_time_floor_delete_forbidden
BEFORE DELETE ON authbus_time_floor
BEGIN
    SELECT RAISE(ABORT, 'AuthBus time floor cannot be deleted');
END;
