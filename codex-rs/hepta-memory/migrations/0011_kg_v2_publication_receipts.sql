-- G11 binds the rebuildable SQLite projection to the canonical hepta-kg V2
-- generation semantics. Source facts remain owned by the existing cognitive
-- ledger; this table stores only immutable projection/publication receipts.

CREATE TABLE kg_projection_v2_publications (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 0),
    source_snapshot_digest TEXT NOT NULL CHECK (
        length(source_snapshot_digest) = 64 AND
        source_snapshot_digest NOT GLOB '*[^0-9a-f]*'
    ),
    generation_vector_digest TEXT NOT NULL CHECK (
        length(generation_vector_digest) = 64 AND
        generation_vector_digest NOT GLOB '*[^0-9a-f]*'
    ),
    graph_profile_digest TEXT NOT NULL CHECK (
        length(graph_profile_digest) = 64 AND
        graph_profile_digest NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_generation INTEGER,
    predecessor_digest TEXT,
    generation_digest TEXT NOT NULL CHECK (
        length(generation_digest) = 64 AND
        generation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    publication_digest TEXT NOT NULL CHECK (
        length(publication_digest) = 64 AND
        publication_digest NOT GLOB '*[^0-9a-f]*'
    ),
    sqlite_output_sha256 TEXT NOT NULL CHECK (
        length(sqlite_output_sha256) = 64 AND
        sqlite_output_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    node_count INTEGER NOT NULL CHECK (node_count BETWEEN 0 AND 10000),
    edge_count INTEGER NOT NULL CHECK (edge_count BETWEEN 0 AND 50000),
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(
            projection_scope, generation
        ) ON DELETE RESTRICT,
    CHECK (
        (generation = 1 AND predecessor_generation IS NULL AND predecessor_digest IS NULL) OR
        (
            generation > 1 AND
            predecessor_generation = generation - 1 AND
            length(predecessor_digest) = 64 AND
            predecessor_digest NOT GLOB '*[^0-9a-f]*'
        )
    )
) STRICT;

CREATE TRIGGER kg_projection_v2_publications_counts_match
BEFORE INSERT ON kg_projection_v2_publications
WHEN NOT EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts AS r
    WHERE r.projection_scope = NEW.projection_scope
      AND r.generation = NEW.generation
      AND r.input_heads_sha256 = NEW.source_snapshot_digest
      AND r.output_sha256 = NEW.sqlite_output_sha256
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
    SELECT RAISE(ABORT, 'KG V2 publication requires a complete persisted generation');
END;

CREATE TRIGGER kg_projection_v2_publications_no_update
BEFORE UPDATE ON kg_projection_v2_publications BEGIN
    SELECT RAISE(ABORT, 'KG V2 publication receipts are immutable');
END;

CREATE TRIGGER kg_projection_v2_publications_no_delete
BEFORE DELETE ON kg_projection_v2_publications BEGIN
    SELECT RAISE(ABORT, 'KG V2 publication receipts are immutable');
END;

CREATE INDEX kg_projection_v2_publications_digest_lookup
ON kg_projection_v2_publications(generation_digest, projection_scope, generation);

-- From G11 onward a mutable current pointer may select only a generation that
-- has both the physical SQLite completeness receipt and the canonical V2
-- publication receipt. Existing pointers are certified by the Rust open path
-- before store verification; no legacy digest is fabricated in SQL.
DROP TRIGGER kg_projection_current_receipt_on_insert;
DROP TRIGGER kg_projection_current_receipt_on_update;

CREATE TRIGGER kg_projection_current_receipt_on_insert
BEFORE INSERT ON kg_projection
WHEN NEW.generation > 0 AND NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_receipts AS r
    JOIN kg_projection_v2_publications AS v
      ON v.projection_scope = r.projection_scope
     AND v.generation = r.generation
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
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete V2-certified generation');
END;

CREATE TRIGGER kg_projection_current_receipt_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_receipts AS r
    JOIN kg_projection_v2_publications AS v
      ON v.projection_scope = r.projection_scope
     AND v.generation = r.generation
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
    SELECT RAISE(ABORT, 'KG projection current pointer requires a complete V2-certified generation');
END;
