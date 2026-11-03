-- An internal witness from the original writer's synchronous FinalUse error
-- branch. This is not a destination receipt and cannot settle an unknown D.
-- The existing operation, outbox, event and claim journals remain unchanged.
CREATE TABLE cognitive_operation_pre_boundary_rejections (
    operation_id TEXT NOT NULL,
    entered_claim_sha256 TEXT NOT NULL,
    settled_claim_sha256 TEXT NOT NULL,
    dispatch_event_id TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    proof_json TEXT NOT NULL CHECK (
        length(proof_json) BETWEEN 1 AND 8192 AND json_valid(proof_json)
    ),
    proof_sha256 TEXT NOT NULL CHECK (
        length(proof_sha256) = 64 AND proof_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_unix_ms INTEGER NOT NULL CHECK (recorded_at_unix_ms > 0),
    PRIMARY KEY (operation_id, entered_claim_sha256),
    UNIQUE (operation_id, settled_claim_sha256),
    FOREIGN KEY (operation_id, entered_claim_sha256)
        REFERENCES cognitive_operation_dispatch_claims(operation_id, claim_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id, settled_claim_sha256)
        REFERENCES cognitive_operation_dispatch_claims(operation_id, claim_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (lease_id, dispatch_event_id)
        REFERENCES cognitive_local_events(lease_id, event_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER cognitive_operation_pre_boundary_rejections_no_update
BEFORE UPDATE ON cognitive_operation_pre_boundary_rejections BEGIN
    SELECT RAISE(ABORT, 'pre-boundary rejection proofs are immutable');
END;

CREATE TRIGGER cognitive_operation_pre_boundary_rejections_no_delete
BEFORE DELETE ON cognitive_operation_pre_boundary_rejections BEGIN
    SELECT RAISE(ABORT, 'pre-boundary rejection proofs are immutable');
END;

-- Canonical HOS2 payloads preserve the complete unsigned D as JSON values.
-- Uniqueness belongs to this same database transaction, across all leases/K.
CREATE UNIQUE INDEX cognitive_local_outbox_hos2_delivery
ON cognitive_local_outbox(
    json_extract(payload_json, '$.delivery.boot_id'),
    json_extract(payload_json, '$.delivery.space_id'),
    json_extract(payload_json, '$.delivery.sequence')
)
WHERE topic = 'hepta.hos2.install-budget.v1';
