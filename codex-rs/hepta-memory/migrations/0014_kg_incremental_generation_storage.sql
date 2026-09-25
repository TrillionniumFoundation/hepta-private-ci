-- G14 stops copying the complete knowledge graph into every projection generation.
-- Immutable memory revisions and revision-scoped KG facts already contain the
-- canonical content. A generation now records only its trigger/source cut,
-- semantic/publication receipts, and this storage-mode witness. Historical
-- generations are reconstructed from the latest trigger revision for each
-- memory at or before that generation.
CREATE TABLE kg_projection_generation_storage (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    storage_mode TEXT NOT NULL CHECK (storage_mode = 'revision_facts_v1'),
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_semantics(
            projection_scope, generation
        ) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER kg_projection_generation_storage_no_update
BEFORE UPDATE ON kg_projection_generation_storage BEGIN
    SELECT RAISE(ABORT, 'KG projection generation storage witnesses are immutable');
END;

CREATE TRIGGER kg_projection_generation_storage_no_delete
BEFORE DELETE ON kg_projection_generation_storage BEGIN
    SELECT RAISE(ABORT, 'KG projection generation storage witnesses are immutable');
END;

CREATE INDEX kg_projection_generation_receipts_scope_memory_generation
ON kg_projection_generation_receipts(
    projection_scope, trigger_memory_id, generation
);

-- Prove that the compact generation's declared node/edge counts match the
-- immutable revision facts selected by its exact trigger history before the
-- compact-storage witness can be published.
CREATE TRIGGER kg_projection_generation_storage_counts_match
BEFORE INSERT ON kg_projection_generation_storage
WHEN NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_receipts r
    JOIN kg_projection_generation_semantics s
      ON s.projection_scope = r.projection_scope
     AND s.generation = r.generation
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND r.node_count = (
          SELECT COUNT(*)
          FROM kg_revision_entities e
          JOIN kg_projection_generation_receipts h
            ON h.projection_scope = NEW.projection_scope
           AND h.trigger_memory_id = e.memory_id
           AND h.trigger_memory_revision = e.memory_revision
           AND h.generation = (
               SELECT MAX(x.generation)
               FROM kg_projection_generation_receipts x
               WHERE x.projection_scope = NEW.projection_scope
                 AND x.trigger_memory_id = e.memory_id
                 AND x.generation <= NEW.generation
           )
          JOIN memory_revisions m
            ON m.memory_id = h.trigger_memory_id
           AND m.revision = h.trigger_memory_revision
          WHERE m.verification = 'verified'
            AND m.lifecycle = 'active'
      )
      AND r.edge_count = (
          SELECT COUNT(*)
          FROM kg_revision_relations q
          JOIN kg_projection_generation_receipts h
            ON h.projection_scope = NEW.projection_scope
           AND h.trigger_memory_id = q.memory_id
           AND h.trigger_memory_revision = q.memory_revision
           AND h.generation = (
               SELECT MAX(x.generation)
               FROM kg_projection_generation_receipts x
               WHERE x.projection_scope = NEW.projection_scope
                 AND x.trigger_memory_id = q.memory_id
                 AND x.generation <= NEW.generation
           )
          JOIN memory_revisions m
            ON m.memory_id = h.trigger_memory_id
           AND m.revision = h.trigger_memory_revision
          WHERE m.verification = 'verified'
            AND m.lifecycle = 'active'
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG compact generation counts do not match immutable revision facts');
END;

-- Index entity text once per immutable memory revision rather than once per
-- projection generation. Current-head and scope checks stay in the retrieval
-- query, so obsolete revisions cannot become current results.
CREATE VIRTUAL TABLE kg_revision_entity_fts USING fts5(
    memory_id UNINDEXED,
    memory_revision UNINDEXED,
    entity_key UNINDEXED,
    canonical_entity_id UNINDEXED,
    entity_type,
    label,
    tokenize = 'unicode61'
);

INSERT INTO kg_revision_entity_fts (
    memory_id, memory_revision, entity_key, canonical_entity_id, entity_type, label
)
SELECT memory_id, memory_revision, entity_key, canonical_entity_id, entity_type, label
FROM kg_revision_entities
ORDER BY memory_id, memory_revision, entity_key;

DROP TRIGGER kg_projection_current_receipt_on_insert;
DROP TRIGGER kg_projection_current_receipt_on_update;

-- Pre-G14 complete generations remain valid history. Every generation published
-- after this migration must instead carry the compact storage witness.
CREATE TRIGGER kg_projection_current_receipt_on_insert
BEFORE INSERT ON kg_projection
WHEN NEW.generation > 0 AND NOT EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND (
          EXISTS (
              SELECT 1 FROM kg_projection_generation_storage s
              WHERE s.projection_scope = NEW.projection_scope
                AND s.generation = NEW.generation
                AND s.storage_mode = 'revision_facts_v1'
          )
          OR (
              r.node_count = (
                  SELECT COUNT(*) FROM kg_nodes n
                  WHERE n.projection_scope = NEW.projection_scope
                    AND n.generation = NEW.generation
              )
              AND r.edge_count = (
                  SELECT COUNT(*) FROM kg_edges e
                  WHERE e.projection_scope = NEW.projection_scope
                    AND e.generation = NEW.generation
              )
              AND r.node_count = (
                  SELECT COUNT(*) FROM kg_projection_node_entities i
                  WHERE i.projection_scope = NEW.projection_scope
                    AND i.generation = NEW.generation
              )
              AND r.node_count = (
                  SELECT COUNT(*) FROM kg_entity_fts f
                  WHERE f.projection_scope = NEW.projection_scope
                    AND f.generation = NEW.generation
              )
          )
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete generation receipt');
END;

CREATE TRIGGER kg_projection_current_receipt_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NOT EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND (
          EXISTS (
              SELECT 1 FROM kg_projection_generation_storage s
              WHERE s.projection_scope = NEW.projection_scope
                AND s.generation = NEW.generation
                AND s.storage_mode = 'revision_facts_v1'
          )
          OR (
              r.node_count = (
                  SELECT COUNT(*) FROM kg_nodes n
                  WHERE n.projection_scope = NEW.projection_scope
                    AND n.generation = NEW.generation
              )
              AND r.edge_count = (
                  SELECT COUNT(*) FROM kg_edges e
                  WHERE e.projection_scope = NEW.projection_scope
                    AND e.generation = NEW.generation
              )
              AND r.node_count = (
                  SELECT COUNT(*) FROM kg_projection_node_entities i
                  WHERE i.projection_scope = NEW.projection_scope
                    AND i.generation = NEW.generation
              )
              AND r.node_count = (
                  SELECT COUNT(*) FROM kg_entity_fts f
                  WHERE f.projection_scope = NEW.projection_scope
                    AND f.generation = NEW.generation
              )
          )
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete generation receipt');
END;
