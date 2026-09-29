-- G16 binds every newly published compact generation to an immutable,
-- machine-derived transition/resource receipt. The durable source facts remain
-- authoritative; this receipt proves which trigger revision changed, which
-- predecessor was observed, and the bounded physical size of the write that
-- advanced the current pointer.

CREATE TABLE kg_projection_generation_transitions (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    predecessor_generation INTEGER CHECK (
        predecessor_generation IS NULL OR predecessor_generation > 0
    ),
    predecessor_generation_sha256 TEXT CHECK (
        predecessor_generation_sha256 IS NULL OR (
            length(predecessor_generation_sha256) = 64 AND
            predecessor_generation_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    generation_sha256 TEXT NOT NULL CHECK (
        length(generation_sha256) = 64 AND
        generation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    transition_kind TEXT NOT NULL CHECK (
        transition_kind IN (
            'baseline_full_oracle',
            'delta_full_oracle',
            'delta_legacy_predecessor_full_oracle'
        )
    ),
    verification_mode TEXT NOT NULL CHECK (
        verification_mode = 'full_candidate_oracle_v1'
    ),
    trigger_memory_id TEXT NOT NULL,
    previous_trigger_revision INTEGER CHECK (
        previous_trigger_revision IS NULL OR previous_trigger_revision > 0
    ),
    trigger_memory_revision INTEGER NOT NULL CHECK (trigger_memory_revision > 0),
    previous_entity_support_count INTEGER NOT NULL CHECK (
        previous_entity_support_count BETWEEN 0 AND 10000
    ),
    next_entity_support_count INTEGER NOT NULL CHECK (
        next_entity_support_count BETWEEN 0 AND 10000
    ),
    previous_relation_support_count INTEGER NOT NULL CHECK (
        previous_relation_support_count BETWEEN 0 AND 50000
    ),
    next_relation_support_count INTEGER NOT NULL CHECK (
        next_relation_support_count BETWEEN 0 AND 50000
    ),
    touched_canonical_entity_count INTEGER NOT NULL CHECK (
        touched_canonical_entity_count BETWEEN 0 AND 20000
    ),
    touched_canonical_relation_count INTEGER NOT NULL CHECK (
        touched_canonical_relation_count BETWEEN 0 AND 100000
    ),
    trigger_payload_bytes INTEGER NOT NULL CHECK (
        trigger_payload_bytes BETWEEN 0 AND 4194304
    ),
    full_oracle_verified INTEGER NOT NULL CHECK (full_oracle_verified = 1),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_storage(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_semantics(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    CHECK (
        (
            generation = 1 AND
            predecessor_generation IS NULL AND
            predecessor_generation_sha256 IS NULL AND
            transition_kind = 'baseline_full_oracle'
        ) OR (
            generation > 1 AND
            predecessor_generation = generation - 1 AND
            (
                (
                    predecessor_generation_sha256 IS NOT NULL AND
                    transition_kind = 'delta_full_oracle'
                ) OR (
                    predecessor_generation_sha256 IS NULL AND
                    transition_kind = 'delta_legacy_predecessor_full_oracle'
                )
            )
        )
    )
) STRICT;

CREATE TRIGGER kg_projection_generation_transitions_no_update
BEFORE UPDATE ON kg_projection_generation_transitions BEGIN
    SELECT RAISE(ABORT, 'KG generation transition receipts are immutable');
END;

CREATE TRIGGER kg_projection_generation_transitions_no_delete
BEFORE DELETE ON kg_projection_generation_transitions BEGIN
    SELECT RAISE(ABORT, 'KG generation transition receipts are immutable');
END;

CREATE INDEX kg_projection_generation_transitions_predecessor
ON kg_projection_generation_transitions(
    projection_scope, predecessor_generation, generation
);

-- The complete trigger revision must fit a hard physical write budget before a
-- compact generation can be witnessed. length(CAST(... AS BLOB)) measures UTF-8
-- bytes rather than characters. Any failure aborts the enclosing SQLite
-- transaction, including the source revision and current-pointer update.
CREATE TRIGGER kg_projection_generation_storage_trigger_payload_budget
BEFORE INSERT ON kg_projection_generation_storage
WHEN (
    COALESCE((
        SELECT SUM(
            length(CAST(e.entity_key AS BLOB)) +
            length(CAST(e.canonical_entity_id AS BLOB)) +
            length(CAST(e.entity_type AS BLOB)) +
            length(CAST(e.label AS BLOB)) +
            length(CAST(e.source_id AS BLOB)) + 48
        )
        FROM kg_projection_generation_receipts r
        JOIN kg_revision_entities e
          ON e.memory_id = r.trigger_memory_id
         AND e.memory_revision = r.trigger_memory_revision
        WHERE r.projection_scope = NEW.projection_scope
          AND r.generation = NEW.generation
    ), 0) +
    COALESCE((
        SELECT SUM(
            length(CAST(q.relation_key AS BLOB)) +
            length(CAST(q.canonical_relation_id AS BLOB)) +
            length(CAST(q.from_entity_key AS BLOB)) +
            length(CAST(q.from_canonical_entity_id AS BLOB)) +
            length(CAST(q.to_entity_key AS BLOB)) +
            length(CAST(q.to_canonical_entity_id AS BLOB)) +
            length(CAST(q.relation AS BLOB)) +
            length(CAST(q.source_id AS BLOB)) + 56
        )
        FROM kg_projection_generation_receipts r
        JOIN kg_revision_relations q
          ON q.memory_id = r.trigger_memory_id
         AND q.memory_revision = r.trigger_memory_revision
        WHERE r.projection_scope = NEW.projection_scope
          AND r.generation = NEW.generation
    ), 0)
) > 4194304 BEGIN
    SELECT RAISE(ABORT, 'KG trigger revision exceeds the 4 MiB publication budget');
END;

-- Generate the transition receipt from immutable owner rows. This is an AFTER
-- trigger on the compact storage witness, so callers cannot selectively omit or
-- forge the receipt while still advancing the generation in the same
-- transaction.
CREATE TRIGGER kg_projection_generation_storage_transition_receipt
AFTER INSERT ON kg_projection_generation_storage BEGIN
    INSERT INTO kg_projection_generation_transitions (
        projection_scope,
        generation,
        predecessor_generation,
        predecessor_generation_sha256,
        generation_sha256,
        transition_kind,
        verification_mode,
        trigger_memory_id,
        previous_trigger_revision,
        trigger_memory_revision,
        previous_entity_support_count,
        next_entity_support_count,
        previous_relation_support_count,
        next_relation_support_count,
        touched_canonical_entity_count,
        touched_canonical_relation_count,
        trigger_payload_bytes,
        full_oracle_verified,
        recorded_at_unix_seconds
    )
    SELECT
        NEW.projection_scope,
        NEW.generation,
        CASE WHEN NEW.generation = 1 THEN NULL ELSE NEW.generation - 1 END,
        predecessor.generation_sha256,
        current_semantics.generation_sha256,
        CASE
            WHEN NEW.generation = 1 THEN 'baseline_full_oracle'
            WHEN predecessor.generation_sha256 IS NULL
                THEN 'delta_legacy_predecessor_full_oracle'
            ELSE 'delta_full_oracle'
        END,
        'full_candidate_oracle_v1',
        receipt.trigger_memory_id,
        (
            SELECT prior.trigger_memory_revision
            FROM kg_projection_generation_receipts prior
            WHERE prior.projection_scope = NEW.projection_scope
              AND prior.trigger_memory_id = receipt.trigger_memory_id
              AND prior.generation < NEW.generation
            ORDER BY prior.generation DESC
            LIMIT 1
        ),
        receipt.trigger_memory_revision,
        COALESCE((
            SELECT COUNT(*)
            FROM kg_revision_entities old_entity
            WHERE old_entity.memory_id = receipt.trigger_memory_id
              AND old_entity.memory_revision = (
                  SELECT prior.trigger_memory_revision
                  FROM kg_projection_generation_receipts prior
                  WHERE prior.projection_scope = NEW.projection_scope
                    AND prior.trigger_memory_id = receipt.trigger_memory_id
                    AND prior.generation < NEW.generation
                  ORDER BY prior.generation DESC
                  LIMIT 1
              )
        ), 0),
        (
            SELECT COUNT(*)
            FROM kg_revision_entities next_entity
            WHERE next_entity.memory_id = receipt.trigger_memory_id
              AND next_entity.memory_revision = receipt.trigger_memory_revision
        ),
        COALESCE((
            SELECT COUNT(*)
            FROM kg_revision_relations old_relation
            WHERE old_relation.memory_id = receipt.trigger_memory_id
              AND old_relation.memory_revision = (
                  SELECT prior.trigger_memory_revision
                  FROM kg_projection_generation_receipts prior
                  WHERE prior.projection_scope = NEW.projection_scope
                    AND prior.trigger_memory_id = receipt.trigger_memory_id
                    AND prior.generation < NEW.generation
                  ORDER BY prior.generation DESC
                  LIMIT 1
              )
        ), 0),
        (
            SELECT COUNT(*)
            FROM kg_revision_relations next_relation
            WHERE next_relation.memory_id = receipt.trigger_memory_id
              AND next_relation.memory_revision = receipt.trigger_memory_revision
        ),
        (
            SELECT COUNT(*)
            FROM (
                SELECT old_entity.canonical_entity_id
                FROM kg_revision_entities old_entity
                WHERE old_entity.memory_id = receipt.trigger_memory_id
                  AND old_entity.memory_revision = (
                      SELECT prior.trigger_memory_revision
                      FROM kg_projection_generation_receipts prior
                      WHERE prior.projection_scope = NEW.projection_scope
                        AND prior.trigger_memory_id = receipt.trigger_memory_id
                        AND prior.generation < NEW.generation
                      ORDER BY prior.generation DESC
                      LIMIT 1
                  )
                UNION
                SELECT next_entity.canonical_entity_id
                FROM kg_revision_entities next_entity
                WHERE next_entity.memory_id = receipt.trigger_memory_id
                  AND next_entity.memory_revision = receipt.trigger_memory_revision
            ) AS touched_entities
        ),
        (
            SELECT COUNT(*)
            FROM (
                SELECT old_relation.canonical_relation_id
                FROM kg_revision_relations old_relation
                WHERE old_relation.memory_id = receipt.trigger_memory_id
                  AND old_relation.memory_revision = (
                      SELECT prior.trigger_memory_revision
                      FROM kg_projection_generation_receipts prior
                      WHERE prior.projection_scope = NEW.projection_scope
                        AND prior.trigger_memory_id = receipt.trigger_memory_id
                        AND prior.generation < NEW.generation
                      ORDER BY prior.generation DESC
                      LIMIT 1
                  )
                UNION
                SELECT next_relation.canonical_relation_id
                FROM kg_revision_relations next_relation
                WHERE next_relation.memory_id = receipt.trigger_memory_id
                  AND next_relation.memory_revision = receipt.trigger_memory_revision
            ) AS touched_relations
        ),
        COALESCE((
            SELECT SUM(
                length(CAST(e.entity_key AS BLOB)) +
                length(CAST(e.canonical_entity_id AS BLOB)) +
                length(CAST(e.entity_type AS BLOB)) +
                length(CAST(e.label AS BLOB)) +
                length(CAST(e.source_id AS BLOB)) + 48
            )
            FROM kg_revision_entities e
            WHERE e.memory_id = receipt.trigger_memory_id
              AND e.memory_revision = receipt.trigger_memory_revision
        ), 0) +
        COALESCE((
            SELECT SUM(
                length(CAST(q.relation_key AS BLOB)) +
                length(CAST(q.canonical_relation_id AS BLOB)) +
                length(CAST(q.from_entity_key AS BLOB)) +
                length(CAST(q.from_canonical_entity_id AS BLOB)) +
                length(CAST(q.to_entity_key AS BLOB)) +
                length(CAST(q.to_canonical_entity_id AS BLOB)) +
                length(CAST(q.relation AS BLOB)) +
                length(CAST(q.source_id AS BLOB)) + 56
            )
            FROM kg_revision_relations q
            WHERE q.memory_id = receipt.trigger_memory_id
              AND q.memory_revision = receipt.trigger_memory_revision
        ), 0),
        1,
        unixepoch()
    FROM kg_projection_generation_receipts receipt
    JOIN kg_projection_generation_semantics current_semantics
      ON current_semantics.projection_scope = receipt.projection_scope
     AND current_semantics.generation = receipt.generation
    LEFT JOIN kg_projection_generation_semantics predecessor
      ON predecessor.projection_scope = receipt.projection_scope
     AND predecessor.generation = receipt.generation - 1
    WHERE receipt.projection_scope = NEW.projection_scope
      AND receipt.generation = NEW.generation;
END;

-- A post-G16 generation can become current only after the automatic transition
-- receipt exists. Existing pre-migration current generations remain readable;
-- the next advancing transaction must satisfy this gate.
CREATE TRIGGER kg_projection_current_transition_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NEW.generation > OLD.generation AND NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_transitions transition_receipt
    WHERE transition_receipt.projection_scope = NEW.projection_scope
      AND transition_receipt.generation = NEW.generation
      AND transition_receipt.generation_sha256 = (
          SELECT semantics.generation_sha256
          FROM kg_projection_generation_semantics semantics
          WHERE semantics.projection_scope = NEW.projection_scope
            AND semantics.generation = NEW.generation
      )
) BEGIN
    SELECT RAISE(ABORT, 'current KG projection requires a bound transition receipt');
END;
