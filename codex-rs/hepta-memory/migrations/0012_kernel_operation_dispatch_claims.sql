-- Durable per-operation outbox claim leases.
--
-- Claims are append-only operational fencing records. A claim lease may be
-- renewed by the same generation before expiry or taken over by a strictly
-- newer owner generation only after expiry plus the recorded retry backoff.
-- Once a claim is marked entered, the external boundary may have been crossed
-- and no later claim may authorize a resend; only reconciliation may settle it.

CREATE TABLE cognitive_operation_dispatch_claims (
    operation_id TEXT NOT NULL,
    claim_sequence INTEGER NOT NULL CHECK (claim_sequence > 0),
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 64),
    owner_generation INTEGER NOT NULL CHECK (owner_generation > 0),
    fencing_token TEXT NOT NULL CHECK (
        length(trim(fencing_token)) BETWEEN 1 AND 256 AND
        instr(fencing_token, char(0)) = 0
    ),
    claim_state TEXT NOT NULL CHECK (
        claim_state IN ('claimed', 'renewed', 'entered', 'settled')
    ),
    lease_expires_at_unix_ms INTEGER NOT NULL CHECK (lease_expires_at_unix_ms > 0),
    next_eligible_at_unix_ms INTEGER NOT NULL CHECK (next_eligible_at_unix_ms > 0),
    previous_sha256 TEXT NOT NULL CHECK (
        length(previous_sha256) = 64 AND previous_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claim_sha256 TEXT NOT NULL CHECK (
        length(claim_sha256) = 64 AND claim_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_ms INTEGER NOT NULL CHECK (recorded_at_unix_ms > 0),
    PRIMARY KEY (operation_id, claim_sequence),
    UNIQUE (operation_id, claim_sha256),
    FOREIGN KEY (operation_id)
        REFERENCES cognitive_operation_ledger(operation_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER cognitive_operation_dispatch_claims_no_update
BEFORE UPDATE ON cognitive_operation_dispatch_claims BEGIN
    SELECT RAISE(ABORT, 'operation dispatch claim journal is immutable');
END;

CREATE TRIGGER cognitive_operation_dispatch_claims_no_delete
BEFORE DELETE ON cognitive_operation_dispatch_claims BEGIN
    SELECT RAISE(ABORT, 'operation dispatch claim journal is immutable');
END;

CREATE INDEX cognitive_operation_dispatch_claims_active_lookup
ON cognitive_operation_dispatch_claims(
    operation_id, claim_sequence, claim_state, owner_generation
);

CREATE INDEX cognitive_operation_dispatch_claims_expiry_lookup
ON cognitive_operation_dispatch_claims(
    lease_expires_at_unix_ms, next_eligible_at_unix_ms, operation_id
);
