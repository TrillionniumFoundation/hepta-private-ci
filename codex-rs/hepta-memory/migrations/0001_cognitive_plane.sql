CREATE TABLE cognitive_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36)
) STRICT;

CREATE TRIGGER cognitive_meta_no_update
BEFORE UPDATE ON cognitive_meta BEGIN
    SELECT RAISE(ABORT, 'cognitive store owner is immutable');
END;

CREATE TRIGGER cognitive_meta_no_delete
BEFORE DELETE ON cognitive_meta BEGIN
    SELECT RAISE(ABORT, 'cognitive store owner is immutable');
END;

CREATE TABLE source_ledger (
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision = 1),
    owner_agent_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('agent_private', 'workspace_private')),
    workspace_sha256 TEXT,
    source_kind TEXT NOT NULL,
    content BLOB NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_unix_seconds INTEGER NOT NULL,
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (source_id, source_revision),
    CHECK (
        (scope_kind = 'agent_private' AND workspace_sha256 IS NULL) OR
        (scope_kind = 'workspace_private' AND length(workspace_sha256) = 64 AND
         workspace_sha256 NOT GLOB '*[^0-9a-f]*')
    )
) STRICT;

CREATE TRIGGER source_ledger_no_update
BEFORE UPDATE ON source_ledger BEGIN
    SELECT RAISE(ABORT, 'source ledger is immutable');
END;

CREATE TRIGGER source_ledger_no_delete
BEFORE DELETE ON source_ledger BEGIN
    SELECT RAISE(ABORT, 'source ledger is immutable');
END;

CREATE TABLE memory_revisions (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    owner_agent_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('agent_private', 'workspace_private')),
    workspace_sha256 TEXT,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'provisional')),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'tombstoned')),
    tombstone_reason TEXT,
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    supersedes_revision INTEGER,
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (memory_id, revision),
    FOREIGN KEY (memory_id, supersedes_revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    CHECK (valid_to_unix_seconds IS NULL OR valid_to_unix_seconds > valid_from_unix_seconds),
    CHECK ((revision = 1 AND supersedes_revision IS NULL) OR
           (revision > 1 AND supersedes_revision = revision - 1)),
    CHECK ((lifecycle = 'active' AND tombstone_reason IS NULL) OR
           (lifecycle = 'tombstoned' AND length(tombstone_reason) BETWEEN 1 AND 256)),
    CHECK (
        (scope_kind = 'agent_private' AND workspace_sha256 IS NULL) OR
        (scope_kind = 'workspace_private' AND length(workspace_sha256) = 64 AND
         workspace_sha256 NOT GLOB '*[^0-9a-f]*')
    )
) STRICT;

CREATE TRIGGER memory_revisions_no_update
BEFORE UPDATE ON memory_revisions BEGIN
    SELECT RAISE(ABORT, 'memory revisions are immutable');
END;

CREATE TRIGGER memory_revisions_no_delete
BEFORE DELETE ON memory_revisions BEGIN
    SELECT RAISE(ABORT, 'memory revisions are immutable');
END;

CREATE TABLE memory_citations (
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision = 1),
    PRIMARY KEY (memory_id, memory_revision, ordinal),
    UNIQUE (memory_id, memory_revision, source_id, source_revision),
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    FOREIGN KEY (source_id, source_revision)
        REFERENCES source_ledger(source_id, source_revision) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER memory_citations_no_update
BEFORE UPDATE ON memory_citations BEGIN
    SELECT RAISE(ABORT, 'memory citations are immutable');
END;

CREATE TRIGGER memory_citations_no_delete
BEFORE DELETE ON memory_citations BEGIN
    SELECT RAISE(ABORT, 'memory citations are immutable');
END;

CREATE TABLE memory_heads (
    memory_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    FOREIGN KEY (memory_id, revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT
) STRICT;

CREATE VIRTUAL TABLE memory_fts USING fts5(
    memory_id UNINDEXED,
    revision UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE kg_projection (
    projection_scope TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK (generation >= 0)
) STRICT;

CREATE TABLE kg_nodes (
    projection_scope TEXT NOT NULL,
    generation INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation, node_id),
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    FOREIGN KEY (source_id, source_revision)
        REFERENCES source_ledger(source_id, source_revision) ON DELETE RESTRICT,
    CHECK (valid_to_unix_seconds IS NULL OR valid_to_unix_seconds > valid_from_unix_seconds)
) STRICT;

CREATE TABLE kg_edges (
    projection_scope TEXT NOT NULL,
    generation INTEGER NOT NULL,
    edge_id TEXT NOT NULL,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation, edge_id),
    FOREIGN KEY (projection_scope, generation, from_node_id)
        REFERENCES kg_nodes(projection_scope, generation, node_id) ON DELETE CASCADE,
    FOREIGN KEY (projection_scope, generation, to_node_id)
        REFERENCES kg_nodes(projection_scope, generation, node_id) ON DELETE CASCADE,
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    FOREIGN KEY (source_id, source_revision)
        REFERENCES source_ledger(source_id, source_revision) ON DELETE RESTRICT,
    CHECK (valid_to_unix_seconds IS NULL OR valid_to_unix_seconds > valid_from_unix_seconds)
) STRICT;

CREATE VIRTUAL TABLE kg_entity_fts USING fts5(
    projection_scope UNINDEXED,
    generation UNINDEXED,
    node_id UNINDEXED,
    entity_type,
    label,
    tokenize = 'unicode61'
);
