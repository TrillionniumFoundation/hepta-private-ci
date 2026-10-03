-- Count exact-cut immutable fact supports after selecting one revision per
-- memory identity. A genuinely empty fact table has an exact count of zero;
-- inspect the table itself rather than trusting a declared receipt count.
DROP TRIGGER kg_projection_generation_storage_counts_match;

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
          CASE WHEN EXISTS (SELECT 1 FROM kg_revision_entities LIMIT 1)
          THEN (
              WITH selected_memories AS (
                  SELECT DISTINCT projection_scope, trigger_memory_id
                  FROM kg_projection_generation_receipts
                  WHERE projection_scope = NEW.projection_scope
                    AND generation <= NEW.generation
              ), selected_heads AS (
                  SELECT h.trigger_memory_id AS memory_id,
                         h.trigger_memory_revision AS memory_revision
                  FROM selected_memories p
                  JOIN kg_projection_generation_receipts h
                    ON h.projection_scope = p.projection_scope
                   AND h.trigger_memory_id = p.trigger_memory_id
                   AND h.generation = (
                       SELECT MAX(x.generation)
                       FROM kg_projection_generation_receipts x
                       WHERE x.projection_scope = p.projection_scope
                         AND x.trigger_memory_id = p.trigger_memory_id
                         AND x.generation <= NEW.generation
                   )
              )
              SELECT COUNT(*)
              FROM selected_heads h
              JOIN memory_revisions m
                ON m.memory_id = h.memory_id
               AND m.revision = h.memory_revision
              JOIN kg_revision_entities e
                ON e.memory_id = h.memory_id
               AND e.memory_revision = h.memory_revision
              WHERE m.verification = 'verified'
                AND m.lifecycle = 'active'
          )
          ELSE 0 END
      )
      AND r.edge_count = (
          CASE WHEN EXISTS (SELECT 1 FROM kg_revision_relations LIMIT 1)
          THEN (
              WITH selected_memories AS (
                  SELECT DISTINCT projection_scope, trigger_memory_id
                  FROM kg_projection_generation_receipts
                  WHERE projection_scope = NEW.projection_scope
                    AND generation <= NEW.generation
              ), selected_heads AS (
                  SELECT h.trigger_memory_id AS memory_id,
                         h.trigger_memory_revision AS memory_revision
                  FROM selected_memories p
                  JOIN kg_projection_generation_receipts h
                    ON h.projection_scope = p.projection_scope
                   AND h.trigger_memory_id = p.trigger_memory_id
                   AND h.generation = (
                       SELECT MAX(x.generation)
                       FROM kg_projection_generation_receipts x
                       WHERE x.projection_scope = p.projection_scope
                         AND x.trigger_memory_id = p.trigger_memory_id
                         AND x.generation <= NEW.generation
                   )
              )
              SELECT COUNT(*)
              FROM selected_heads h
              JOIN memory_revisions m
                ON m.memory_id = h.memory_id
               AND m.revision = h.memory_revision
              JOIN kg_revision_relations q
                ON q.memory_id = h.memory_id
               AND q.memory_revision = h.memory_revision
              WHERE m.verification = 'verified'
                AND m.lifecycle = 'active'
          )
          ELSE 0 END
      )
) BEGIN
    SELECT RAISE(ABORT, 'KG compact generation counts do not match immutable revision facts');
END;
