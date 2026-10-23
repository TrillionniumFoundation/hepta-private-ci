-- Derived state belongs to the existing cognitive owner; no facts or outbox effects.
CREATE TABLE cognitive_memory_cell_checkpoints (
    scope_key TEXT NOT NULL CHECK(length(scope_key) BETWEEN 1 AND 128),
    cell_id TEXT NOT NULL CHECK(length(cell_id) BETWEEN 1 AND 256),
    logical_sequence INTEGER NOT NULL CHECK(logical_sequence > 0),
    checkpoint_sha256 TEXT NOT NULL CHECK(length(checkpoint_sha256) = 64),
    predecessor_sha256 TEXT CHECK(predecessor_sha256 IS NULL OR length(predecessor_sha256) = 64),
    owner_cut_sha256 TEXT NOT NULL CHECK(length(owner_cut_sha256) = 64),
    source_frontier INTEGER NOT NULL CHECK(source_frontier >= 0),
    tombstone_frontier INTEGER NOT NULL CHECK(tombstone_frontier >= 0),
    header_json TEXT NOT NULL CHECK(length(CAST(header_json AS BLOB)) BETWEEN 1 AND 16384),
    state_bytes BLOB NOT NULL CHECK(length(state_bytes) BETWEEN 1 AND 1048576),
    recall_bytes BLOB NOT NULL CHECK(length(recall_bytes) BETWEEN 1 AND 524288),
    lease_id TEXT NOT NULL,
    lease_sha256 TEXT NOT NULL,
    authority_grant_sha256 TEXT NOT NULL CHECK(length(authority_grant_sha256) = 64),
    CHECK((logical_sequence = 1) = (predecessor_sha256 IS NULL)),
    PRIMARY KEY(scope_key, cell_id, logical_sequence),
    UNIQUE(scope_key, cell_id, checkpoint_sha256),
    FOREIGN KEY(lease_id, lease_sha256) REFERENCES cognitive_local_leases(lease_id, lease_sha256)
) STRICT;
CREATE TRIGGER cognitive_memory_cell_checkpoints_no_update
BEFORE UPDATE ON cognitive_memory_cell_checkpoints BEGIN
    SELECT RAISE(ABORT, 'MemoryCell checkpoint history is immutable');
END;
CREATE TRIGGER cognitive_memory_cell_checkpoints_no_delete
BEFORE DELETE ON cognitive_memory_cell_checkpoints BEGIN
    SELECT RAISE(ABORT, 'MemoryCell checkpoint history is immutable');
END;
CREATE TABLE cognitive_memory_cell_heads (
    scope_key TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    logical_sequence INTEGER NOT NULL CHECK(logical_sequence > 0),
    PRIMARY KEY(scope_key, cell_id),
    FOREIGN KEY(scope_key, cell_id, logical_sequence)
        REFERENCES cognitive_memory_cell_checkpoints(scope_key, cell_id, logical_sequence)
) STRICT;
CREATE TRIGGER cognitive_memory_cell_heads_no_delete
BEFORE DELETE ON cognitive_memory_cell_heads BEGIN
    SELECT RAISE(ABORT, 'MemoryCell head cannot be deleted');
END;
CREATE TRIGGER cognitive_memory_cell_heads_monotonic
BEFORE UPDATE ON cognitive_memory_cell_heads
WHEN NEW.scope_key != OLD.scope_key OR NEW.cell_id != OLD.cell_id
     OR NEW.logical_sequence != OLD.logical_sequence + 1 BEGIN
    SELECT RAISE(ABORT, 'MemoryCell head must advance by one');
END;
