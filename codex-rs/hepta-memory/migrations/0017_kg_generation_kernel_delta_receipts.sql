-- G17 binds every non-baseline compact generation to the exact canonical
-- hepta-kg transition plan that was validated before publication. The compact
-- owner continues to store immutable revision facts rather than duplicate full
-- graph rows; this receipt records the bounded delta and impact closure selected
-- by the graph kernel for recovery, audit and target-host measurement.

CREATE TABLE kg_projection_generation_kernel_deltas (
    projection_scope TEXT NOT NULL CHECK (
        length(trim(projection_scope)) BETWEEN 1 AND 128 AND
        instr(projection_scope, char(0)) = 0
    ),
    generation INTEGER NOT NULL CHECK (generation > 1),
    predecessor_generation_sha256 TEXT NOT NULL CHECK (
        length(predecessor_generation_sha256) = 64 AND
        predecessor_generation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    generation_sha256 TEXT NOT NULL CHECK (
        length(generation_sha256) = 64 AND
        generation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    delta_mode TEXT NOT NULL CHECK (delta_mode = 'canonical_transition_v1'),
    remove_node_count INTEGER NOT NULL CHECK (
        remove_node_count BETWEEN 0 AND 10000
    ),
    upsert_node_count INTEGER NOT NULL CHECK (
        upsert_node_count BETWEEN 0 AND 10000
    ),
    remove_edge_count INTEGER NOT NULL CHECK (
        remove_edge_count BETWEEN 0 AND 50000
    ),
    upsert_edge_count INTEGER NOT NULL CHECK (
        upsert_edge_count BETWEEN 0 AND 50000
    ),
    impact_node_count INTEGER NOT NULL CHECK (
        impact_node_count BETWEEN 0 AND 10000
    ),
    impact_edge_count INTEGER NOT NULL CHECK (
        impact_edge_count BETWEEN 0 AND 50000
    ),
    full_candidate_oracle_verified INTEGER NOT NULL CHECK (
        full_candidate_oracle_verified = 1
    ),
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
    FOREIGN KEY (projection_scope, generation)
        REFERENCES kg_projection_generation_transitions(
            projection_scope, generation
        ) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER kg_projection_generation_kernel_deltas_no_update
BEFORE UPDATE ON kg_projection_generation_kernel_deltas BEGIN
    SELECT RAISE(ABORT, 'KG generation kernel delta receipts are immutable');
END;

CREATE TRIGGER kg_projection_generation_kernel_deltas_no_delete
BEFORE DELETE ON kg_projection_generation_kernel_deltas BEGIN
    SELECT RAISE(ABORT, 'KG generation kernel delta receipts are immutable');
END;

CREATE INDEX kg_projection_generation_kernel_deltas_predecessor
ON kg_projection_generation_kernel_deltas(
    projection_scope, predecessor_generation_sha256, generation
);

-- A non-baseline compact generation cannot become current until the exact
-- kernel delta is present and bound to both the candidate digest and, whenever
-- a canonical predecessor receipt exists, the predecessor digest. Legacy
-- predecessors without a semantics row remain recoverable, but still require a
-- syntactically valid predecessor digest produced by the reconstructed kernel
-- generation.
CREATE TRIGGER kg_projection_current_kernel_delta_on_update
BEFORE UPDATE OF generation ON kg_projection
WHEN NEW.generation > OLD.generation
 AND NEW.generation > 1
 AND NOT EXISTS (
    SELECT 1
    FROM kg_projection_generation_kernel_deltas delta
    JOIN kg_projection_generation_semantics current_semantics
      ON current_semantics.projection_scope = delta.projection_scope
     AND current_semantics.generation = delta.generation
    WHERE delta.projection_scope = NEW.projection_scope
      AND delta.generation = NEW.generation
      AND delta.generation_sha256 = current_semantics.generation_sha256
      AND (
          NOT EXISTS (
              SELECT 1
              FROM kg_projection_generation_semantics predecessor
              WHERE predecessor.projection_scope = NEW.projection_scope
                AND predecessor.generation = NEW.generation - 1
          )
          OR delta.predecessor_generation_sha256 = (
              SELECT predecessor.generation_sha256
              FROM kg_projection_generation_semantics predecessor
              WHERE predecessor.projection_scope = NEW.projection_scope
                AND predecessor.generation = NEW.generation - 1
          )
      )
 ) BEGIN
    SELECT RAISE(ABORT, 'current KG projection requires a bound kernel delta receipt');
END;
