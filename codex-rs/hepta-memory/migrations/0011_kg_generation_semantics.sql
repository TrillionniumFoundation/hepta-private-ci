-- Canonical hepta-kg V2 semantics for each persisted SQLite projection generation.
-- The physical occurrence projection remains in kg_nodes/kg_edges; this immutable
-- companion binds that materialization to the single deterministic graph kernel.
CREATE TABLE kg_projection_generation_semantics (
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
    publication_sha256 TEXT CHECK (
        publication_sha256 IS NULL OR (
            length(publication_sha256) = 64 AND
            publication_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(
            projection_scope, generation
        ) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER kg_projection_generation_semantics_no_update
BEFORE UPDATE ON kg_projection_generation_semantics BEGIN
    SELECT RAISE(ABORT, 'KG projection generation semantics are immutable');
END;

CREATE TRIGGER kg_projection_generation_semantics_no_delete
BEFORE DELETE ON kg_projection_generation_semantics BEGIN
    SELECT RAISE(ABORT, 'KG projection generation semantics are immutable');
END;

CREATE INDEX kg_projection_generation_semantics_digest_lookup
ON kg_projection_generation_semantics(generation_sha256, projection_scope, generation);

-- Any generation made current after this migration must already have its
-- canonical V2 semantics receipt in the same transaction. Existing current
-- generations remain valid legacy history until the next projection write.
CREATE TRIGGER kg_projection_current_semantics_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NEW.generation > OLD.generation AND NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_semantics s
    WHERE s.projection_scope = NEW.projection_scope
      AND s.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'current KG projection requires canonical generation semantics');
END;
