-- Random-capability fencing and append-only per-attempt evidence for Matrix
-- outbound effects. The existing outbox remains the scheduling queue and the
-- dispatch ledger remains terminal truth; these tables make every physical
-- attempt independently auditable and prevent a stale lease holder from
-- mutating the active attempt.
CREATE TABLE matrix_dispatch_attempt_claims (
    stable_txn_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_token_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(claim_token_sha256) = 64
        AND claim_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claimed_at_ms INTEGER NOT NULL CHECK (claimed_at_ms >= 0),
    lease_until_ms INTEGER NOT NULL CHECK (lease_until_ms > claimed_at_ms),
    PRIMARY KEY (stable_txn_id, attempt),
    UNIQUE (stable_txn_id, attempt, lease_epoch, claim_token_sha256),
    FOREIGN KEY (stable_txn_id) REFERENCES outbox_messages(stable_txn_id)
        ON DELETE RESTRICT,
    CHECK (lease_epoch = attempt)
) STRICT;

CREATE INDEX matrix_dispatch_attempt_claims_by_token
ON matrix_dispatch_attempt_claims(claim_token_sha256);

CREATE TRIGGER matrix_dispatch_attempt_claims_no_update
BEFORE UPDATE ON matrix_dispatch_attempt_claims BEGIN
    SELECT RAISE(ABORT, 'Matrix attempt claim identity is immutable');
END;

CREATE TRIGGER matrix_dispatch_attempt_claims_no_delete
BEFORE DELETE ON matrix_dispatch_attempt_claims BEGIN
    SELECT RAISE(ABORT, 'Matrix attempt claim identity is durable');
END;

CREATE TABLE matrix_dispatch_active_claims (
    stable_txn_id TEXT PRIMARY KEY,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_token_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(claim_token_sha256) = 64
        AND claim_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    phase TEXT NOT NULL CHECK (phase IN ('claimed', 'authorized', 'dispatching')),
    claimed_at_ms INTEGER NOT NULL CHECK (claimed_at_ms >= 0),
    lease_until_ms INTEGER NOT NULL CHECK (lease_until_ms > claimed_at_ms),
    FOREIGN KEY (stable_txn_id, attempt, lease_epoch, claim_token_sha256)
        REFERENCES matrix_dispatch_attempt_claims(
            stable_txn_id, attempt, lease_epoch, claim_token_sha256
        ) ON DELETE RESTRICT,
    CHECK (lease_epoch = attempt)
) STRICT;

CREATE INDEX matrix_dispatch_active_claims_by_lease
ON matrix_dispatch_active_claims(lease_until_ms, stable_txn_id);

CREATE TRIGGER matrix_dispatch_active_claim_identity_immutable
BEFORE UPDATE OF stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                 claimed_at_ms, lease_until_ms
ON matrix_dispatch_active_claims BEGIN
    SELECT RAISE(ABORT, 'Matrix active claim identity is immutable');
END;

CREATE TABLE matrix_dispatch_authority_witnesses (
    stable_txn_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_token_sha256 TEXT NOT NULL CHECK (
        length(claim_token_sha256) = 64
        AND claim_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    revocation_revision INTEGER NOT NULL CHECK (revocation_revision > 0),
    grant_id TEXT NOT NULL CHECK (
        length(grant_id) BETWEEN 1 AND 128
        AND grant_id NOT GLOB '*[^A-Za-z0-9_.:/-]*'
    ),
    verified_use_witness_sha256 TEXT NOT NULL CHECK (
        length(verified_use_witness_sha256) = 64
        AND verified_use_witness_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    revocation_head_sha256 TEXT NOT NULL CHECK (
        length(revocation_head_sha256) = 64
        AND revocation_head_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (stable_txn_id, attempt),
    FOREIGN KEY (stable_txn_id, attempt, lease_epoch, claim_token_sha256)
        REFERENCES matrix_dispatch_attempt_claims(
            stable_txn_id, attempt, lease_epoch, claim_token_sha256
        ) ON DELETE RESTRICT,
    CHECK (lease_epoch = attempt)
) STRICT;

CREATE TRIGGER matrix_dispatch_authority_witnesses_no_update
BEFORE UPDATE ON matrix_dispatch_authority_witnesses BEGIN
    SELECT RAISE(ABORT, 'Matrix authority witness is immutable');
END;

CREATE TRIGGER matrix_dispatch_authority_witnesses_no_delete
BEFORE DELETE ON matrix_dispatch_authority_witnesses BEGIN
    SELECT RAISE(ABORT, 'Matrix authority witness is durable');
END;

CREATE TABLE matrix_dispatch_attempt_events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_txn_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_token_sha256 TEXT NOT NULL CHECK (
        length(claim_token_sha256) = 64
        AND claim_token_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'claimed', 'prepared', 'authorized', 'dispatching',
        'transport_accepted', 'indeterminate', 'retry_scheduled',
        'confirmed', 'redacted', 'permanently_rejected',
        'revoked', 'canceled', 'expired'
    )),
    failure_class TEXT CHECK (failure_class IS NULL OR failure_class IN (
        'retryable', 'rate_limited', 'dns', 'tls', 'connect_timeout',
        'connect_failure', 'read_timeout', 'connection_reset',
        'response_lost', 'server_unavailable', 'permanent',
        'authority_denied'
    )),
    retry_after_ms INTEGER CHECK (retry_after_ms IS NULL OR retry_after_ms >= 0),
    event_id TEXT,
    detail_sha256 TEXT CHECK (
        detail_sha256 IS NULL OR (
            length(detail_sha256) = 64
            AND detail_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    FOREIGN KEY (stable_txn_id, attempt, lease_epoch, claim_token_sha256)
        REFERENCES matrix_dispatch_attempt_claims(
            stable_txn_id, attempt, lease_epoch, claim_token_sha256
        ) ON DELETE RESTRICT,
    CHECK (lease_epoch = attempt),
    UNIQUE (
        stable_txn_id, attempt, claim_token_sha256, event_kind,
        recorded_at_ms, detail_sha256
    )
) STRICT;

CREATE INDEX matrix_dispatch_attempt_events_by_txn
ON matrix_dispatch_attempt_events(stable_txn_id, event_seq);

CREATE TRIGGER matrix_dispatch_attempt_events_no_update
BEFORE UPDATE ON matrix_dispatch_attempt_events BEGIN
    SELECT RAISE(ABORT, 'Matrix attempt history is append-only');
END;

CREATE TRIGGER matrix_dispatch_attempt_events_no_delete
BEFORE DELETE ON matrix_dispatch_attempt_events BEGIN
    SELECT RAISE(ABORT, 'Matrix attempt history is durable');
END;

-- Trusted homeserver observations are the only source of Confirmed and
-- Redacted terminal events. These triggers bind that terminal observation to
-- the exact random claim identity used by the accepted attempt.
CREATE TRIGGER matrix_dispatch_attempt_confirmed
AFTER UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'succeeded' AND OLD.state != 'succeeded'
BEGIN
    INSERT INTO matrix_dispatch_attempt_events (
        stable_txn_id, attempt, lease_epoch, claim_token_sha256,
        event_kind, failure_class, retry_after_ms, event_id,
        detail_sha256, recorded_at_ms
    )
    SELECT NEW.stable_txn_id, claim.attempt, claim.lease_epoch,
           claim.claim_token_sha256, 'confirmed', NULL, NULL,
           NEW.terminal_event_id, NEW.send_observation_sha256,
           NEW.terminal_observed_at_ms
    FROM matrix_dispatch_attempt_claims AS claim
    WHERE claim.stable_txn_id = NEW.stable_txn_id
      AND claim.attempt = NEW.attempts;
    DELETE FROM matrix_dispatch_active_claims
    WHERE stable_txn_id = NEW.stable_txn_id AND attempt = NEW.attempts;
END;

CREATE TRIGGER matrix_dispatch_attempt_redacted
AFTER UPDATE OF state ON matrix_dispatch_ledger
WHEN NEW.state = 'redacted' AND OLD.state != 'redacted'
BEGIN
    INSERT INTO matrix_dispatch_attempt_events (
        stable_txn_id, attempt, lease_epoch, claim_token_sha256,
        event_kind, failure_class, retry_after_ms, event_id,
        detail_sha256, recorded_at_ms
    )
    SELECT NEW.stable_txn_id, claim.attempt, claim.lease_epoch,
           claim.claim_token_sha256, 'redacted', NULL, NULL,
           NEW.terminal_event_id, NEW.redaction_observation_sha256,
           NEW.terminal_observed_at_ms
    FROM matrix_dispatch_attempt_claims AS claim
    WHERE claim.stable_txn_id = NEW.stable_txn_id
      AND claim.attempt = NEW.attempts;
    DELETE FROM matrix_dispatch_active_claims
    WHERE stable_txn_id = NEW.stable_txn_id AND attempt = NEW.attempts;
END;
