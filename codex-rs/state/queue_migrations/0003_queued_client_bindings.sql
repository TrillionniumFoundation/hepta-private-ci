CREATE TABLE queued_client_bindings (
    thread_id TEXT NOT NULL,
    client_user_message_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('reserved', 'queued', 'dispatching', 'persisted', 'cancelled')
    ),
    queued_item_id TEXT,
    turn_id TEXT,
    reservation_id TEXT NOT NULL,
    dispatch_owner_id TEXT,
    dispatch_lease_expires_at_ms INTEGER,
    dispatch_lock_device INTEGER,
    dispatch_lock_inode INTEGER,
    revision INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (thread_id, client_user_message_id),
    UNIQUE (queued_item_id),
    CHECK (length(thread_id) > 0),
    CHECK (length(client_user_message_id) BETWEEN 1 AND 256),
    CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    CHECK (length(reservation_id) > 0),
    CHECK (revision >= 1),
    CHECK (created_at_ms >= 0 AND updated_at_ms >= created_at_ms),
    CHECK (queued_item_id IS NULL OR length(queued_item_id) > 0),
    CHECK (turn_id IS NULL OR length(turn_id) > 0),
    CHECK (dispatch_owner_id IS NULL OR length(dispatch_owner_id) BETWEEN 1 AND 256),
    CHECK (
        dispatch_lease_expires_at_ms IS NULL
        OR dispatch_lease_expires_at_ms >= 0
    ),
    CHECK (dispatch_lock_device IS NULL OR dispatch_lock_device >= 0),
    CHECK (dispatch_lock_inode IS NULL OR dispatch_lock_inode >= 0),
    CHECK (
        (
            state = 'reserved'
            AND queued_item_id IS NOT NULL
            AND turn_id IS NULL
            AND dispatch_owner_id IS NULL
            AND dispatch_lease_expires_at_ms IS NULL
            AND dispatch_lock_device IS NULL
            AND dispatch_lock_inode IS NULL
        )
        OR (
            state = 'queued'
            AND queued_item_id IS NOT NULL
            AND turn_id IS NULL
            AND dispatch_owner_id IS NULL
            AND dispatch_lease_expires_at_ms IS NULL
            AND (
                (dispatch_lock_device IS NULL AND dispatch_lock_inode IS NULL)
                OR (dispatch_lock_device IS NOT NULL AND dispatch_lock_inode IS NOT NULL)
            )
        )
        OR (
            state = 'dispatching'
            AND queued_item_id IS NOT NULL
            AND turn_id IS NULL
            AND dispatch_owner_id IS NOT NULL
            AND length(dispatch_owner_id) > 0
            AND dispatch_lease_expires_at_ms IS NOT NULL
            AND dispatch_lock_device IS NOT NULL
            AND dispatch_lock_inode IS NOT NULL
        )
        OR (
            state = 'persisted'
            AND queued_item_id IS NULL
            AND turn_id IS NOT NULL
            AND dispatch_owner_id IS NULL
            AND dispatch_lease_expires_at_ms IS NULL
            AND dispatch_lock_device IS NULL
            AND dispatch_lock_inode IS NULL
        )
        OR (
            state = 'cancelled'
            AND queued_item_id IS NULL
            AND turn_id IS NULL
            AND dispatch_owner_id IS NULL
            AND dispatch_lease_expires_at_ms IS NULL
            AND dispatch_lock_device IS NULL
            AND dispatch_lock_inode IS NULL
        )
    )
);

CREATE INDEX queued_client_bindings_state_idx
    ON queued_client_bindings(thread_id, state);

-- One queue database may use exactly one same-host dispatch lock directory
-- inode. This binds the kernel owner-death proof to the durable ledger and
-- makes a parent symlink retarget or directory unlink/recreate fail closed.
CREATE TABLE queue_dispatch_lock_root (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    device INTEGER NOT NULL,
    inode INTEGER NOT NULL
);

-- Permanent, per-thread queue tombstones.  A thread id is never reused, so a
-- successful delete seal must survive queue-row cleanup and process restart:
-- otherwise an old or concurrent writer could recreate work after the thread
-- store has already been removed.
CREATE TABLE queued_thread_deletion_fences (
    thread_id TEXT PRIMARY KEY NOT NULL CHECK (length(thread_id) > 0),
    deletion_id TEXT NOT NULL CHECK (length(deletion_id) > 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
);

-- Durable hard-delete operation journal.  The exact ordered closure is committed in the same
-- queue.sqlite writer transaction as every member fence, so a response loss or process restart
-- can resume after the thread store and AgentGraph rows have already disappeared.  A member may
-- legitimately appear in more than one operation (for example, a child was sealed before its
-- parent subtree); root+member identity therefore owns the mapping instead of member alone.
-- The journal is permanent and deliberately has no mutable `completed` bit: presence means the
-- seal committed, and both incomplete and completed operations replay the same idempotent
-- thread-store/StateDb deletion sequence.  This avoids a second cross-database completion commit.
CREATE TABLE queued_thread_deletion_operation_members (
    root_thread_id TEXT NOT NULL CHECK (length(root_thread_id) > 0),
    member_thread_id TEXT NOT NULL CHECK (length(member_thread_id) > 0),
    member_ordinal INTEGER NOT NULL CHECK (member_ordinal >= 0),
    operation_id TEXT NOT NULL CHECK (length(operation_id) > 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY(root_thread_id, member_thread_id),
    UNIQUE(root_thread_id, member_ordinal)
);

CREATE INDEX queued_thread_deletion_operation_member_idx
ON queued_thread_deletion_operation_members(member_thread_id);

-- These triggers are the compatibility backstop for older queue writers that
-- do not know about the G4 deletion fence.  Current writers also preflight the
-- tombstone inside their BEGIN IMMEDIATE transaction so callers receive a
-- typed conflict instead of a raw SQLite constraint error.
CREATE TRIGGER queued_items_reject_insert_after_thread_delete_seal
BEFORE INSERT ON queued_items
WHEN EXISTS (
    SELECT 1 FROM queued_thread_deletion_fences WHERE thread_id = NEW.thread_id
)
BEGIN
    SELECT RAISE(ABORT, 'thread queue is sealed for deletion');
END;

CREATE TRIGGER queued_items_reject_update_after_thread_delete_seal
BEFORE UPDATE ON queued_items
WHEN EXISTS (
    SELECT 1 FROM queued_thread_deletion_fences
    WHERE thread_id = OLD.thread_id OR thread_id = NEW.thread_id
)
BEGIN
    SELECT RAISE(ABORT, 'thread queue is sealed for deletion');
END;

CREATE TRIGGER queued_client_bindings_reject_insert_after_thread_delete_seal
BEFORE INSERT ON queued_client_bindings
WHEN EXISTS (
    SELECT 1 FROM queued_thread_deletion_fences WHERE thread_id = NEW.thread_id
)
BEGIN
    SELECT RAISE(ABORT, 'thread queue is sealed for deletion');
END;

CREATE TRIGGER queued_client_bindings_reject_update_after_thread_delete_seal
BEFORE UPDATE ON queued_client_bindings
WHEN EXISTS (
    SELECT 1 FROM queued_thread_deletion_fences
    WHERE thread_id = OLD.thread_id OR thread_id = NEW.thread_id
)
BEGIN
    SELECT RAISE(ABORT, 'thread queue is sealed for deletion');
END;
