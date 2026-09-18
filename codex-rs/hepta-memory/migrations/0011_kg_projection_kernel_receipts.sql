-- Bind every durable cognitive KG generation to the canonical hepta-kg V2
-- generation/publication semantics without replacing the existing SQLite owner.

CREATE TABLE kg_projection_kernel_receipts (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    source_snapshot_sha256 TEXT NOT NULL CHECK (
        length(source_snapshot_sha256) = 64 AND
        source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    generation_vector_sha256 TEXT NOT NULL CHECK (
        length(generation_vector_sha256) = 64 AND
        generation_vector_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    graph_profile_sha256 TEXT NOT NULL CHECK (
        length(graph_profile_sha256) = 64 AND
        graph_profile_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    generation_sha256 TEXT NOT NULL CHECK (
        length(generation_sha256) = 64 AND
        generation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_generation INTEGER,
    predecessor_sha256 TEXT CHECK (
        predecessor_sha256 IS NULL OR
        (
            length(predecessor_sha256) = 64 AND
            predecessor_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    publication_sha256 TEXT NOT NULL CHECK (
        length(publication_sha256) = 64 AND
        publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    disposition TEXT NOT NULL CHECK (disposition IN ('published', 'unchanged')),
    node_count INTEGER NOT NULL CHECK (node_count BETWEEN 0 AND 10000),
    edge_count INTEGER NOT NULL CHECK (edge_count BETWEEN 0 AND 50000),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    CHECK (
        (generation = 1 AND predecessor_generation IS NULL AND predecessor_sha256 IS NULL) OR
        (generation > 1 AND predecessor_generation = generation - 1 AND predecessor_sha256 IS NOT NULL)
    )
) STRICT;

CREATE TRIGGER kg_projection_kernel_receipts_match_materialization
BEFORE INSERT ON kg_projection_kernel_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_receipts AS r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND r.input_heads_sha256 = NEW.source_snapshot_sha256
      AND r.node_count = NEW.node_count
      AND r.edge_count = NEW.edge_count
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
) BEGIN
    SELECT RAISE(ABORT, 'hepta-kg receipt requires the exact durable materialization');
END;

CREATE TRIGGER kg_projection_kernel_receipts_no_update
BEFORE UPDATE ON kg_projection_kernel_receipts BEGIN
    SELECT RAISE(ABORT, 'hepta-kg projection receipts are immutable');
END;

CREATE TRIGGER kg_projection_kernel_receipts_no_delete
BEFORE DELETE ON kg_projection_kernel_receipts BEGIN
    SELECT RAISE(ABORT, 'hepta-kg projection receipts are immutable');
END;

CREATE UNIQUE INDEX kg_projection_kernel_receipts_generation_digest
ON kg_projection_kernel_receipts(projection_scope, generation_sha256);

CREATE TRIGGER kg_projection_kernel_receipt_on_insert
BEFORE INSERT ON kg_projection
WHEN NEW.generation > 0 AND NOT EXISTS (
    SELECT 1 FROM kg_projection_kernel_receipts AS k
    WHERE k.projection_scope = NEW.projection_scope
      AND k.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'KG current pointer requires a hepta-kg generation receipt');
END;

CREATE TRIGGER kg_projection_kernel_receipt_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NEW.generation > 0 AND NOT EXISTS (
    SELECT 1 FROM kg_projection_kernel_receipts AS k
    WHERE k.projection_scope = NEW.projection_scope
      AND k.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'KG current pointer requires a hepta-kg generation receipt');
END;
