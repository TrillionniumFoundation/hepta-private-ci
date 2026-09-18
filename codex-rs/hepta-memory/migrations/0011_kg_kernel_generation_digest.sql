-- Bind every newly published SQLite KG generation to the canonical
-- codex-hepta-kg V2 generation digest. Historical receipts remain readable:
-- they predate the canonical-kernel composition and therefore retain NULL.

ALTER TABLE kg_projection_generation_receipts
ADD COLUMN kernel_generation_sha256 TEXT
CHECK (
    kernel_generation_sha256 IS NULL OR (
        length(kernel_generation_sha256) = 64 AND
        kernel_generation_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);
