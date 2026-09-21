PRAGMA foreign_keys = ON;

CREATE TABLE operation_records (
    operation_id TEXT PRIMARY KEY NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    owner_generation INTEGER NOT NULL CHECK(owner_generation > 0),
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL CHECK(state IN ('pending','authorized','dispatched','indeterminate','applied','not_applied','quarantined')),
    authorization_digest TEXT,
    authority_generation INTEGER,
    dispatch_digest TEXT,
    reason_digest TEXT,
    outcome_digest TEXT
) STRICT;

CREATE TABLE operation_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL REFERENCES operation_records(operation_id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL,
    authorization_digest TEXT,
    authority_generation INTEGER,
    dispatch_digest TEXT,
    reason_digest TEXT,
    outcome_digest TEXT,
    UNIQUE(operation_id, revision)
) STRICT;

CREATE TRIGGER operation_events_no_update BEFORE UPDATE ON operation_events BEGIN
    SELECT RAISE(ABORT, 'operation events are immutable');
END;
CREATE TRIGGER operation_events_no_delete BEFORE DELETE ON operation_events BEGIN
    SELECT RAISE(ABORT, 'operation events are immutable');
END;

CREATE TABLE operation_outbox (
    intent_id TEXT PRIMARY KEY NOT NULL,
    operation_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK(length(payload_digest) = 64),
    state TEXT NOT NULL CHECK(state IN ('pending','claimed','acknowledged')),
    claim_owner TEXT,
    claim_generation INTEGER,
    lease_expires_at_ms INTEGER,
    acknowledgement_digest TEXT,
    revision INTEGER NOT NULL CHECK(revision > 0)
) STRICT;

CREATE TABLE operation_outbox_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL REFERENCES operation_outbox(intent_id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL,
    claim_owner TEXT,
    claim_generation INTEGER,
    lease_expires_at_ms INTEGER,
    acknowledgement_digest TEXT,
    UNIQUE(intent_id, revision)
) STRICT;

CREATE TRIGGER operation_outbox_events_no_update BEFORE UPDATE ON operation_outbox_events BEGIN
    SELECT RAISE(ABORT, 'operation outbox events are immutable');
END;
CREATE TRIGGER operation_outbox_events_no_delete BEFORE DELETE ON operation_outbox_events BEGIN
    SELECT RAISE(ABORT, 'operation outbox events are immutable');
END;
