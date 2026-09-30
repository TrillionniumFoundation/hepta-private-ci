-- Durable, one-transition repair authorization ledger for kernel.evidence.
--
-- This schema is deliberately separate from ordinary frontier publication.
-- Normal compare-and-swap never reads or consumes these rows. A repair caller
-- must first persist one exact signed current -> target transition and one
-- globally unique authority nonce, then carry the same dispatch token through
-- an observed terminal acknowledgement or conflict.

CREATE TABLE evidence_frontier_repairs (
    repair_id TEXT PRIMARY KEY CHECK (
        length(repair_id) BETWEEN 1 AND 128
        AND repair_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    store_id TEXT NOT NULL CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    state TEXT NOT NULL CHECK (state IN (
        'prepared', 'dispatching', 'indeterminate', 'acknowledged', 'conflicted'
    )),
    nonce_hex TEXT NOT NULL CHECK (
        length(nonce_hex) = 64 AND nonce_hex NOT GLOB '*[^0-9a-f]*'
    ),
    operator_principal_id TEXT NOT NULL CHECK (
        length(operator_principal_id) BETWEEN 1 AND 128
        AND operator_principal_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'backend_migration', 'store_recovery', 'trust_root_rotation',
        'schema_migration', 'operator_disaster_recovery'
    )),
    authority_key_id TEXT NOT NULL CHECK (
        length(authority_key_id) BETWEEN 1 AND 128
        AND authority_key_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    authority_key_epoch INTEGER NOT NULL CHECK (authority_key_epoch > 0),
    trust_root_generation INTEGER NOT NULL CHECK (trust_root_generation > 0),
    current_generation INTEGER NOT NULL CHECK (current_generation > 0),
    target_generation INTEGER NOT NULL CHECK (target_generation > current_generation),
    current_frontier_sha256 TEXT NOT NULL CHECK (
        length(current_frontier_sha256) = 64
        AND current_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    target_frontier_sha256 TEXT NOT NULL CHECK (
        length(target_frontier_sha256) = 64
        AND target_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    current_frontier_json TEXT NOT NULL CHECK (
        json_valid(current_frontier_json)
        AND length(CAST(current_frontier_json AS BLOB)) <= 524288
    ),
    current_frontier_json_sha256 TEXT NOT NULL CHECK (
        length(current_frontier_json_sha256) = 64
        AND current_frontier_json_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    target_frontier_json TEXT NOT NULL CHECK (
        json_valid(target_frontier_json)
        AND length(CAST(target_frontier_json AS BLOB)) <= 524288
    ),
    target_frontier_json_sha256 TEXT NOT NULL CHECK (
        length(target_frontier_json_sha256) = 64
        AND target_frontier_json_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authorization_json TEXT NOT NULL CHECK (
        json_valid(authorization_json)
        AND length(CAST(authorization_json AS BLOB)) <= 131072
    ),
    authorization_sha256 TEXT NOT NULL CHECK (
        length(authorization_sha256) = 64
        AND authorization_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority_json TEXT NOT NULL CHECK (
        json_valid(authority_json)
        AND length(CAST(authority_json AS BLOB)) <= 131072
    ),
    authority_sha256 TEXT NOT NULL CHECK (
        length(authority_sha256) = 64
        AND authority_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dispatch_token TEXT CHECK (
        dispatch_token IS NULL OR (
            length(dispatch_token) BETWEEN 1 AND 128
            AND dispatch_token NOT GLOB '*[^A-Za-z0-9._:-]*'
        )
    ),
    backend_identity_sha256 TEXT CHECK (
        backend_identity_sha256 IS NULL OR (
            length(backend_identity_sha256) = 64
            AND backend_identity_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    durable_audit_sequence INTEGER CHECK (
        durable_audit_sequence IS NULL OR durable_audit_sequence > 0
    ),
    conflict_generation INTEGER CHECK (
        conflict_generation IS NULL OR conflict_generation > 0
    ),
    conflict_frontier_sha256 TEXT CHECK (
        conflict_frontier_sha256 IS NULL OR (
            length(conflict_frontier_sha256) = 64
            AND conflict_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    UNIQUE(authority_key_id, authority_key_epoch, nonce_hex),
    CHECK (
        (state = 'prepared'
            AND dispatch_token IS NULL
            AND backend_identity_sha256 IS NULL
            AND durable_audit_sequence IS NULL
            AND conflict_generation IS NULL
            AND conflict_frontier_sha256 IS NULL)
        OR
        (state IN ('dispatching', 'indeterminate')
            AND dispatch_token IS NOT NULL
            AND backend_identity_sha256 IS NOT NULL
            AND durable_audit_sequence IS NULL
            AND conflict_generation IS NULL
            AND conflict_frontier_sha256 IS NULL)
        OR
        (state = 'acknowledged'
            AND dispatch_token IS NOT NULL
            AND backend_identity_sha256 IS NOT NULL
            AND durable_audit_sequence IS NOT NULL
            AND conflict_generation IS NULL
            AND conflict_frontier_sha256 IS NULL)
        OR
        (state = 'conflicted'
            AND dispatch_token IS NOT NULL
            AND backend_identity_sha256 IS NOT NULL
            AND durable_audit_sequence IS NULL
            AND conflict_generation IS NOT NULL
            AND conflict_frontier_sha256 IS NOT NULL)
    ),
    FOREIGN KEY(store_id) REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE UNIQUE INDEX evidence_frontier_repairs_one_open_per_store
    ON evidence_frontier_repairs(store_id)
    WHERE state IN ('prepared', 'dispatching', 'indeterminate');

CREATE INDEX evidence_frontier_repairs_store_created
    ON evidence_frontier_repairs(store_id, created_at_ms, repair_id);

CREATE TRIGGER evidence_frontier_repairs_transition
BEFORE UPDATE ON evidence_frontier_repairs
WHEN NEW.repair_id != OLD.repair_id
  OR NEW.store_id != OLD.store_id
  OR NEW.nonce_hex != OLD.nonce_hex
  OR NEW.operator_principal_id != OLD.operator_principal_id
  OR NEW.reason_code != OLD.reason_code
  OR NEW.authority_key_id != OLD.authority_key_id
  OR NEW.authority_key_epoch != OLD.authority_key_epoch
  OR NEW.trust_root_generation != OLD.trust_root_generation
  OR NEW.current_generation != OLD.current_generation
  OR NEW.target_generation != OLD.target_generation
  OR NEW.current_frontier_sha256 != OLD.current_frontier_sha256
  OR NEW.target_frontier_sha256 != OLD.target_frontier_sha256
  OR NEW.current_frontier_json != OLD.current_frontier_json
  OR NEW.current_frontier_json_sha256 != OLD.current_frontier_json_sha256
  OR NEW.target_frontier_json != OLD.target_frontier_json
  OR NEW.target_frontier_json_sha256 != OLD.target_frontier_json_sha256
  OR NEW.authorization_json != OLD.authorization_json
  OR NEW.authorization_sha256 != OLD.authorization_sha256
  OR NEW.authority_json != OLD.authority_json
  OR NEW.authority_sha256 != OLD.authority_sha256
  OR NEW.created_at_ms != OLD.created_at_ms
  OR NEW.updated_at_ms < OLD.updated_at_ms
  OR NOT (
      (OLD.state = 'prepared' AND NEW.state = 'dispatching'
          AND OLD.dispatch_token IS NULL
          AND OLD.backend_identity_sha256 IS NULL
          AND NEW.dispatch_token IS NOT NULL
          AND NEW.backend_identity_sha256 IS NOT NULL
          AND NEW.durable_audit_sequence IS NULL
          AND NEW.conflict_generation IS NULL
          AND NEW.conflict_frontier_sha256 IS NULL)
      OR
      (OLD.state = 'dispatching' AND NEW.state = 'indeterminate'
          AND NEW.dispatch_token = OLD.dispatch_token
          AND NEW.backend_identity_sha256 = OLD.backend_identity_sha256
          AND NEW.durable_audit_sequence IS NULL
          AND NEW.conflict_generation IS NULL
          AND NEW.conflict_frontier_sha256 IS NULL)
      OR
      (OLD.state IN ('dispatching', 'indeterminate')
          AND NEW.state = 'acknowledged'
          AND NEW.dispatch_token = OLD.dispatch_token
          AND NEW.backend_identity_sha256 = OLD.backend_identity_sha256
          AND NEW.durable_audit_sequence IS NOT NULL
          AND NEW.conflict_generation IS NULL
          AND NEW.conflict_frontier_sha256 IS NULL)
      OR
      (OLD.state IN ('dispatching', 'indeterminate')
          AND NEW.state = 'conflicted'
          AND NEW.dispatch_token = OLD.dispatch_token
          AND NEW.backend_identity_sha256 = OLD.backend_identity_sha256
          AND NEW.durable_audit_sequence IS NULL
          AND NEW.conflict_generation IS NOT NULL
          AND NEW.conflict_frontier_sha256 IS NOT NULL)
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid evidence frontier repair transition');
END;

CREATE TRIGGER evidence_frontier_repairs_no_delete
BEFORE DELETE ON evidence_frontier_repairs
BEGIN
    SELECT RAISE(ABORT, 'evidence frontier repairs cannot be deleted');
END;

CREATE TABLE evidence_frontier_repair_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_id TEXT NOT NULL,
    event_index INTEGER NOT NULL CHECK (event_index > 0),
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'prepared', 'dispatching', 'indeterminate', 'acknowledged', 'conflicted'
    )),
    event_json TEXT NOT NULL CHECK (
        json_valid(event_json)
        AND length(CAST(event_json AS BLOB)) <= 65536
    ),
    event_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(event_sha256) = 64
        AND event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    previous_event_sha256 TEXT CHECK (
        previous_event_sha256 IS NULL OR (
            length(previous_event_sha256) = 64
            AND previous_event_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms > 0),
    UNIQUE(repair_id, event_index),
    FOREIGN KEY(repair_id) REFERENCES evidence_frontier_repairs(repair_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX evidence_frontier_repair_events_repair_seq
    ON evidence_frontier_repair_events(repair_id, event_index);

CREATE TRIGGER evidence_frontier_repair_events_no_update
BEFORE UPDATE ON evidence_frontier_repair_events
BEGIN
    SELECT RAISE(ABORT, 'evidence frontier repair events are immutable');
END;

CREATE TRIGGER evidence_frontier_repair_events_no_delete
BEFORE DELETE ON evidence_frontier_repair_events
BEGIN
    SELECT RAISE(ABORT, 'evidence frontier repair events cannot be deleted');
END;
