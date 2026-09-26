-- Immutable local witness of external monotonic frontier admissions.
-- The external backend remains authoritative; this history prevents an already
-- accepted generation from being silently replaced inside a live database.
CREATE TABLE evidence_frontier_acceptance (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    frontier_generation BLOB NOT NULL CHECK (length(frontier_generation) = 8),
    frontier_sha256 TEXT NOT NULL CHECK (
        length(frontier_sha256) = 64
        AND frontier_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    backend_identity_sha256 TEXT NOT NULL CHECK (
        length(backend_identity_sha256) = 64
        AND backend_identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    accepted_at_ms BLOB NOT NULL CHECK (length(accepted_at_ms) = 8),
    UNIQUE(store_id, frontier_generation),
    FOREIGN KEY(store_id)
        REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX evidence_frontier_acceptance_store_seq
    ON evidence_frontier_acceptance(store_id, seq DESC);

CREATE TRIGGER evidence_frontier_acceptance_no_update
BEFORE UPDATE ON evidence_frontier_acceptance
BEGIN
    SELECT RAISE(ABORT, 'accepted evidence frontier is immutable');
END;

CREATE TRIGGER evidence_frontier_acceptance_no_delete
BEFORE DELETE ON evidence_frontier_acceptance
BEGIN
    SELECT RAISE(ABORT, 'accepted evidence frontier is immutable');
END;
