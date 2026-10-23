-- Exhausting a retry budget cannot prove that a send failed at the server.
-- Park the exact outstanding attempt without rewriting its durable identity.
CREATE TABLE outbox_unresolved (
    stable_txn_id TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    reason TEXT NOT NULL CHECK (reason = 'unknown_delivery'),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER outbox_unresolved_guard_insert
BEFORE INSERT ON outbox_unresolved BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM outbox_messages
        WHERE stable_txn_id = NEW.stable_txn_id AND state = 'in_flight'
          AND attempts = NEW.attempts AND updated_at_ms <= NEW.recorded_at_ms
    ) THEN RAISE(ABORT, 'unresolved outbox attempt is not current') END;
END;

CREATE TRIGGER outbox_unresolved_no_update
BEFORE UPDATE ON outbox_unresolved BEGIN
    SELECT RAISE(ABORT, 'unresolved outbox attempt is immutable');
END;

CREATE TRIGGER outbox_unresolved_guard_delete
BEFORE DELETE ON outbox_unresolved BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM outbox_messages
        WHERE stable_txn_id = OLD.stable_txn_id AND state = 'in_flight'
    ) THEN RAISE(ABORT, 'unresolved outbox attempt requires a terminal observation') END;
END;
