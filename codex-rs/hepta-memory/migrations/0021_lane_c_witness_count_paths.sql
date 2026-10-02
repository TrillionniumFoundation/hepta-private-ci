-- Canonical witness recounts remain mandatory on each mutation. For a table
-- whose indexed first and last scope keys both equal the selected scope, all
-- rows belong to that scope, so SQLite's table COUNT is the exact filtered count.
-- Otherwise retain the canonical filtered query. Child counts rely on enforced
-- foreign keys; writable and recovery opens independently reject orphan rows.
-- No counter is trusted to infer scope membership, and no admission bound changes.
-- Global reopen audits remain independent of the witness's scope inventory.

DROP INDEX memory_revisions_lane_c_scope_lookup;
CREATE INDEX memory_revisions_lane_c_scope_lookup ON memory_revisions(owner_agent_id, scope_kind, COALESCE(workspace_sha256, ''), memory_id, revision);
CREATE INDEX memory_revisions_lane_c_tombstone_scope_lookup ON memory_revisions(owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')) WHERE lifecycle = 'tombstoned';

CREATE VIEW lane_c_scope_witness_current_expected AS
SELECT
    s.owner_agent_id,
    s.scope_kind,
    s.workspace_key,
    (CASE WHEN (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id ASC, scope_kind ASC, COALESCE(workspace_sha256, '') ASC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      AND (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id DESC, scope_kind DESC, COALESCE(workspace_sha256, '') DESC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      THEN (SELECT COUNT(*) FROM memory_revisions)
      ELSE (
        SELECT COUNT(*) FROM memory_revisions r
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
      ) END) AS memory_revision_count,
    (CASE WHEN (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM source_ledger
         ORDER BY owner_agent_id ASC, scope_kind ASC, COALESCE(workspace_sha256, '') ASC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      AND (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM source_ledger
         ORDER BY owner_agent_id DESC, scope_kind DESC, COALESCE(workspace_sha256, '') DESC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      THEN (SELECT COUNT(*) FROM source_ledger)
      ELSE (
        SELECT COUNT(*) FROM source_ledger l
        WHERE l.owner_agent_id = s.owner_agent_id
          AND l.scope_kind = s.scope_kind
          AND COALESCE(l.workspace_sha256, '') = s.workspace_key
      ) END) AS source_count,
    (CASE WHEN (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id ASC, scope_kind ASC, COALESCE(workspace_sha256, '') ASC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      AND (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id DESC, scope_kind DESC, COALESCE(workspace_sha256, '') DESC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      THEN (SELECT COUNT(*) FROM memory_citations)
      ELSE (
        SELECT COUNT(*) FROM memory_citations c
        JOIN memory_revisions r
          ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
      ) END) AS citation_count,
    (
        SELECT COUNT(*) FROM memory_revisions r
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
          AND r.lifecycle = 'tombstoned'
    ) AS tombstone_count,
    (CASE WHEN (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id ASC, scope_kind ASC, COALESCE(workspace_sha256, '') ASC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      AND (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id DESC, scope_kind DESC, COALESCE(workspace_sha256, '') DESC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      THEN (SELECT COUNT(*) FROM kg_revision_fact_sets)
      ELSE (
        SELECT COUNT(*) FROM kg_revision_fact_sets f
        JOIN memory_revisions r
          ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
      ) END) AS knowledge_fact_count,
    (CASE WHEN (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id ASC, scope_kind ASC, COALESCE(workspace_sha256, '') ASC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      AND (SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
         FROM memory_revisions
         ORDER BY owner_agent_id DESC, scope_kind DESC, COALESCE(workspace_sha256, '') DESC
         LIMIT 1) = (s.owner_agent_id, s.scope_kind, s.workspace_key)
      THEN (SELECT COUNT(*) FROM memory_heads)
      ELSE (
        SELECT COUNT(*) FROM memory_heads h
        JOIN memory_revisions r
          ON r.memory_id = h.memory_id AND r.revision = h.revision
        WHERE r.owner_agent_id = s.owner_agent_id
          AND r.scope_kind = s.scope_kind
          AND COALESCE(r.workspace_sha256, '') = s.workspace_key
      ) END) AS head_count
FROM lane_c_scope_witness s;
CREATE VIEW lane_c_scope_witness_valid AS
SELECT w.owner_agent_id,w.scope_kind,w.workspace_key
FROM lane_c_scope_witness w JOIN lane_c_scope_witness_current_expected e
 ON w.owner_agent_id=e.owner_agent_id AND w.scope_kind=e.scope_kind AND w.workspace_key=e.workspace_key
WHERE w.memory_revision_count=e.memory_revision_count AND w.source_count=e.source_count
 AND w.citation_count=e.citation_count AND w.tombstone_count=e.tombstone_count
 AND w.knowledge_fact_count=e.knowledge_fact_count AND w.head_count=e.head_count
 AND w.state_revision >= w.memory_revision_count+w.source_count+w.citation_count+w.knowledge_fact_count+w.head_count
 AND w.memory_revision_count+w.source_count > 0;
DROP TRIGGER lane_c_head_witness_after_delete;
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
    WHERE NOT EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_valid a
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

DROP TRIGGER lane_c_scope_witness_direct_insert_guard;
CREATE TRIGGER lane_c_scope_witness_direct_insert_guard
AFTER INSERT ON lane_c_scope_witness BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness direct-write drift')
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness_valid a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = NEW.workspace_key
    );
END;

DROP TRIGGER lane_c_scope_witness_direct_update_guard;
CREATE TRIGGER lane_c_scope_witness_direct_update_guard
AFTER UPDATE ON lane_c_scope_witness BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness direct-write drift')
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness_valid a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = NEW.workspace_key
    );
END;

DROP TRIGGER lane_c_source_witness_after_insert;
CREATE TRIGGER lane_c_source_witness_after_insert
AFTER INSERT ON source_ledger BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1,
        source_count = source_count + 1
    WHERE owner_agent_id = NEW.owner_agent_id AND scope_kind = NEW.scope_kind
          AND workspace_key = COALESCE(NEW.workspace_sha256, '');

    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        NEW.owner_agent_id, NEW.scope_kind, COALESCE(NEW.workspace_sha256, ''),
        1, 0, 1, 0, 0, 0, 0
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness
        WHERE owner_agent_id = NEW.owner_agent_id AND scope_kind = NEW.scope_kind
          AND workspace_key = COALESCE(NEW.workspace_sha256, '')
    );

    SELECT RAISE(ABORT, 'Lane C scope witness drift after source insert')
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness_valid a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = COALESCE(NEW.workspace_sha256, '')
    );
END;

DROP TRIGGER lane_c_memory_revision_witness_after_insert;
CREATE TRIGGER lane_c_memory_revision_witness_after_insert
AFTER INSERT ON memory_revisions BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1,
        memory_revision_count = memory_revision_count + 1,
        tombstone_count = tombstone_count
            + CASE WHEN NEW.lifecycle = 'tombstoned' THEN 1 ELSE 0 END
    WHERE owner_agent_id = NEW.owner_agent_id AND scope_kind = NEW.scope_kind
          AND workspace_key = COALESCE(NEW.workspace_sha256, '');

    INSERT INTO lane_c_scope_witness (
        owner_agent_id, scope_kind, workspace_key, state_revision,
        memory_revision_count, source_count, citation_count, tombstone_count,
        knowledge_fact_count, head_count
    )
    SELECT
        NEW.owner_agent_id, NEW.scope_kind, COALESCE(NEW.workspace_sha256, ''),
        1, 1, 0, 0,
        CASE WHEN NEW.lifecycle = 'tombstoned' THEN 1 ELSE 0 END,
        0, 0
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness
        WHERE owner_agent_id = NEW.owner_agent_id AND scope_kind = NEW.scope_kind
          AND workspace_key = COALESCE(NEW.workspace_sha256, '')
    );

    SELECT RAISE(ABORT, 'Lane C scope witness drift after memory insert')
    WHERE NOT EXISTS (
        SELECT 1 FROM lane_c_scope_witness_valid a
        WHERE a.owner_agent_id = NEW.owner_agent_id
          AND a.scope_kind = NEW.scope_kind
          AND a.workspace_key = COALESCE(NEW.workspace_sha256, '')
    );
END;

DROP TRIGGER lane_c_citation_witness_after_insert;
CREATE TRIGGER lane_c_citation_witness_after_insert
AFTER INSERT ON memory_citations BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1,
        citation_count = citation_count + 1
    WHERE (owner_agent_id, scope_kind, workspace_key) = (
        SELECT r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, '')
        FROM memory_revisions r
        WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.memory_revision
    );

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
      AND NOT EXISTS (
          SELECT 1 FROM lane_c_scope_witness w
          WHERE w.owner_agent_id = r.owner_agent_id
            AND w.scope_kind = r.scope_kind
            AND w.workspace_key = COALESCE(r.workspace_sha256, '')
      );

    SELECT RAISE(ABORT, 'Lane C scope witness drift after citation insert')
    WHERE NOT EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_valid a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.memory_revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
END;

DROP TRIGGER lane_c_fact_witness_after_insert;
CREATE TRIGGER lane_c_fact_witness_after_insert
AFTER INSERT ON kg_revision_fact_sets BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1,
        knowledge_fact_count = knowledge_fact_count + 1
    WHERE (owner_agent_id, scope_kind, workspace_key) = (
        SELECT r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, '')
        FROM memory_revisions r
        WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.memory_revision
    );

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
      AND NOT EXISTS (
          SELECT 1 FROM lane_c_scope_witness w
          WHERE w.owner_agent_id = r.owner_agent_id
            AND w.scope_kind = r.scope_kind
            AND w.workspace_key = COALESCE(r.workspace_sha256, '')
      );

    SELECT RAISE(ABORT, 'Lane C scope witness drift after fact insert')
    WHERE NOT EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_valid a
        JOIN memory_revisions r
          ON r.memory_id = NEW.memory_id
         AND r.revision = NEW.memory_revision
         AND a.owner_agent_id = r.owner_agent_id
         AND a.scope_kind = r.scope_kind
         AND a.workspace_key = COALESCE(r.workspace_sha256, '')
    );
END;

DROP TRIGGER lane_c_head_witness_after_insert;
CREATE TRIGGER lane_c_head_witness_after_insert
AFTER INSERT ON memory_heads BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1,
        head_count = head_count + 1
    WHERE (owner_agent_id, scope_kind, workspace_key) = (
        SELECT r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, '')
        FROM memory_revisions r
        WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    );

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
      AND NOT EXISTS (
          SELECT 1 FROM lane_c_scope_witness w
          WHERE w.owner_agent_id = r.owner_agent_id
            AND w.scope_kind = r.scope_kind
            AND w.workspace_key = COALESCE(r.workspace_sha256, '')
      );

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
    WHERE NOT EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_valid a
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

DROP TRIGGER lane_c_head_witness_after_update;
CREATE TRIGGER lane_c_head_witness_after_update
AFTER UPDATE OF revision ON memory_heads
WHEN OLD.revision != NEW.revision BEGIN
    UPDATE lane_c_scope_witness
    SET
        state_revision = state_revision + 1
    WHERE (owner_agent_id, scope_kind, workspace_key) = (
        SELECT r.owner_agent_id, r.scope_kind, COALESCE(r.workspace_sha256, '')
        FROM memory_revisions r
        WHERE r.memory_id = NEW.memory_id AND r.revision = NEW.revision
    );

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
      AND NOT EXISTS (
          SELECT 1 FROM lane_c_scope_witness w
          WHERE w.owner_agent_id = r.owner_agent_id
            AND w.scope_kind = r.scope_kind
            AND w.workspace_key = COALESCE(r.workspace_sha256, '')
      );

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
    WHERE NOT EXISTS (
        SELECT 1
        FROM lane_c_scope_witness_valid a
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
