-- Historical authority rows are evidence, not mutable projections.  Prevent a
-- direct SQL caller from rewriting or deleting lineage after the owner commits
-- it.  The schema verifier requires these exact triggers on every reopen.
CREATE TRIGGER authbus_policy_history_immutable_update
BEFORE UPDATE ON authbus_policy_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy history is immutable');
END;
CREATE TRIGGER authbus_policy_history_immutable_delete
BEFORE DELETE ON authbus_policy_history
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy history is immutable');
END;

CREATE TRIGGER authbus_policy_archive_immutable_update
BEFORE UPDATE ON authbus_policy_archive
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy archive is immutable');
END;
CREATE TRIGGER authbus_policy_archive_immutable_delete
BEFORE DELETE ON authbus_policy_archive
BEGIN
    SELECT RAISE(ABORT, 'AuthBus policy archive is immutable');
END;

CREATE TRIGGER authbus_reservation_archive_immutable_update
BEFORE UPDATE ON authbus_quota_reservation_archive
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation archive is immutable');
END;
CREATE TRIGGER authbus_reservation_archive_immutable_delete
BEFORE DELETE ON authbus_quota_reservation_archive
BEGIN
    SELECT RAISE(ABORT, 'AuthBus reservation archive is immutable');
END;

-- Complete the dirty frontier for destructive mutations even though normal
-- owner APIs do not expose them.  A future reviewed migration may add such an
-- operation without silently escaping checkpoint publication.
CREATE TRIGGER authbus_dirty_quota_delete AFTER DELETE ON authbus_quota_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_issuer_delete AFTER DELETE ON authbus_issuer_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
