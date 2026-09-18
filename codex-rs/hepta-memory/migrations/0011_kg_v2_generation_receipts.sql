-- Persist the canonical knowledge.graph V2 publication receipt alongside the
-- existing byte-compatible SQLite v1 projection receipt. This is append-only
-- qualification/product state; it does not create another fact store.

CREATE TABLE kg_projection_v2_generation_receipts (
    projection_scope TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    source_snapshot_sha256 TEXT NOT NULL CHECK (
        length(source_snapshot_sha256) = 64 AND
        source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    generation_digest TEXT NOT NULL CHECK (
        length(generation_digest) = 64 AND
        generation_digest NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_generation INTEGER,
    predecessor_generation_digest TEXT,
    disposition TEXT NOT NULL CHECK (disposition IN ('published', 'unchanged')),
    publication_digest TEXT NOT NULL CHECK (
        length(publication_digest) = 64 AND
        publication_digest NOT GLOB '*[^0-9a-f]*'
    ),
    PRIMARY KEY (projection_scope, generation),
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_receipts(projection_scope, generation)
        ON DELETE RESTRICT,
    CHECK (
        (generation = 1 AND predecessor_generation IS NULL
         AND predecessor_generation_digest IS NULL)
        OR
        (generation > 1 AND predecessor_generation = generation - 1
         AND predecessor_generation_digest IS NOT NULL
         AND length(predecessor_generation_digest) = 64
         AND predecessor_generation_digest NOT GLOB '*[^0-9a-f]*')
    )
) STRICT;

CREATE TRIGGER kg_projection_v2_generation_receipts_no_update
BEFORE UPDATE ON kg_projection_v2_generation_receipts
BEGIN
    SELECT RAISE(ABORT, 'KG V2 generation receipts are immutable');
END;

CREATE TRIGGER kg_projection_v2_generation_receipts_no_delete
BEFORE DELETE ON kg_projection_v2_generation_receipts
BEGIN
    SELECT RAISE(ABORT, 'KG V2 generation receipts are immutable');
END;
