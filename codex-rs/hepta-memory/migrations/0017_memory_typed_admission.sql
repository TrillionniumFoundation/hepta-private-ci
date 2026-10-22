-- Preserve every legacy row as Fact without rewriting content or ancestry.
-- All three columns inherit the existing immutable revision triggers.
ALTER TABLE memory_revisions ADD COLUMN memory_kind TEXT NOT NULL DEFAULT 'fact'
    CHECK (memory_kind IN ('episode', 'fact', 'preference', 'procedure'));
ALTER TABLE memory_revisions ADD COLUMN typed_admission_sha256 TEXT
    CHECK (typed_admission_sha256 IS NULL OR
        (length(typed_admission_sha256) = 64 AND typed_admission_sha256 NOT GLOB '*[^0-9a-f]*'));
ALTER TABLE memory_revisions ADD COLUMN typed_admission_json TEXT
    CHECK ((typed_admission_json IS NULL AND typed_admission_sha256 IS NULL AND memory_kind = 'fact') OR
           (typed_admission_json IS NOT NULL AND typed_admission_sha256 IS NOT NULL AND
            length(CAST(typed_admission_json AS BLOB)) BETWEEN 1 AND 16384));

CREATE TRIGGER memory_revisions_kind_predecessor
BEFORE INSERT ON memory_revisions
WHEN NEW.supersedes_revision IS NOT NULL AND EXISTS (
    SELECT 1 FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.supersedes_revision
      AND r.memory_kind != NEW.memory_kind
) BEGIN
    SELECT RAISE(ABORT, 'memory kind cannot change across revisions');
END;
