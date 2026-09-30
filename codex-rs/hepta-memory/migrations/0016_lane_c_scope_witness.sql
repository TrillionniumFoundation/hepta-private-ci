-- Request-hot Lane C witness. This is a rebuildable projection maintained by
-- the existing SQLite owner; it is not a second fact store, authorization
-- cache, currentness cache or writer. Exact-ID reads still load and validate
-- the selected immutable source rows inside the same owner transaction.

CREATE TABLE lane_c_scope_witness (
    owner_agent_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('agent_private', 'workspace_private')),
    workspace_key TEXT NOT NULL,
    state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
    memory_revision_count INTEGER NOT NULL CHECK (memory_revision_count >= 0),
    source_count INTEGER NOT NULL CHECK (source_count >= 0),
    citation_count INTEGER NOT NULL CHECK (citation_count >= 0),
    tombstone_count INTEGER NOT NULL CHECK (tombstone_count >= 0),
    knowledge_fact_count INTEGER NOT NULL CHECK (knowledge_fact_count >= 0),
    head_count INTEGER NOT NULL CHECK (head_count >= 0),
    PRIMARY KEY (owner_agent_id, scope_kind, workspace_key),
    CHECK (
        (scope_kind = 'agent_private' AND workspace_key = '') OR
        (scope_kind = 'workspace_private' AND length(workspace_key) = 64 AND
         workspace_key NOT GLOB '*[^0-9a-f]*')
    )
) STRICT;

CREATE TABLE lane_c_head_validity (
    memory_id TEXT PRIMARY KEY,
    owner_agent_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('agent_private', 'workspace_private')),
    workspace_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'provisional')),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'tombstoned')),
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    FOREIGN KEY (memory_id, revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    CHECK (valid_to_unix_seconds IS NULL OR valid_to_unix_seconds > valid_from_unix_seconds),
    CHECK (
        (scope_kind = 'agent_private' AND workspace_key = '') OR
        (scope_kind = 'workspace_private' AND length(workspace_key) = 64 AND
         workspace_key NOT GLOB '*[^0-9a-f]*')
    )
) STRICT;

CREATE INDEX lane_c_head_validity_start_lookup
ON lane_c_head_validity(
    owner_agent_id, scope_kind, workspace_key, verification, lifecycle,
    valid_from_unix_seconds
);

CREATE INDEX lane_c_head_validity_end_lookup
ON lane_c_head_validity(
    owner_agent_id, scope_kind, workspace_key, verification, lifecycle,
    valid_to_unix_seconds
);

-- Reconstruct the projection for existing stores. Later changes are maintained
-- by triggers in the same transactions as the existing owner tables.
WITH scopes(owner_agent_id, scope_kind, workspace_key) AS (
    SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
    FROM source_ledger
    UNION
    SELECT owner_agent_id, scope_kind, COALESCE(workspace_sha256, '')
    FROM memory_revisions
),
counts AS (
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
    FROM scopes s
)
INSERT INTO lane_c_scope_witness (
    owner_agent_id, scope_kind, workspace_key, state_revision,
    memory_revision_count, source_count, citation_count, tombstone_count,
    knowledge_fact_count, head_count
)
SELECT
    owner_agent_id,
    scope_kind,
    workspace_key,
    memory_revision_count + source_count + citation_count
        + knowledge_fact_count + head_count,
    memory_revision_count,
    source_count,
    citation_count,
    tombstone_count,
    knowledge_fact_count,
    head_count
FROM counts;

INSERT INTO lane_c_head_validity (
    memory_id, owner_agent_id, scope_kind, workspace_key, revision,
    content_sha256, verification, lifecycle, valid_from_unix_seconds,
    valid_to_unix_seconds
)
SELECT
    r.memory_id,
    r.owner_agent_id,
    r.scope_kind,
    COALESCE(r.workspace_sha256, ''),
    r.revision,
    r.content_sha256,
    r.verification,
    r.lifecycle,
    r.valid_from_unix_seconds,
    r.valid_to_unix_seconds
FROM memory_heads h
JOIN memory_revisions r
  ON r.memory_id = h.memory_id AND r.revision = h.revision;

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
END;
