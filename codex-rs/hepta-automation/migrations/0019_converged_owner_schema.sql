-- Converge the causal-occurrence and timer/dedupe branches without dropping
-- either owner's data. The displaced migrations retain their original SQL and
-- checksums at versions 17/18; the loader explicitly remaps only those known
-- legacy version/checksum pairs before normal SQLx migration validation.
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 19 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
