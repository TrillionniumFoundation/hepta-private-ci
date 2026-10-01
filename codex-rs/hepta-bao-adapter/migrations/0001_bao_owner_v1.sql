-- Production-oriented metadata owner for the registered HeptaBao exact KV-v2
-- consumption boundary. Fixed-width big-endian BLOB integers preserve the full
-- u64 range and sort monotonically. No provider token or secret value is stored.

CREATE TABLE bao_owner_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    revision BLOB NOT NULL CHECK (length(revision) = 8),
    time_frontier_unix_ms BLOB NOT NULL CHECK (length(time_frontier_unix_ms) = 8)
) STRICT;

INSERT INTO bao_owner_meta(singleton, schema_version, revision, time_frontier_unix_ms)
VALUES (1, 1, X'0000000000000001', X'0000000000000000');

CREATE TABLE bao_operation (
    operation_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain IN ('consumption', 'lease')),
    kind TEXT NOT NULL CHECK (kind IN ('read', 'issue', 'renew', 'revoke')),
    semantic_sha256 BLOB NOT NULL CHECK (length(semantic_sha256) = 32),
    created_at_unix_ms BLOB NOT NULL CHECK (length(created_at_unix_ms) = 8),
    updated_at_unix_ms BLOB NOT NULL CHECK (length(updated_at_unix_ms) = 8),
    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1))
) STRICT, WITHOUT ROWID;

CREATE TABLE bao_consumption (
    operation_id TEXT PRIMARY KEY REFERENCES bao_operation(operation_id),
    semantic_sha256 BLOB NOT NULL CHECK (length(semantic_sha256) = 32),
    effect_sha256 BLOB NOT NULL CHECK (length(effect_sha256) = 32),
    request_sha256 BLOB NOT NULL CHECK (length(request_sha256) = 32),
    consumer_id TEXT NOT NULL,
    consumer_configuration_sha256 BLOB NOT NULL CHECK (length(consumer_configuration_sha256) = 32),
    amount BLOB NOT NULL CHECK (length(amount) = 8),
    state TEXT NOT NULL CHECK (state IN (
        'claimed', 'reserved', 'dispatch_fenced', 'delivery_prepared',
        'consumer_succeeded', 'consumer_not_applied', 'provider_failed',
        'indeterminate', 'succeeded', 'failed', 'dispatch_attempted'
    )),
    reservation_id TEXT,
    terminal_kind TEXT,
    terminal_code TEXT,
    terminal_evidence_sha256 BLOB CHECK (
        terminal_evidence_sha256 IS NULL OR length(terminal_evidence_sha256) = 32
    ),
    terminal_observed_cost BLOB CHECK (
        terminal_observed_cost IS NULL OR length(terminal_observed_cost) = 8
    ),
    row_json BLOB NOT NULL CHECK (length(row_json) BETWEEN 2 AND 131072),
    owner_revision BLOB NOT NULL CHECK (length(owner_revision) = 8),
    created_at_unix_ms BLOB NOT NULL CHECK (length(created_at_unix_ms) = 8),
    updated_at_unix_ms BLOB NOT NULL CHECK (length(updated_at_unix_ms) = 8),
    CHECK (
        (terminal_kind IS NULL AND terminal_code IS NULL
         AND terminal_evidence_sha256 IS NULL AND terminal_observed_cost IS NULL)
        OR
        (terminal_kind IS NOT NULL AND terminal_evidence_sha256 IS NOT NULL
         AND terminal_observed_cost IS NOT NULL)
    )
) STRICT, WITHOUT ROWID;

CREATE INDEX bao_consumption_state_updated
    ON bao_consumption(state, updated_at_unix_ms);
CREATE UNIQUE INDEX bao_consumption_reservation_identity
    ON bao_consumption(reservation_id) WHERE reservation_id IS NOT NULL;

CREATE TABLE bao_lease (
    lease_id TEXT PRIMARY KEY,
    generation BLOB NOT NULL CHECK (length(generation) = 8),
    state TEXT NOT NULL CHECK (state IN (
        'active', 'renew_unknown', 'revoke_unknown', 'revoked', 'expired'
    )),
    row_json BLOB NOT NULL CHECK (length(row_json) BETWEEN 2 AND 131072),
    updated_at_unix_ms BLOB NOT NULL CHECK (length(updated_at_unix_ms) = 8)
) STRICT, WITHOUT ROWID;

CREATE INDEX bao_lease_state_updated ON bao_lease(state, updated_at_unix_ms);

CREATE TABLE bao_lease_operation (
    operation_id TEXT PRIMARY KEY REFERENCES bao_operation(operation_id),
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('issue', 'renew', 'revoke')),
    lease_id TEXT,
    expected_generation BLOB CHECK (
        expected_generation IS NULL OR length(expected_generation) = 8
    ),
    resulting_generation BLOB CHECK (
        resulting_generation IS NULL OR length(resulting_generation) = 8
    ),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'unknown', 'applied', 'denied')),
    row_json BLOB NOT NULL CHECK (length(row_json) BETWEEN 2 AND 131072),
    terminal_result_sha256 BLOB CHECK (
        terminal_result_sha256 IS NULL OR length(terminal_result_sha256) = 32
    ),
    CHECK (
        (state IN ('prepared', 'unknown') AND terminal_result_sha256 IS NULL)
        OR
        (state IN ('applied', 'denied') AND terminal_result_sha256 IS NOT NULL)
    ),
    CHECK (
        (operation_kind = 'issue' AND expected_generation IS NULL)
        OR
        (operation_kind IN ('renew', 'revoke') AND lease_id IS NOT NULL
         AND expected_generation IS NOT NULL)
    )
) STRICT, WITHOUT ROWID;

CREATE UNIQUE INDEX bao_one_pending_renew_per_lease
    ON bao_lease_operation(lease_id)
    WHERE operation_kind = 'renew' AND state IN ('prepared', 'unknown');
CREATE UNIQUE INDEX bao_one_pending_revoke_per_lease
    ON bao_lease_operation(lease_id)
    WHERE operation_kind = 'revoke' AND state IN ('prepared', 'unknown');

CREATE TABLE bao_transition (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    revision BLOB NOT NULL UNIQUE CHECK (length(revision) = 8),
    operation_id TEXT NOT NULL REFERENCES bao_operation(operation_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    evidence_sha256 BLOB NOT NULL CHECK (length(evidence_sha256) = 32),
    observed_at_unix_ms BLOB NOT NULL CHECK (length(observed_at_unix_ms) = 8)
) STRICT;

CREATE INDEX bao_transition_operation_sequence
    ON bao_transition(operation_id, sequence);

CREATE TABLE bao_reconciliation_queue (
    operation_id TEXT PRIMARY KEY REFERENCES bao_operation(operation_id),
    reason TEXT NOT NULL,
    next_attempt_at_unix_ms BLOB NOT NULL CHECK (length(next_attempt_at_unix_ms) = 8),
    attempt_count BLOB NOT NULL CHECK (length(attempt_count) = 8),
    last_error_sha256 BLOB CHECK (
        last_error_sha256 IS NULL OR length(last_error_sha256) = 32
    )
) STRICT, WITHOUT ROWID;

CREATE INDEX bao_reconciliation_due
    ON bao_reconciliation_queue(next_attempt_at_unix_ms, operation_id);

CREATE TABLE bao_terminal_archive (
    operation_id TEXT PRIMARY KEY REFERENCES bao_operation(operation_id),
    semantic_sha256 BLOB NOT NULL CHECK (length(semantic_sha256) = 32),
    terminal_kind TEXT NOT NULL,
    terminal_code TEXT,
    terminal_evidence_sha256 BLOB NOT NULL CHECK (length(terminal_evidence_sha256) = 32),
    terminal_observed_cost BLOB NOT NULL CHECK (length(terminal_observed_cost) = 8),
    row_json BLOB NOT NULL CHECK (length(row_json) BETWEEN 2 AND 131072),
    owner_revision BLOB NOT NULL CHECK (length(owner_revision) = 8),
    created_at_unix_ms BLOB NOT NULL CHECK (length(created_at_unix_ms) = 8),
    updated_at_unix_ms BLOB NOT NULL CHECK (length(updated_at_unix_ms) = 8),
    archived_at_unix_ms BLOB NOT NULL CHECK (length(archived_at_unix_ms) = 8)
) STRICT, WITHOUT ROWID;

CREATE INDEX bao_terminal_archive_time
    ON bao_terminal_archive(archived_at_unix_ms, operation_id);

-- Owner meta is singleton, schema-stable and monotonic.
CREATE TRIGGER bao_owner_meta_no_insert
BEFORE INSERT ON bao_owner_meta
WHEN EXISTS(SELECT 1 FROM bao_owner_meta WHERE singleton = 1)
BEGIN
    SELECT RAISE(ABORT, 'Bao owner meta is a singleton');
END;

CREATE TRIGGER bao_owner_meta_no_delete
BEFORE DELETE ON bao_owner_meta
BEGIN
    SELECT RAISE(ABORT, 'Bao owner meta cannot be deleted');
END;

CREATE TRIGGER bao_owner_meta_monotonic
BEFORE UPDATE ON bao_owner_meta
WHEN NEW.singleton != OLD.singleton
  OR NEW.schema_version != OLD.schema_version
  OR NEW.revision < OLD.revision
  OR NEW.time_frontier_unix_ms < OLD.time_frontier_unix_ms
BEGIN
    SELECT RAISE(ABORT, 'Bao owner frontier cannot move backwards');
END;

-- Operation identities and historical tombstones are immutable.
CREATE TRIGGER bao_operation_identity_immutable
BEFORE UPDATE OF operation_id, domain, kind, semantic_sha256, created_at_unix_ms
ON bao_operation
BEGIN
    SELECT RAISE(ABORT, 'Bao operation identity is immutable');
END;

CREATE TRIGGER bao_operation_terminal_monotonic
BEFORE UPDATE OF terminal ON bao_operation
WHEN OLD.terminal = 1 AND NEW.terminal != 1
BEGIN
    SELECT RAISE(ABORT, 'Bao operation terminal state cannot be reopened');
END;

CREATE TRIGGER bao_operation_no_delete
BEFORE DELETE ON bao_operation
BEGIN
    SELECT RAISE(ABORT, 'Bao operation tombstone cannot be deleted');
END;

-- Consumption identity is immutable; once-bound evidence cannot be changed.
CREATE TRIGGER bao_consumption_identity_immutable
BEFORE UPDATE OF operation_id, semantic_sha256, effect_sha256, request_sha256,
                 consumer_id, consumer_configuration_sha256, amount,
                 created_at_unix_ms
ON bao_consumption
BEGIN
    SELECT RAISE(ABORT, 'Bao consumption identity is immutable');
END;

CREATE TRIGGER bao_consumption_reservation_immutable
BEFORE UPDATE OF reservation_id ON bao_consumption
WHEN OLD.reservation_id IS NOT NULL AND NEW.reservation_id IS NOT OLD.reservation_id
BEGIN
    SELECT RAISE(ABORT, 'Bao reservation identity is immutable');
END;

CREATE TRIGGER bao_consumption_terminal_immutable
BEFORE UPDATE OF terminal_kind, terminal_code, terminal_evidence_sha256,
                 terminal_observed_cost ON bao_consumption
WHEN OLD.terminal_kind IS NOT NULL AND (
    NEW.terminal_kind IS NOT OLD.terminal_kind
 OR NEW.terminal_code IS NOT OLD.terminal_code
 OR NEW.terminal_evidence_sha256 IS NOT OLD.terminal_evidence_sha256
 OR NEW.terminal_observed_cost IS NOT OLD.terminal_observed_cost
)
BEGIN
    SELECT RAISE(ABORT, 'Bao terminal evidence is immutable');
END;

CREATE TRIGGER bao_consumption_revision_monotonic
BEFORE UPDATE OF owner_revision, updated_at_unix_ms ON bao_consumption
WHEN NEW.owner_revision <= OLD.owner_revision
  OR NEW.updated_at_unix_ms < OLD.updated_at_unix_ms
BEGIN
    SELECT RAISE(ABORT, 'Bao consumption revision must advance');
END;

CREATE TRIGGER bao_consumption_delete_requires_archive
BEFORE DELETE ON bao_consumption
WHEN NOT EXISTS (
    SELECT 1 FROM bao_terminal_archive a
    WHERE a.operation_id = OLD.operation_id
      AND a.semantic_sha256 = OLD.semantic_sha256
      AND a.owner_revision = OLD.owner_revision
      AND a.row_json = OLD.row_json
)
BEGIN
    SELECT RAISE(ABORT, 'Bao terminal row must be archived before deletion');
END;

-- Lease projection updates are generation-fenced and terminal projections do
-- not resurrect. Rust validates exact +1/domain semantics where required.
CREATE TRIGGER bao_lease_identity_immutable
BEFORE UPDATE OF lease_id ON bao_lease
BEGIN
    SELECT RAISE(ABORT, 'Bao lease identity is immutable');
END;

CREATE TRIGGER bao_lease_generation_monotonic
BEFORE UPDATE OF generation, state ON bao_lease
WHEN NEW.generation <= OLD.generation
  OR (OLD.state IN ('revoked', 'expired') AND NEW.state != OLD.state)
BEGIN
    SELECT RAISE(ABORT, 'Bao lease generation/state cannot regress');
END;

CREATE TRIGGER bao_lease_no_delete
BEFORE DELETE ON bao_lease
BEGIN
    SELECT RAISE(ABORT, 'Bao lease projection cannot be forgotten');
END;

-- Lease-operation identity/result history is permanent.
CREATE TRIGGER bao_lease_operation_identity_immutable
BEFORE UPDATE OF operation_id, operation_kind, lease_id, expected_generation
ON bao_lease_operation
BEGIN
    SELECT RAISE(ABORT, 'Bao lease-operation identity is immutable');
END;

CREATE TRIGGER bao_lease_operation_terminal_immutable
BEFORE UPDATE OF resulting_generation, state, row_json, terminal_result_sha256
ON bao_lease_operation
WHEN OLD.state IN ('applied', 'denied')
BEGIN
    SELECT RAISE(ABORT, 'Bao lease-operation result is immutable');
END;

CREATE TRIGGER bao_lease_operation_no_delete
BEFORE DELETE ON bao_lease_operation
BEGIN
    SELECT RAISE(ABORT, 'Bao lease-operation history cannot be deleted');
END;

-- Evidence history and terminal archive are append-only.
CREATE TRIGGER bao_transition_no_update
BEFORE UPDATE ON bao_transition
BEGIN
    SELECT RAISE(ABORT, 'Bao transition history is append-only');
END;

CREATE TRIGGER bao_transition_no_delete
BEFORE DELETE ON bao_transition
BEGIN
    SELECT RAISE(ABORT, 'Bao transition history cannot be deleted');
END;

CREATE TRIGGER bao_terminal_archive_no_update
BEFORE UPDATE ON bao_terminal_archive
BEGIN
    SELECT RAISE(ABORT, 'Bao terminal archive is immutable');
END;

CREATE TRIGGER bao_terminal_archive_no_delete
BEFORE DELETE ON bao_terminal_archive
BEGIN
    SELECT RAISE(ABORT, 'Bao terminal archive cannot be deleted');
END;
