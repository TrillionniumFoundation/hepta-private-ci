-- This belongs to the original state owner, not a second operation database.
-- Keys survive deletion and deliberately have no cascading thread foreign key.
CREATE TABLE thread_creation_operations (
    idempotency_key TEXT PRIMARY KEY NOT NULL,
    parameters_sha256 TEXT NOT NULL CHECK(length(parameters_sha256) = 64),
    thread_id TEXT NOT NULL UNIQUE,
    project_id TEXT,
    cwd TEXT NOT NULL,
    thread_source TEXT NOT NULL,
    rollout_path TEXT,
    receipt_json TEXT,
    phase TEXT NOT NULL DEFAULT 'pending' CHECK(phase IN ('pending', 'created', 'deleted', 'abandoned')),
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX thread_creation_pending ON thread_creation_operations(phase);

-- Late rollout backfill must not resurrect a deleted or abandoned creation.
CREATE TRIGGER thread_creation_deleted_insert
BEFORE INSERT ON threads
WHEN EXISTS (SELECT 1 FROM thread_creation_operations WHERE thread_id = NEW.id AND phase IN ('deleted', 'abandoned'))
BEGIN SELECT RAISE(ABORT, 'identified creation was permanently terminated'); END;
CREATE TRIGGER thread_creation_deleted_update
BEFORE UPDATE ON threads
WHEN EXISTS (SELECT 1 FROM thread_creation_operations WHERE thread_id = NEW.id AND phase IN ('deleted', 'abandoned'))
BEGIN SELECT RAISE(ABORT, 'identified creation was permanently terminated'); END;
