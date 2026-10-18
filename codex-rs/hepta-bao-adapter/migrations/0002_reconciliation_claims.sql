-- Cross-process, time-bounded reconciliation claims. These fields are
-- operational coordination state: they are intentionally excluded from the
-- authoritative owner checkpoint so worker crashes cannot alter durable facts.

ALTER TABLE bao_reconciliation_queue
    ADD COLUMN claim_owner TEXT;
ALTER TABLE bao_reconciliation_queue
    ADD COLUMN claim_until_unix_ms BLOB
        CHECK (claim_until_unix_ms IS NULL OR length(claim_until_unix_ms) = 8);
ALTER TABLE bao_reconciliation_queue
    ADD COLUMN claim_generation BLOB NOT NULL
        DEFAULT X'0000000000000000'
        CHECK (length(claim_generation) = 8);

DROP INDEX bao_reconciliation_due;
CREATE INDEX bao_reconciliation_due
    ON bao_reconciliation_queue(
        next_attempt_at_unix_ms,
        attempt_count,
        operation_id
    );
CREATE INDEX bao_reconciliation_claim_expiry
    ON bao_reconciliation_queue(claim_until_unix_ms, operation_id)
    WHERE claim_owner IS NOT NULL;

-- Rebuild the singleton metadata table so the schema version remains an
-- exact checked value rather than a mutable range.
DROP TRIGGER bao_owner_meta_no_insert;
DROP TRIGGER bao_owner_meta_no_delete;
DROP TRIGGER bao_owner_meta_monotonic;
ALTER TABLE bao_owner_meta RENAME TO bao_owner_meta_v1;

CREATE TABLE bao_owner_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 2),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    time_frontier_unix_ms BLOB NOT NULL CHECK (length(time_frontier_unix_ms) = 8)
) STRICT;

INSERT INTO bao_owner_meta(singleton, schema_version, revision, time_frontier_unix_ms)
SELECT singleton, 2, revision, time_frontier_unix_ms FROM bao_owner_meta_v1;
DROP TABLE bao_owner_meta_v1;

CREATE TRIGGER bao_owner_meta_no_insert
BEFORE INSERT ON bao_owner_meta
WHEN EXISTS(SELECT 1 FROM bao_owner_meta WHERE singleton = 1)
BEGIN
    SELECT RAISE(ABORT, 'Bao owner meta is a singleton');
END;

CREATE TRIGGER bao_owner_meta_no_delete
BEFORE DELETE ON bao_owner_meta
BEGIN
    SELECT RAISE(ABORT, 'Bao owner meta cannot be deleted');
END;

CREATE TRIGGER bao_owner_meta_monotonic
BEFORE UPDATE ON bao_owner_meta
WHEN NEW.singleton != OLD.singleton
  OR NEW.schema_version != OLD.schema_version
  OR NEW.revision < OLD.revision
  OR NEW.time_frontier_unix_ms < OLD.time_frontier_unix_ms
BEGIN
    SELECT RAISE(ABORT, 'Bao owner frontier cannot move backwards');
END;

CREATE TABLE bao_reference_import (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    source_schema_version INTEGER NOT NULL CHECK (source_schema_version = 4),
    source_revision BLOB NOT NULL CHECK (length(source_revision) = 8),
    source_time_frontier_unix_ms BLOB NOT NULL CHECK (length(source_time_frontier_unix_ms) = 8),
    source_sha256 BLOB NOT NULL CHECK (length(source_sha256) = 32),
    imported_at_unix_ms BLOB NOT NULL CHECK (length(imported_at_unix_ms) = 8)
) STRICT;

CREATE TRIGGER bao_reference_import_no_update
BEFORE UPDATE ON bao_reference_import
BEGIN
    SELECT RAISE(ABORT, 'Bao reference import receipt is immutable');
END;

CREATE TRIGGER bao_reference_import_no_delete
BEFORE DELETE ON bao_reference_import
BEGIN
    SELECT RAISE(ABORT, 'Bao reference import receipt cannot be deleted');
END;
