CREATE TABLE authbus_owner_policy_floor (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    policy_revision BLOB NOT NULL CHECK (length(policy_revision) = 8 AND policy_revision > X'0000000000000000'),
    policy_digest BLOB NOT NULL CHECK (length(policy_digest) = 32)
) WITHOUT ROWID;
CREATE TRIGGER authbus_owner_policy_monotonic BEFORE UPDATE ON authbus_owner_policy_floor
WHEN NEW.singleton != OLD.singleton OR NEW.policy_revision < OLD.policy_revision
    OR (NEW.policy_revision = OLD.policy_revision AND NEW.policy_digest != OLD.policy_digest)
BEGIN SELECT RAISE(ABORT, 'AuthBus owner policy cannot regress'); END;
CREATE TRIGGER authbus_owner_policy_no_delete BEFORE DELETE ON authbus_owner_policy_floor
BEGIN SELECT RAISE(ABORT, 'AuthBus owner policy cannot be deleted'); END;
