-- Scope identity and mutation history are part of exact-ID currentness. A
-- direct projection write must not erase a head-pointer transition by restoring
-- a previous state_revision that still exceeds the append-only row counts.
-- Existing owner maintenance updates preserve identity and advance by one.
CREATE TRIGGER memory_heads_identity_guard
BEFORE UPDATE OF memory_id ON memory_heads
WHEN NEW.memory_id IS NOT OLD.memory_id BEGIN
    SELECT RAISE(ABORT, 'Memory head identity cannot change');
END;

CREATE TRIGGER lane_c_head_validity_identity_guard
BEFORE UPDATE OF memory_id ON lane_c_head_validity
WHEN NEW.memory_id IS NOT OLD.memory_id BEGIN
    SELECT RAISE(ABORT, 'Lane C head-validity identity cannot change');
END;

CREATE TRIGGER lane_c_scope_witness_monotonic_guard
BEFORE UPDATE ON lane_c_scope_witness
WHEN NEW.owner_agent_id IS NOT OLD.owner_agent_id
  OR NEW.scope_kind IS NOT OLD.scope_kind
  OR NEW.workspace_key IS NOT OLD.workspace_key
  OR NEW.state_revision <= OLD.state_revision BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness identity or state revision regressed');
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
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
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
    WHERE EXISTS (
        SELECT 1 FROM lane_c_scope_witness_audit a
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

-- REPLACE can silently delete a conflicting row when recursive_triggers is
-- off. Owner maintenance therefore updates an existing identity before an
-- insert-if-absent, and the schema rejects all conflicting direct inserts.
CREATE TRIGGER lane_c_scope_witness_existing_insert_guard
BEFORE INSERT ON lane_c_scope_witness
WHEN EXISTS (
    SELECT 1 FROM lane_c_scope_witness w
    WHERE w.owner_agent_id = NEW.owner_agent_id
      AND w.scope_kind = NEW.scope_kind
      AND w.workspace_key = NEW.workspace_key
) BEGIN
    SELECT RAISE(ABORT, 'Lane C scope witness existing identity cannot be replaced');
END;
