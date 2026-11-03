-- A trusted owner chooses one immutable authority profile. Existing authority
-- state remains explicitly classical; changing profile requires a new domain.
CREATE TABLE authbus_crypto_profile (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    auth_version INTEGER NOT NULL CHECK (auth_version IN (1, 2))
) WITHOUT ROWID;
INSERT INTO authbus_crypto_profile(singleton, auth_version)
SELECT 1, 1 WHERE
    EXISTS(SELECT 1 FROM authbus_issuer_registry) OR
    EXISTS(SELECT 1 FROM authbus_trusted_time) OR
    EXISTS(SELECT 1 FROM authbus_policy_history) OR
    EXISTS(SELECT 1 FROM authbus_quota_registry) OR
    EXISTS(SELECT 1 FROM authbus_authority_checkpoint);
CREATE TRIGGER authbus_profile_immutable BEFORE UPDATE ON authbus_crypto_profile
BEGIN SELECT RAISE(ABORT, 'AuthBus authority profile is immutable'); END;
CREATE TRIGGER authbus_profile_no_delete BEFORE DELETE ON authbus_crypto_profile
BEGIN SELECT RAISE(ABORT, 'AuthBus authority profile cannot be deleted'); END;

ALTER TABLE authbus_issuer_registry RENAME TO authbus_issuer_registry_v4;
DROP INDEX authbus_one_active_issuer_epoch;
DROP TRIGGER authbus_dirty_issuer_insert;
DROP TRIGGER authbus_dirty_issuer_update;
CREATE TABLE authbus_issuer_registry (
    issuer_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('message', 'settlement', 'trusted_time')),
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    auth_version INTEGER NOT NULL CHECK (auth_version IN (1, 2)),
    public_key BLOB NOT NULL CHECK (
        (auth_version = 1 AND length(public_key) = 32) OR
        (auth_version = 2 AND length(public_key) = 1974)),
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked', 'retired')),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    PRIMARY KEY (issuer_id, purpose, key_epoch)
) WITHOUT ROWID;
INSERT INTO authbus_issuer_registry
SELECT issuer_id, purpose, key_epoch, 1, public_key, state, revision
FROM authbus_issuer_registry_v4;
DROP TABLE authbus_issuer_registry_v4;
CREATE UNIQUE INDEX authbus_one_active_issuer_epoch
    ON authbus_issuer_registry(issuer_id, purpose) WHERE state = 'active';
CREATE TRIGGER authbus_issuer_profile BEFORE INSERT ON authbus_issuer_registry
WHEN NEW.auth_version IS NOT
    (SELECT auth_version FROM authbus_crypto_profile WHERE singleton = 1)
BEGIN SELECT RAISE(ABORT, 'AuthBus issuer profile mismatch'); END;
CREATE TRIGGER authbus_issuer_identity_immutable BEFORE UPDATE OF
    issuer_id, purpose, key_epoch, auth_version, public_key ON authbus_issuer_registry
BEGIN SELECT RAISE(ABORT, 'AuthBus issuer identity is immutable'); END;
CREATE TRIGGER authbus_dirty_issuer_insert AFTER INSERT ON authbus_issuer_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
CREATE TRIGGER authbus_dirty_issuer_update AFTER UPDATE ON authbus_issuer_registry
BEGIN UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1; END;
