-- G3 adds immutable revision-scoped KG facts without changing the cognitive
-- database family version. cognitive_meta.schema_version intentionally stays 1.

CREATE TABLE kg_revision_fact_sets (
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL CHECK (memory_revision > 0),
    extractor_contract TEXT NOT NULL CHECK (
        length(trim(extractor_contract)) BETWEEN 1 AND 128 AND
        instr(extractor_contract, char(0)) = 0
    ),
    fact_set_sha256 TEXT NOT NULL CHECK (
        length(fact_set_sha256) = 64 AND
        fact_set_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision > 0),
    entity_count INTEGER NOT NULL CHECK (entity_count BETWEEN 0 AND 10000),
    relation_count INTEGER NOT NULL CHECK (relation_count BETWEEN 0 AND 50000),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (memory_id, memory_revision),
    UNIQUE (memory_id, memory_revision, fact_set_sha256),
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id, memory_revision, source_id, source_revision)
        REFERENCES memory_citations(
            memory_id, memory_revision, source_id, source_revision
        ) ON DELETE RESTRICT,
    CHECK (
        extractor_contract != 'legacy_pre_g3_empty_v1' OR
        (
            fact_set_sha256 =
                '6eb8599ab837d22123cda62453adb0c22a20fb1986308de666507188e79297af' AND
            entity_count = 0 AND relation_count = 0
        )
    )
) STRICT;

CREATE TRIGGER kg_revision_fact_sets_no_update
BEFORE UPDATE ON kg_revision_fact_sets BEGIN
    SELECT RAISE(ABORT, 'KG revision fact sets are immutable');
END;

CREATE TRIGGER kg_revision_fact_sets_no_delete
BEFORE DELETE ON kg_revision_fact_sets BEGIN
    SELECT RAISE(ABORT, 'KG revision fact sets are immutable');
END;

CREATE TABLE kg_revision_entities (
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL CHECK (memory_revision > 0),
    entity_key TEXT NOT NULL CHECK (
        length(trim(entity_key)) BETWEEN 1 AND 512 AND
        instr(entity_key, char(0)) = 0
    ),
    canonical_entity_id TEXT NOT NULL CHECK (
        length(trim(canonical_entity_id)) BETWEEN 1 AND 512 AND
        instr(canonical_entity_id, char(0)) = 0
    ),
    entity_type TEXT NOT NULL CHECK (
        length(trim(entity_type)) BETWEEN 1 AND 512 AND
        instr(entity_type, char(0)) = 0
    ),
    label TEXT NOT NULL CHECK (
        length(trim(label)) BETWEEN 1 AND 4096 AND
        instr(label, char(0)) = 0
    ),
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision > 0),
    PRIMARY KEY (memory_id, memory_revision, entity_key),
    UNIQUE (memory_id, memory_revision, entity_key, canonical_entity_id),
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES kg_revision_fact_sets(memory_id, memory_revision) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id, memory_revision, source_id, source_revision)
        REFERENCES memory_citations(
            memory_id, memory_revision, source_id, source_revision
        ) ON DELETE RESTRICT,
    CHECK (
        valid_to_unix_seconds IS NULL OR
        valid_to_unix_seconds > valid_from_unix_seconds
    )
) STRICT;

CREATE TRIGGER kg_revision_entities_declared_count
BEFORE INSERT ON kg_revision_entities
WHEN (
    SELECT COUNT(*) FROM kg_revision_entities
    WHERE memory_id = NEW.memory_id AND memory_revision = NEW.memory_revision
) >= (
    SELECT entity_count FROM kg_revision_fact_sets
    WHERE memory_id = NEW.memory_id AND memory_revision = NEW.memory_revision
) BEGIN
    SELECT RAISE(ABORT, 'KG entity facts exceed the immutable fact-set receipt');
END;

CREATE TRIGGER kg_revision_entities_no_update
BEFORE UPDATE ON kg_revision_entities BEGIN
    SELECT RAISE(ABORT, 'KG revision entities are immutable');
END;

CREATE TRIGGER kg_revision_entities_no_delete
BEFORE DELETE ON kg_revision_entities BEGIN
    SELECT RAISE(ABORT, 'KG revision entities are immutable');
END;

CREATE INDEX kg_revision_entities_canonical_lookup
ON kg_revision_entities(canonical_entity_id, memory_id, memory_revision);

CREATE INDEX kg_revision_entities_citation_lookup
ON kg_revision_entities(memory_id, memory_revision, source_id, source_revision);

CREATE TABLE kg_revision_relations (
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL CHECK (memory_revision > 0),
    relation_key TEXT NOT NULL CHECK (
        length(trim(relation_key)) BETWEEN 1 AND 512 AND
        instr(relation_key, char(0)) = 0
    ),
    canonical_relation_id TEXT NOT NULL CHECK (
        length(trim(canonical_relation_id)) BETWEEN 1 AND 512 AND
        instr(canonical_relation_id, char(0)) = 0
    ),
    from_entity_key TEXT NOT NULL CHECK (
        length(trim(from_entity_key)) BETWEEN 1 AND 512 AND
        instr(from_entity_key, char(0)) = 0
    ),
    from_canonical_entity_id TEXT NOT NULL CHECK (
        length(trim(from_canonical_entity_id)) BETWEEN 1 AND 512 AND
        instr(from_canonical_entity_id, char(0)) = 0
    ),
    to_entity_key TEXT NOT NULL CHECK (
        length(trim(to_entity_key)) BETWEEN 1 AND 512 AND
        instr(to_entity_key, char(0)) = 0
    ),
    to_canonical_entity_id TEXT NOT NULL CHECK (
        length(trim(to_canonical_entity_id)) BETWEEN 1 AND 512 AND
        instr(to_canonical_entity_id, char(0)) = 0
    ),
    relation TEXT NOT NULL CHECK (
        length(trim(relation)) BETWEEN 1 AND 512 AND
        instr(relation, char(0)) = 0
    ),
    valid_from_unix_seconds INTEGER NOT NULL,
    valid_to_unix_seconds INTEGER,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision > 0),
    PRIMARY KEY (memory_id, memory_revision, relation_key),
    FOREIGN KEY (memory_id, memory_revision)
        REFERENCES kg_revision_fact_sets(memory_id, memory_revision) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id, memory_revision, source_id, source_revision)
        REFERENCES memory_citations(
            memory_id, memory_revision, source_id, source_revision
        ) ON DELETE RESTRICT,
    FOREIGN KEY (
        memory_id, memory_revision, from_entity_key, from_canonical_entity_id
    ) REFERENCES kg_revision_entities(
        memory_id, memory_revision, entity_key, canonical_entity_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (
        memory_id, memory_revision, to_entity_key, to_canonical_entity_id
    ) REFERENCES kg_revision_entities(
        memory_id, memory_revision, entity_key, canonical_entity_id
    ) ON DELETE RESTRICT,
    CHECK (
        valid_to_unix_seconds IS NULL OR
        valid_to_unix_seconds > valid_from_unix_seconds
    )
) STRICT;

CREATE TRIGGER kg_revision_relations_declared_count
BEFORE INSERT ON kg_revision_relations
WHEN (
    SELECT COUNT(*) FROM kg_revision_relations
    WHERE memory_id = NEW.memory_id AND memory_revision = NEW.memory_revision
) >= (
    SELECT relation_count FROM kg_revision_fact_sets
    WHERE memory_id = NEW.memory_id AND memory_revision = NEW.memory_revision
) BEGIN
    SELECT RAISE(ABORT, 'KG relation facts exceed the immutable fact-set receipt');
END;

CREATE TRIGGER kg_revision_relations_no_update
BEFORE UPDATE ON kg_revision_relations BEGIN
    SELECT RAISE(ABORT, 'KG revision relations are immutable');
END;

CREATE TRIGGER kg_revision_relations_no_delete
BEFORE DELETE ON kg_revision_relations BEGIN
    SELECT RAISE(ABORT, 'KG revision relations are immutable');
END;

CREATE INDEX kg_revision_relations_from_entity_lookup
ON kg_revision_relations(
    from_canonical_entity_id, memory_id, memory_revision
);

CREATE INDEX kg_revision_relations_to_entity_lookup
ON kg_revision_relations(
    to_canonical_entity_id, memory_id, memory_revision
);

CREATE INDEX kg_revision_relations_canonical_lookup
ON kg_revision_relations(
    canonical_relation_id, memory_id, memory_revision
);

CREATE INDEX kg_revision_relations_citation_lookup
ON kg_revision_relations(memory_id, memory_revision, source_id, source_revision);

-- A receipt is the immutable boundary between one triggering memory fact set,
-- the exact active-head input snapshot, and the derived projection output.
CREATE TABLE kg_projection_generation_receipts (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    trigger_memory_id TEXT NOT NULL,
    trigger_memory_revision INTEGER NOT NULL CHECK (trigger_memory_revision > 0),
    fact_set_sha256 TEXT NOT NULL CHECK (
        length(fact_set_sha256) = 64 AND
        fact_set_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    input_heads_sha256 TEXT NOT NULL CHECK (
        length(input_heads_sha256) = 64 AND
        input_heads_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    output_sha256 TEXT NOT NULL CHECK (
        length(output_sha256) = 64 AND
        output_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    entity_count INTEGER NOT NULL CHECK (entity_count BETWEEN 0 AND 10000),
    relation_count INTEGER NOT NULL CHECK (relation_count BETWEEN 0 AND 50000),
    node_count INTEGER NOT NULL CHECK (node_count BETWEEN 0 AND 10000),
    edge_count INTEGER NOT NULL CHECK (edge_count BETWEEN 0 AND 50000),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (trigger_memory_id, trigger_memory_revision, fact_set_sha256)
        REFERENCES kg_revision_fact_sets(
            memory_id, memory_revision, fact_set_sha256
        ) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER kg_projection_generation_receipts_scope_match
BEFORE INSERT ON kg_projection_generation_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM memory_revisions AS m
    WHERE m.memory_id = NEW.trigger_memory_id
      AND m.revision = NEW.trigger_memory_revision
      AND (
          (m.scope_kind = 'agent_private' AND
           NEW.projection_scope = 'agent_private') OR
          (m.scope_kind = 'workspace_private' AND
           NEW.projection_scope = 'workspace_private:' || m.workspace_sha256)
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection receipt scope does not match its trigger revision');
END;

CREATE TRIGGER kg_projection_generation_receipts_fact_counts_match
BEFORE INSERT ON kg_projection_generation_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM kg_revision_fact_sets AS s
    WHERE s.memory_id = NEW.trigger_memory_id
      AND s.memory_revision = NEW.trigger_memory_revision
      AND s.fact_set_sha256 = NEW.fact_set_sha256
      AND s.entity_count = NEW.entity_count
      AND s.relation_count = NEW.relation_count
      AND s.entity_count = (
          SELECT COUNT(*) FROM kg_revision_entities AS e
          WHERE e.memory_id = NEW.trigger_memory_id
            AND e.memory_revision = NEW.trigger_memory_revision
      )
      AND s.relation_count = (
          SELECT COUNT(*) FROM kg_revision_relations AS r
          WHERE r.memory_id = NEW.trigger_memory_id
            AND r.memory_revision = NEW.trigger_memory_revision
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection receipt requires a complete triggering fact set');
END;

CREATE TRIGGER kg_projection_generation_receipts_no_update
BEFORE UPDATE ON kg_projection_generation_receipts BEGIN
    SELECT RAISE(ABORT, 'KG projection generation receipts are immutable');
END;

CREATE TRIGGER kg_projection_generation_receipts_no_delete
BEFORE DELETE ON kg_projection_generation_receipts BEGIN
    SELECT RAISE(ABORT, 'KG projection generation receipts are immutable');
END;

CREATE INDEX kg_projection_generation_receipts_trigger_lookup
ON kg_projection_generation_receipts(
    trigger_memory_id, trigger_memory_revision, fact_set_sha256
);

-- kg_nodes retains the original projection representation for compatibility.
-- This immutable companion binds every projected node to its stable identity.
CREATE TABLE kg_projection_node_entities (
    projection_scope TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    node_id TEXT NOT NULL,
    canonical_entity_id TEXT NOT NULL CHECK (
        length(trim(canonical_entity_id)) BETWEEN 1 AND 512 AND
        instr(canonical_entity_id, char(0)) = 0
    ),
    PRIMARY KEY (projection_scope, generation, node_id),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    FOREIGN KEY (projection_scope, generation, node_id)
        REFERENCES kg_nodes(projection_scope, generation, node_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER kg_projection_node_entities_no_update
BEFORE UPDATE ON kg_projection_node_entities BEGIN
    SELECT RAISE(ABORT, 'KG projection node identities are immutable');
END;

CREATE TRIGGER kg_projection_node_entities_no_delete
BEFORE DELETE ON kg_projection_node_entities BEGIN
    SELECT RAISE(ABORT, 'KG projection node identities are immutable');
END;

CREATE INDEX kg_projection_node_entities_canonical_lookup
ON kg_projection_node_entities(
    canonical_entity_id, projection_scope, generation
);

-- Pre-G3 projections have no fact-set or generation receipt. Revoke them
-- rather than presenting legacy test-only rebuilds as composed product truth.
DELETE FROM kg_entity_fts;
DELETE FROM kg_edges;
DELETE FROM kg_nodes;
DELETE FROM kg_projection;

-- Every pre-G3 memory revision receives an explicit zero-fact extraction
-- receipt. The digest is SHA-256("legacy_pre_g3_empty_v1").
INSERT INTO kg_revision_fact_sets (
    memory_id,
    memory_revision,
    extractor_contract,
    fact_set_sha256,
    source_id,
    source_revision,
    entity_count,
    relation_count,
    recorded_at_unix_seconds
)
SELECT
    memory_id,
    revision,
    'legacy_pre_g3_empty_v1',
    '6eb8599ab837d22123cda62453adb0c22a20fb1986308de666507188e79297af',
    (
        SELECT c.source_id FROM memory_citations AS c
        WHERE c.memory_id = memory_revisions.memory_id
          AND c.memory_revision = memory_revisions.revision
          AND c.ordinal = 0
    ),
    (
        SELECT c.source_revision FROM memory_citations AS c
        WHERE c.memory_id = memory_revisions.memory_id
          AND c.memory_revision = memory_revisions.revision
          AND c.ordinal = 0
    ),
    0,
    0,
    recorded_at_unix_seconds
FROM memory_revisions;

-- After the legacy revocation, all projection generations are append-only.
-- kg_projection remains the small mutable pointer to the current receipt.
CREATE TRIGGER kg_nodes_no_update
BEFORE UPDATE ON kg_nodes BEGIN
    SELECT RAISE(ABORT, 'KG projection nodes are immutable');
END;

CREATE TRIGGER kg_nodes_no_delete
BEFORE DELETE ON kg_nodes BEGIN
    SELECT RAISE(ABORT, 'KG projection nodes are immutable');
END;

CREATE TRIGGER kg_edges_no_update
BEFORE UPDATE ON kg_edges BEGIN
    SELECT RAISE(ABORT, 'KG projection edges are immutable');
END;

CREATE TRIGGER kg_edges_no_delete
BEFORE DELETE ON kg_edges BEGIN
    SELECT RAISE(ABORT, 'KG projection edges are immutable');
END;

CREATE TRIGGER kg_projection_no_delete
BEFORE DELETE ON kg_projection BEGIN
    SELECT RAISE(ABORT, 'KG projection current pointers cannot be deleted');
END;

CREATE TRIGGER kg_projection_scope_no_update
BEFORE UPDATE OF projection_scope ON kg_projection BEGIN
    SELECT RAISE(ABORT, 'KG projection scopes are immutable');
END;

CREATE TRIGGER kg_projection_generation_monotonic
BEFORE UPDATE OF generation ON kg_projection
WHEN NEW.generation != OLD.generation + 1 BEGIN
    SELECT RAISE(ABORT, 'KG projection generation must advance exactly once');
END;

CREATE TRIGGER kg_projection_current_receipt_on_insert
BEFORE INSERT ON kg_projection
WHEN NEW.generation > 0 AND NOT EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts AS r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_nodes AS n
          WHERE n.projection_scope = NEW.projection_scope
            AND n.generation = NEW.generation
      )
      AND r.edge_count = (
          SELECT COUNT(*) FROM kg_edges AS e
          WHERE e.projection_scope = NEW.projection_scope
            AND e.generation = NEW.generation
      )
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_projection_node_entities AS i
          WHERE i.projection_scope = NEW.projection_scope
            AND i.generation = NEW.generation
      )
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_entity_fts AS f
          WHERE f.projection_scope = NEW.projection_scope
            AND f.generation = NEW.generation
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete generation receipt');
END;

CREATE TRIGGER kg_projection_current_receipt_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NOT EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts AS r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_nodes AS n
          WHERE n.projection_scope = NEW.projection_scope
            AND n.generation = NEW.generation
      )
      AND r.edge_count = (
          SELECT COUNT(*) FROM kg_edges AS e
          WHERE e.projection_scope = NEW.projection_scope
            AND e.generation = NEW.generation
      )
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_projection_node_entities AS i
          WHERE i.projection_scope = NEW.projection_scope
            AND i.generation = NEW.generation
      )
      AND r.node_count = (
          SELECT COUNT(*) FROM kg_entity_fts AS f
          WHERE f.projection_scope = NEW.projection_scope
            AND f.generation = NEW.generation
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete generation receipt');
END;
