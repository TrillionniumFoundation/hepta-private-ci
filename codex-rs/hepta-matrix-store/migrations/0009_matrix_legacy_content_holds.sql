-- Snapshot pre-canonicalization attempts without inventing their send identity.
-- New pre-pin cancellations can recover; ambiguous historical attempts cannot.

CREATE TABLE matrix_dispatch_legacy_content_holds (
    stable_txn_id TEXT PRIMARY KEY,
    inherited_attempts INTEGER NOT NULL CHECK (inherited_attempts > 0),
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id) ON DELETE RESTRICT
) STRICT;

INSERT INTO matrix_dispatch_legacy_content_holds (stable_txn_id, inherited_attempts)
SELECT message.stable_txn_id, message.attempts
FROM outbox_messages AS message
LEFT JOIN matrix_dispatch_content_bindings AS pin USING (stable_txn_id)
WHERE message.attempts > 0 AND pin.stable_txn_id IS NULL;

CREATE TRIGGER matrix_dispatch_legacy_content_holds_no_insert
BEFORE INSERT ON matrix_dispatch_legacy_content_holds BEGIN
    SELECT RAISE(ABORT, 'Matrix legacy content hold snapshot is sealed');
END;

CREATE TRIGGER matrix_dispatch_legacy_content_holds_no_update
BEFORE UPDATE ON matrix_dispatch_legacy_content_holds BEGIN
    SELECT RAISE(ABORT, 'Matrix legacy content hold snapshot is sealed');
END;

CREATE TRIGGER matrix_dispatch_legacy_content_holds_no_delete
BEFORE DELETE ON matrix_dispatch_legacy_content_holds BEGIN
    SELECT RAISE(ABORT, 'Matrix legacy content hold snapshot is sealed');
END;
