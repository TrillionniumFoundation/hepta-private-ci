-- Owner-local observation progress. This cannot create or change admissions.
CREATE TABLE matrix_turn_recovery (
    event_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL CHECK (length(thread_id) > 0),
    turn_id TEXT NOT NULL CHECK (length(turn_id) > 0),
    cursor TEXT NOT NULL CHECK (length(cursor) > 0 AND length(cursor) <= 4096),
    FOREIGN KEY (event_id) REFERENCES inbox_dispatches(event_id) ON DELETE RESTRICT
) STRICT;
