CREATE TABLE matrix_sync_checkpoint (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    next_batch TEXT NOT NULL CHECK (
        length(next_batch) BETWEEN 1 AND 4096
        AND next_batch NOT GLOB '*[^ -~]*'
    ),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) STRICT;

CREATE TRIGGER matrix_sync_checkpoint_no_delete
BEFORE DELETE ON matrix_sync_checkpoint BEGIN
    SELECT RAISE(ABORT, 'matrix sync checkpoint cannot be deleted');
END;
