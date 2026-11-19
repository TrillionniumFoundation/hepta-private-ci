-- Preserve signed v1 rows and their replay/fence state; v2 has one exact
-- signature width. A trusted profile, never signature length, selects the key.
ALTER TABLE authbus_outbox RENAME TO authbus_outbox_v12;
DROP INDEX authbus_outbox_route;
DROP TRIGGER authbus_outbox_immutable;
DROP TRIGGER authbus_outbox_transition;
DROP TRIGGER authbus_outbox_active_no_delete;

CREATE TABLE authbus_outbox (
    delivery_id BLOB PRIMARY KEY CHECK (length(delivery_id) = 32),
    issuer_id TEXT NOT NULL,
    key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8),
    message_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    scope_digest BLOB NOT NULL CHECK (length(scope_digest) = 32),
    payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
    sequence BLOB NOT NULL CHECK (length(sequence) = 8),
    expires_at_ms BLOB NOT NULL CHECK (length(expires_at_ms) = 8),
    auth_version INTEGER NOT NULL CHECK (auth_version IN (1, 2)),
    signature BLOB NOT NULL CHECK (
        (auth_version = 1 AND length(signature) = 64) OR
        (auth_version = 2 AND length(signature) = 3309)),
    payload BLOB NOT NULL CHECK (length(payload) <= 16384),
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'acked', 'expired', 'quarantined')),
    fence INTEGER NOT NULL CHECK (fence >= 0),
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 0 AND 16),
    worker_id TEXT,
    lease_until_ms INTEGER,
    available_at_ms INTEGER NOT NULL CHECK (available_at_ms >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    terminal_at_ms INTEGER,
    acknowledgement BLOB CHECK (length(acknowledgement) = 32),
    UNIQUE (issuer_id, key_epoch, message_id),
    CHECK ((state = 'leased' AND worker_id IS NOT NULL AND lease_until_ms IS NOT NULL AND lease_until_ms > updated_at_ms)
        OR (state != 'leased' AND worker_id IS NULL AND lease_until_ms IS NULL)),
    CHECK ((state IN ('queued', 'leased') AND terminal_at_ms IS NULL)
        OR (state IN ('acked', 'expired', 'quarantined') AND terminal_at_ms IS NOT NULL AND terminal_at_ms = updated_at_ms)),
    CHECK ((state = 'acked' AND acknowledgement IS NOT NULL)
        OR (state != 'acked' AND acknowledgement IS NULL))
) WITHOUT ROWID;

INSERT INTO authbus_outbox (delivery_id, issuer_id, key_epoch, message_id, subject_id, scope_digest, payload_digest, sequence, expires_at_ms, signature, payload, state, fence, attempts, worker_id, lease_until_ms, available_at_ms, created_at_ms, updated_at_ms, terminal_at_ms, acknowledgement, auth_version)
SELECT delivery_id, issuer_id, key_epoch, message_id, subject_id, scope_digest, payload_digest, sequence, expires_at_ms, signature, payload, state, fence, attempts, worker_id, lease_until_ms, available_at_ms, created_at_ms, updated_at_ms, terminal_at_ms, acknowledgement, 1 FROM authbus_outbox_v12;
DROP TABLE authbus_outbox_v12;

CREATE INDEX authbus_outbox_route ON authbus_outbox
    (subject_id, scope_digest, state, available_at_ms, delivery_id);

CREATE TRIGGER authbus_outbox_immutable BEFORE UPDATE OF
    delivery_id, issuer_id, key_epoch, message_id, subject_id, scope_digest,
    payload_digest, sequence, expires_at_ms, auth_version, signature, payload, created_at_ms
    ON authbus_outbox
BEGIN
    SELECT RAISE(ABORT, 'AuthBus message content is immutable');
END;

CREATE TRIGGER authbus_outbox_transition BEFORE UPDATE ON authbus_outbox
WHEN OLD.state IN ('acked', 'expired', 'quarantined')
    OR NEW.fence != OLD.fence + 1 OR NEW.updated_at_ms < OLD.updated_at_ms
    OR NEW.attempts < OLD.attempts
    OR (NEW.attempts != OLD.attempts AND NOT
        (NEW.state = 'leased' AND NEW.attempts = OLD.attempts + 1))
BEGIN
    SELECT RAISE(ABORT, 'invalid AuthBus ownership transition');
END;

CREATE TRIGGER authbus_outbox_active_no_delete BEFORE DELETE ON authbus_outbox
WHEN OLD.state IN ('queued', 'leased')
BEGIN
    SELECT RAISE(ABORT, 'active AuthBus messages cannot be pruned');
END;

CREATE TABLE authbus_crypto_profile (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    auth_version INTEGER NOT NULL CHECK (auth_version IN (1, 2))
) WITHOUT ROWID;
INSERT INTO authbus_crypto_profile(singleton, auth_version)
SELECT 1, 1 WHERE
    EXISTS(SELECT 1 FROM authbus_replay_sequences) OR
    EXISTS(SELECT 1 FROM authbus_outbox) OR
    EXISTS(SELECT 1 FROM authbus_retired_epochs) OR
    EXISTS(SELECT 1 FROM authbus_restore_checkpoint);
CREATE TRIGGER authbus_profile_immutable BEFORE UPDATE ON authbus_crypto_profile
BEGIN SELECT RAISE(ABORT, 'AuthBus cryptographic profile is immutable'); END;
CREATE TRIGGER authbus_profile_no_delete BEFORE DELETE ON authbus_crypto_profile
BEGIN SELECT RAISE(ABORT, 'AuthBus cryptographic profile cannot be deleted'); END;
