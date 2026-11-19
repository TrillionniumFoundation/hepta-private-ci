-- Authority history and archives are append-only evidence. Direct SQL callers
-- must not rewrite or delete retained identity, settlement, or policy history.

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

CREATE TRIGGER authbus_issuer_delete_forbidden
BEFORE DELETE ON authbus_issuer_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus issuer tombstones cannot be deleted');
END;

CREATE TRIGGER authbus_quota_delete_forbidden
BEFORE DELETE ON authbus_quota_registry
BEGIN
    SELECT RAISE(ABORT, 'AuthBus quota identity cannot be deleted');
END;

CREATE TRIGGER authbus_trusted_time_delete_forbidden
BEFORE DELETE ON authbus_trusted_time
BEGIN
    SELECT RAISE(ABORT, 'AuthBus trusted time cannot be deleted');
END;
