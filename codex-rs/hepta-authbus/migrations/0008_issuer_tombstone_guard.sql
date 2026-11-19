-- The crypto-profile table rebuild preserves issuer rows but replaces the
-- table that owned migration 0005's deletion guard. Restore that exact
-- tombstone rule without editing either historical migration checksum.
CREATE TRIGGER authbus_issuer_delete_forbidden
BEFORE DELETE ON authbus_issuer_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus issuer tombstones cannot be deleted');
END;
