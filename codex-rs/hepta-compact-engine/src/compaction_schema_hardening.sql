-- Schema hardening applied after the reviewed V1 schema on every open.
--
-- SQLite three-valued logic makes `NULL != value` evaluate to NULL. The prior
-- trigger therefore allowed a caller to advance the generation while writing a
-- NULL predecessor. `IS NOT` is NULL-safe and closes that CAS bypass.
DROP TRIGGER IF EXISTS active_compaction_checkpoint_monotonic;
CREATE TRIGGER active_compaction_checkpoint_monotonic
BEFORE UPDATE ON active_compaction_checkpoint
WHEN NEW.generation != OLD.generation + 1
  OR NEW.predecessor_checkpoint_digest IS NOT OLD.checkpoint_digest
BEGIN
    SELECT RAISE(ABORT, 'active compaction checkpoint CAS is not monotonic');
END;
