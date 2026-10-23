-- Durable kernel.evidence external-publication state.
-- Qualification appends enqueue one immutable operation identity in the same
-- SQLite transaction through the AFTER INSERT trigger below.  A publisher must
-- durably fence ownership and the exact batch before attempting external CAS.

CREATE TABLE evidence_publication_owner (
    store_id TEXT PRIMARY KEY CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    owner_id TEXT NOT NULL CHECK (
        length(owner_id) BETWEEN 1 AND 128
        AND owner_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    owner_generation INTEGER NOT NULL CHECK (owner_generation > 0),
    lease_expires_at_ms INTEGER NOT NULL CHECK (lease_expires_at_ms > 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms > 0),
    FOREIGN KEY(store_id) REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TRIGGER evidence_publication_owner_transition
BEFORE UPDATE ON evidence_publication_owner
WHEN NEW.store_id != OLD.store_id
  OR NEW.owner_generation < OLD.owner_generation
  OR NEW.updated_at_ms < OLD.updated_at_ms
  OR NEW.lease_expires_at_ms < NEW.updated_at_ms
  OR (
      NEW.owner_generation = OLD.owner_generation
      AND (
          NEW.owner_id != OLD.owner_id
          OR NEW.lease_expires_at_ms < OLD.lease_expires_at_ms
      )
  )
  OR (
      NEW.owner_generation > OLD.owner_generation
      AND (
          NEW.owner_generation != OLD.owner_generation + 1
          OR OLD.lease_expires_at_ms > NEW.updated_at_ms
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid evidence publication owner transition');
END;

CREATE TRIGGER evidence_publication_owner_no_delete
BEFORE DELETE ON evidence_publication_owner
BEGIN
    SELECT RAISE(ABORT, 'evidence publication owner history cannot be deleted');
END;

CREATE TABLE evidence_publication_batches (
    batch_id TEXT PRIMARY KEY CHECK (
        length(batch_id) BETWEEN 1 AND 128
        AND batch_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    store_id TEXT NOT NULL CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    prepared_owner_id TEXT NOT NULL CHECK (
        length(prepared_owner_id) BETWEEN 1 AND 128
        AND prepared_owner_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    prepared_owner_generation INTEGER NOT NULL CHECK (prepared_owner_generation > 0),
    state TEXT NOT NULL CHECK (state IN (
        'prepared', 'dispatching', 'indeterminate', 'acknowledged'
    )),
    first_intent_seq INTEGER NOT NULL CHECK (first_intent_seq > 0),
    last_intent_seq INTEGER NOT NULL CHECK (last_intent_seq >= first_intent_seq),
    intent_count INTEGER NOT NULL CHECK (intent_count BETWEEN 1 AND 512),
    snapshot_json TEXT NOT NULL CHECK (
        json_valid(snapshot_json) AND length(CAST(snapshot_json AS BLOB)) <= 65536
    ),
    snapshot_sha256 TEXT NOT NULL CHECK (
        length(snapshot_sha256) = 64
        AND snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    expected_frontier_generation INTEGER CHECK (
        expected_frontier_generation IS NULL OR expected_frontier_generation > 0
    ),
    expected_frontier_sha256 TEXT CHECK (
        expected_frontier_sha256 IS NULL OR (
            length(expected_frontier_sha256) = 64
            AND expected_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    expected_backend_identity_sha256 TEXT CHECK (
        expected_backend_identity_sha256 IS NULL OR (
            length(expected_backend_identity_sha256) = 64
            AND expected_backend_identity_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    proposed_frontier_generation INTEGER NOT NULL CHECK (proposed_frontier_generation > 0),
    proposed_frontier_sha256 TEXT CHECK (
        proposed_frontier_sha256 IS NULL OR (
            length(proposed_frontier_sha256) = 64
            AND proposed_frontier_sha256 NOT GLOB '*[^0-9a-f]*'
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
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    CHECK (
        (expected_frontier_generation IS NULL
            AND expected_frontier_sha256 IS NULL
            AND expected_backend_identity_sha256 IS NULL)
        OR
        (expected_frontier_generation IS NOT NULL
            AND expected_frontier_sha256 IS NOT NULL
            AND expected_backend_identity_sha256 IS NOT NULL)
    ),
    CHECK (
        (state = 'prepared'
            AND proposed_frontier_sha256 IS NULL
            AND backend_identity_sha256 IS NULL
            AND durable_audit_sequence IS NULL)
        OR
        (state IN ('dispatching', 'indeterminate')
            AND proposed_frontier_sha256 IS NOT NULL
            AND backend_identity_sha256 IS NOT NULL
            AND durable_audit_sequence IS NULL)
        OR
        (state = 'acknowledged'
            AND proposed_frontier_sha256 IS NOT NULL
            AND backend_identity_sha256 IS NOT NULL
            AND durable_audit_sequence IS NOT NULL)
    ),
    FOREIGN KEY(store_id) REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX evidence_publication_batches_store_state_seq
    ON evidence_publication_batches(store_id, state, first_intent_seq);

CREATE TRIGGER evidence_publication_batches_transition
BEFORE UPDATE ON evidence_publication_batches
WHEN NEW.batch_id != OLD.batch_id
  OR NEW.store_id != OLD.store_id
  OR NEW.prepared_owner_id != OLD.prepared_owner_id
  OR NEW.prepared_owner_generation != OLD.prepared_owner_generation
  OR NEW.first_intent_seq != OLD.first_intent_seq
  OR NEW.last_intent_seq != OLD.last_intent_seq
  OR NEW.intent_count != OLD.intent_count
  OR NEW.snapshot_json != OLD.snapshot_json
  OR NEW.snapshot_sha256 != OLD.snapshot_sha256
  OR NEW.expected_frontier_generation IS NOT OLD.expected_frontier_generation
  OR NEW.expected_frontier_sha256 IS NOT OLD.expected_frontier_sha256
  OR NEW.expected_backend_identity_sha256 IS NOT OLD.expected_backend_identity_sha256
  OR NEW.proposed_frontier_generation != OLD.proposed_frontier_generation
  OR NEW.created_at_ms != OLD.created_at_ms
  OR NEW.updated_at_ms < OLD.updated_at_ms
  OR NOT (
      (OLD.state = 'prepared' AND NEW.state = 'dispatching'
          AND OLD.proposed_frontier_sha256 IS NULL
          AND OLD.backend_identity_sha256 IS NULL
          AND NEW.proposed_frontier_sha256 IS NOT NULL
          AND NEW.backend_identity_sha256 IS NOT NULL
          AND NEW.durable_audit_sequence IS NULL)
      OR
      (OLD.state = 'dispatching' AND NEW.state = 'indeterminate'
          AND NEW.proposed_frontier_sha256 = OLD.proposed_frontier_sha256
          AND NEW.backend_identity_sha256 = OLD.backend_identity_sha256
          AND NEW.durable_audit_sequence IS NULL)
      OR
      (OLD.state IN ('dispatching', 'indeterminate') AND NEW.state = 'acknowledged'
          AND NEW.proposed_frontier_sha256 = OLD.proposed_frontier_sha256
          AND NEW.backend_identity_sha256 = OLD.backend_identity_sha256
          AND NEW.durable_audit_sequence IS NOT NULL)
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid evidence publication batch transition');
END;

CREATE TRIGGER evidence_publication_batches_no_delete
BEFORE DELETE ON evidence_publication_batches
BEGIN
    SELECT RAISE(ABORT, 'evidence publication batches cannot be deleted');
END;

CREATE TABLE evidence_publication_intents (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE CHECK (
        length(operation_id) BETWEEN 1 AND 128
        AND operation_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    store_id TEXT NOT NULL CHECK (
        length(store_id) BETWEEN 1 AND 128
        AND store_id NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    evidence_id TEXT NOT NULL UNIQUE,
    qualification_seq INTEGER NOT NULL UNIQUE CHECK (qualification_seq > 0),
    state TEXT NOT NULL CHECK (state IN ('pending', 'batched', 'acknowledged')),
    batch_id TEXT,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    CHECK (
        (state = 'pending' AND batch_id IS NULL)
        OR (state IN ('batched', 'acknowledged') AND batch_id IS NOT NULL)
    ),
    FOREIGN KEY(store_id) REFERENCES evidence_recovery_identity(store_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(evidence_id) REFERENCES qualification_evidence(evidence_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(batch_id) REFERENCES evidence_publication_batches(batch_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX evidence_publication_intents_store_state_seq
    ON evidence_publication_intents(store_id, state, qualification_seq);

CREATE TRIGGER evidence_publication_intents_transition
BEFORE UPDATE ON evidence_publication_intents
WHEN NEW.seq != OLD.seq
  OR NEW.operation_id != OLD.operation_id
  OR NEW.store_id != OLD.store_id
  OR NEW.evidence_id != OLD.evidence_id
  OR NEW.qualification_seq != OLD.qualification_seq
  OR NEW.created_at_ms != OLD.created_at_ms
  OR NEW.updated_at_ms < OLD.updated_at_ms
  OR NOT (
      (OLD.state = 'pending' AND NEW.state = 'batched'
          AND OLD.batch_id IS NULL AND NEW.batch_id IS NOT NULL)
      OR
      (OLD.state = 'batched' AND NEW.state = 'acknowledged'
          AND NEW.batch_id = OLD.batch_id)
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid evidence publication intent transition');
END;

CREATE TRIGGER evidence_publication_intents_no_delete
BEFORE DELETE ON evidence_publication_intents
BEGIN
    SELECT RAISE(ABORT, 'evidence publication intents cannot be deleted');
END;

CREATE TRIGGER qualification_evidence_enqueue_publication
AFTER INSERT ON qualification_evidence
WHEN EXISTS (SELECT 1 FROM evidence_recovery_identity WHERE singleton = 1)
BEGIN
    INSERT INTO evidence_publication_intents (
        operation_id, store_id, evidence_id, qualification_seq,
        state, batch_id, created_at_ms, updated_at_ms
    )
    SELECT
        'qualification:' || NEW.evidence_id,
        store_id,
        NEW.evidence_id,
        NEW.seq,
        'pending',
        NULL,
        NEW.recorded_at_ms,
        NEW.recorded_at_ms
    FROM evidence_recovery_identity WHERE singleton = 1;
END;

CREATE TRIGGER evidence_recovery_identity_backfill_publication
AFTER INSERT ON evidence_recovery_identity
BEGIN
    INSERT INTO evidence_publication_intents (
        operation_id, store_id, evidence_id, qualification_seq,
        state, batch_id, created_at_ms, updated_at_ms
    )
    SELECT
        'qualification:' || evidence_id,
        NEW.store_id,
        evidence_id,
        seq,
        'pending',
        NULL,
        recorded_at_ms,
        recorded_at_ms
    FROM qualification_evidence
    ORDER BY seq;
END;

-- Backfill lineages that were already enrolled before this migration.
INSERT INTO evidence_publication_intents (
    operation_id, store_id, evidence_id, qualification_seq,
    state, batch_id, created_at_ms, updated_at_ms
)
SELECT
    'qualification:' || q.evidence_id,
    i.store_id,
    q.evidence_id,
    q.seq,
    'pending',
    NULL,
    q.recorded_at_ms,
    q.recorded_at_ms
FROM qualification_evidence AS q
JOIN evidence_recovery_identity AS i ON i.singleton = 1
ORDER BY q.seq;
