-- Independent reopen audit and same-transaction guards for the rebuildable
-- Lane C witness. These views are diagnostic projections only; they do not own
-- facts, authority, currentness, or publication.

CREATE VIEW lane_c_scope_witness_expected AS
WITH scopes(owner_agent_id, scope_kind, workspace_key) AS (
    SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
    FROM source_ledger
    UNION
    SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
    FROM memory_revisions
)
SELECT
    s.owner_agent_id,
    s.scope_kind,
    s.workspace_key,
    (
        SELECT COUNT(*) FROM memory_revisions r
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
    ) AS memory_revision_count,
    (
        SELECT COUNT(*) FROM source_ledger l
        WHERE l.owner_agent_id = s.owner_agent_id
          AND l.scope_kind = s.scope_kind
          AND COALESCE(l.workspace_sha256, '') = s.workspace_key
    ) AS source_count,
    (
        SELECT COUNT(*) FROM memory_citations c
        JOIN memory_revisions r
          ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
    ) AS citation_count,
    (
        SELECT COUNT(*) FROM memory_revisions r
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
          AND r.lifecycle = 'tombstoned'
    ) AS tombstone_count,
    (
        SELECT COUNT(*) FROM kg_revision_fact_sets f
        JOIN memory_revisions r
          ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
    ) AS knowledge_fact_count,
    (
        SELECT COUNT(*) FROM memory_heads h
        JOIN memory_revisions r
          ON r.memory_id = h.memory_id AND r.revision = h.revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
    ) AS head_count
FROM scopes s;

CREATE VIEW lane_c_scope_witness_audit AS
SELECT
    e.owner_agent_id,
    e.scope_kind,
    e.workspace_key,
    'missing_or_mismatched' AS problem
FROM lane_c_scope_witness_expected e
LEFT JOIN lane_c_scope_witness w
  ON w.owner_agent_id = e.owner_agent_id
 AND w.scope_kind = e.scope_kind
 AND w.workspace_key = e.workspace_key
WHERE w.owner_agent_id IS NULL
   OR w.memory_revision_count != e.memory_revision_count
   OR w.source_count != e.source_count
   OR w.citation_count != e.citation_count
   OR w.tombstone_count != e.tombstone_count
   OR w.knowledge_fact_count != e.knowledge_fact_count
   OR w.head_count != e.head_count
   OR w.state_revision < (
        e.memory_revision_count + e.source_count + e.citation_count
        + e.knowledge_fact_count + e.head_count
   )
UNION ALL
SELECT
    w.owner_agent_id,
    w.scope_kind,
    w.workspace_key,
    'unexpected' AS problem
FROM lane_c_scope_witness w
LEFT JOIN lane_c_scope_witness_expected e
  ON e.owner_agent_id = w.owner_agent_id
 AND e.scope_kind = w.scope_kind
 AND e.workspace_key = w.workspace_key
WHERE e.owner_agent_id IS NULL;

CREATE VIEW lane_c_head_validity_expected AS
SELECT
    r.memory_id,
    r.owner_agent_id,
    r.scope_kind,
    COALESCE(r.workspace_sha256, '') AS workspace_key,
    r.revision,
    r.content_sha256,
    r.verification,
    r.lifecycle,
    r.valid_from_unix_seconds,
    r.valid_to_unix_seconds
FROM memory_heads h
JOIN memory_revisions r
  ON r.memory_id = h.memory_id AND r.revision = h.revision;

CREATE VIEW lane_c_head_validity_audit AS
SELECT
    e.owner_agent_id,
    e.scope_kind,
    e.workspace_key,
    e.memory_id,
    'missing_or_mismatched' AS problem
FROM lane_c_head_validity_expected e
LEFT JOIN lane_c_head_validity v
  ON v.memory_id = e.memory_id
 AND v.owner_agent_id = e.owner_agent_id
 AND v.scope_kind = e.scope_kind
 AND v.workspace_key = e.workspace_key
 AND v.revision = e.revision
 AND v.content_sha256 = e.content_sha256
 AND v.verification = e.verification
 AND v.lifecycle = e.lifecycle
 AND v.valid_from_unix_seconds = e.valid_from_unix_seconds
 AND v.valid_to_unix_seconds IS e.valid_to_unix_seconds
WHERE v.memory_id IS NULL
UNION ALL
SELECT
    v.owner_agent_id,
    v.scope_kind,
    v.workspace_key,
    v.memory_id,
    'unexpected_or_mismatched' AS problem
FROM lane_c_head_validity v
LEFT JOIN lane_c_head_validity_expected e
  ON e.memory_id = v.memory_id
 AND e.owner_agent_id = v.owner_agent_id
 AND e.scope_kind = v.scope_kind
 AND e.workspace_key = v.workspace_key
 AND e.revision = v.revision
 AND e.content_sha256 = v.content_sha256
 AND e.verification = v.verification
 AND e.lifecycle = v.lifecycle
 AND e.valid_from_unix_seconds = v.valid_from_unix_seconds
 AND e.valid_to_unix_seconds IS v.valid_to_unix_seconds
WHERE e.memory_id IS NULL;

-- A pre-existing logical mismatch aborts this migration and therefore aborts
-- reopen. The temporary guard never becomes part of the durable schema.
CREATE TEMP TABLE lane_c_witness_migration_guard (
    ok INTEGER NOT NULL CHECK (ok = 1)
);
INSERT INTO lane_c_witness_migration_guard(ok)
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM lane_c_scope_witness_audit)
      OR EXISTS (SELECT 1 FROM lane_c_head_validity_audit)
    THEN 0
    ELSE 1
END;
DROP TABLE lane_c_witness_migration_guard;

-- Replace the original maintenance triggers with equivalent maintenance plus
-- an exact-scope audit before the outer write can commit.
DROP TRIGGER lane_c_source_witness_after_insert;
DROP TRIGGER lane_c_memory_revision_witness_after_insert;
DROP TRIGGER lane_c_citation_witness_after_insert;
DROP TRIGGER lane_c_fact_witness_after_insert;
DROP TRIGGER lane_c_head_witness_after_insert;
DROP TRIGGER lane_c_head_witness_after_update;
DROP TRIGGER lane_c_head_witness_after_delete;

CREATE TRIGGER lane_c_source_witness_after_insert
AFTER INSERT ON source_ledger BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    ) VALUES (
        NEW.owner_agent_id, NEW.scope_kind, COALESCE(NEW.workspace_sha256, ''),
        1, 0, 1, 0, 0, 0, 0
    )
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1,
        source_count = source_count + 1;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after source insert')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = COALESCE(NEW.workspace_sha256, '')
    );
END;

CREATE TRIGGER lane_c_memory_revision_witness_after_insert
AFTER INSERT ON memory_revisions BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    ) VALUES (
        NEW.owner_agent_id, NEW.scope_kind, COALESCE(NEW.workspace_sha256, ''),
        1, 1, 0, 0,
        CASE WHEN NEW.lifecycle = 'tombstoned' THEN 1 ELSE 0 END,
        0, 0
    )
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1,
        memory_revision_count = memory_revision_count + 1,
        tombstone_count = tombstone_count
            + CASE WHEN NEW.lifecycle = 'tombstoned' THEN 1 ELSE 0 END;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after memory insert')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = COALESCE(NEW.workspace_sha256, '')
    );
END;

CREATE TRIGGER lane_c_citation_witness_after_insert
AFTER INSERT ON memory_citations BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, ''),
        1, 0, 0, 1, 0, 0, 0
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.memory_revision
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1,
        citation_count = citation_count + 1;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after citation insert')
    WHERE EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_audit a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.memory_revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
END;

CREATE TRIGGER lane_c_fact_witness_after_insert
AFTER INSERT ON kg_revision_fact_sets BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, ''),
        1, 0, 0, 0, 0, 1, 0
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.memory_revision
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1,
        knowledge_fact_count = knowledge_fact_count + 1;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after fact insert')
    WHERE EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_audit a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.memory_revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
END;

CREATE TRIGGER lane_c_head_witness_after_insert
AFTER INSERT ON memory_heads BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, ''),
        1, 0, 0, 0, 0, 0, 1
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1,
        head_count = head_count + 1;

    INSERT INTO lane_c_head_validity (
        memory_id, owner_agent_id, scope_kind, workspace_key, revision,
        content_sha256, verification, lifecycle, valid_from_unix_seconds,
        valid_to_unix_seconds
    )
    SELECT
        r.memory_id, r.owner_agent_id, r.scope_kind,
        COALESCE(r.workspace_sha256, ''), r.revision, r.content_sha256,
        r.verification, r.lifecycle, r.valid_from_unix_seconds,
        r.valid_to_unix_seconds
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    ON CONFLICT(memory_id) DO UPDATE SET
        owner_agent_id = excluded.owner_agent_id,
        scope_kind = excluded.scope_kind,
        workspace_key = excluded.workspace_key,
        revision = excluded.revision,
        content_sha256 = excluded.content_sha256,
        verification = excluded.verification,
        lifecycle = excluded.lifecycle,
        valid_from_unix_seconds = excluded.valid_from_unix_seconds,
        valid_to_unix_seconds = excluded.valid_to_unix_seconds;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after head insert')
    WHERE EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_audit a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
    SELECT RAISE(ABORT, 'Lane C head-validity drift after head insert')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_head_validity_audit
        WHERE memory_id = NEW.memory_id
    );
END;

CREATE TRIGGER lane_c_head_witness_after_update
AFTER UPDATE OF revision ON memory_heads
WHEN OLD.revision != NEW.revision BEGIN
    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, ''),
        1, 0, 0, 0, 0, 0, 0
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    ON CONFLICT(owner_agent_id, scope_kind, workspace_key) DO UPDATE SET
        state_revision = state_revision + 1;

    INSERT INTO lane_c_head_validity (
        memory_id, owner_agent_id, scope_kind, workspace_key, revision,
        content_sha256, verification, lifecycle, valid_from_unix_seconds,
        valid_to_unix_seconds
    )
    SELECT
        r.memory_id, r.owner_agent_id, r.scope_kind,
        COALESCE(r.workspace_sha256, ''), r.revision, r.content_sha256,
        r.verification, r.lifecycle, r.valid_from_unix_seconds,
        r.valid_to_unix_seconds
    FROM memory_revisions r
    WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    ON CONFLICT(memory_id) DO UPDATE SET
        owner_agent_id = excluded.owner_agent_id,
        scope_kind = excluded.scope_kind,
        workspace_key = excluded.workspace_key,
        revision = excluded.revision,
        content_sha256 = excluded.content_sha256,
        verification = excluded.verification,
        lifecycle = excluded.lifecycle,
        valid_from_unix_seconds = excluded.valid_from_unix_seconds,
        valid_to_unix_seconds = excluded.valid_to_unix_seconds;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after head update')
    WHERE EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_audit a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
    SELECT RAISE(ABORT, 'Lane C head-validity drift after head update')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_head_validity_audit
        WHERE memory_id = NEW.memory_id
    );
END;

CREATE TRIGGER lane_c_head_witness_after_delete
AFTER DELETE ON memory_heads BEGIN
    UPDATE lane_c_scope_witness
    SET state_revision = state_revision + 1,
        head_count = head_count - 1
    WHERE (owner_agent_id, scope_kind, workspace_key) = (
        SELECT r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, '')
        FROM memory_revisions r
        WHERE r.memory_id = OLD.memory_id AND r.revision = OLD.revision
    );
    DELETE FROM lane_c_head_validity WHERE memory_id = OLD.memory_id;

    SELECT RAISE(ABORT, 'Lane C scope witness drift after head delete')
    WHERE EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_audit a
        JOIN memory_revisions r
          ON r.memory_id = OLD.memory_id
         AND r.revision = OLD.revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
    SELECT RAISE(ABORT, 'Lane C head-validity drift after head delete')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_head_validity_audit
        WHERE memory_id = OLD.memory_id
    );
END;

-- Direct writes to the derived projection are permitted only when they result
-- in the exact independently recomputed state. Deletion of a scope witness is
-- always rejected; future migrations can deliberately drop this guard first.
CREATE TRIGGER lane_c_scope_witness_direct_insert_guard
AFTER INSERT ON lane_c_scope_witness BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness direct-write drift')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = NEW.workspace_key
    );
END;

CREATE TRIGGER lane_c_scope_witness_direct_update_guard
AFTER UPDATE ON lane_c_scope_witness BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness direct-write drift')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = NEW.workspace_key
    );
END;

CREATE TRIGGER lane_c_scope_witness_direct_delete_guard
BEFORE DELETE ON lane_c_scope_witness BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness rows are derived and cannot be deleted');
END;

CREATE TRIGGER lane_c_head_validity_direct_insert_guard
AFTER INSERT ON lane_c_head_validity BEGIN
    SELECT RAISE(ABORT, 'Lane C head-validity direct-write drift')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_head_validity_audit
        WHERE memory_id = NEW.memory_id
    );
END;

CREATE TRIGGER lane_c_head_validity_direct_update_guard
AFTER UPDATE ON lane_c_head_validity BEGIN
    SELECT RAISE(ABORT, 'Lane C head-validity direct-write drift')
    WHERE EXISTS (
        SELECT 1 FROM lane_c_head_validity_audit
        WHERE memory_id = NEW.memory_id
    );
END;

CREATE TRIGGER lane_c_head_validity_direct_delete_guard
BEFORE DELETE ON lane_c_head_validity
WHEN EXISTS (
    SELECT 1 FROM memory_heads h WHERE h.memory_id = OLD.memory_id
) BEGIN
    SELECT RAISE(ABORT, 'Lane C head-validity row is still required by a current head');
END;
