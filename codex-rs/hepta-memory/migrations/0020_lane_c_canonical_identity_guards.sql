-- SQLite REPLACE may delete conflicting rows without running DELETE triggers
-- when recursive_triggers is off. Reject conflicting inserts before conflict
-- resolution so canonical immutable rows and the current KG pointer retain
-- their existing update/delete invariants. Legitimate owner initialization and
-- source replay use insert-if-absent and keep their existing semantic checks.

CREATE TRIGGER cognitive_meta_existing_insert_guard
BEFORE INSERT ON cognitive_meta
WHEN EXISTS (
    SELECT 1 FROM cognitive_meta prior
    WHERE prior.singleton = NEW.singleton
) BEGIN
    SELECT RAISE(ABORT, 'cognitive_meta existing identity cannot be replaced');
END;

CREATE TRIGGER source_ledger_existing_insert_guard
BEFORE INSERT ON source_ledger
WHEN EXISTS (
    SELECT 1 FROM source_ledger prior
    WHERE prior.source_id = NEW.source_id AND prior.source_revision = NEW.source_revision
) BEGIN
    SELECT RAISE(ABORT, 'source_ledger existing identity cannot be replaced');
END;

CREATE TRIGGER memory_revisions_existing_insert_guard
BEFORE INSERT ON memory_revisions
WHEN EXISTS (
    SELECT 1 FROM memory_revisions prior
    WHERE prior.memory_id = NEW.memory_id AND prior.revision = NEW.revision
) BEGIN
    SELECT RAISE(ABORT, 'memory_revisions existing identity cannot be replaced');
END;

CREATE TRIGGER memory_citations_existing_insert_guard
BEFORE INSERT ON memory_citations
WHEN EXISTS (
    SELECT 1 FROM memory_citations prior
    WHERE prior.memory_id = NEW.memory_id AND prior.memory_revision = NEW.memory_revision
      AND (prior.ordinal = NEW.ordinal OR
           (prior.source_id = NEW.source_id AND prior.source_revision = NEW.source_revision))
) BEGIN
    SELECT RAISE(ABORT, 'memory_citations existing identity cannot be replaced');
END;

CREATE TRIGGER kg_revision_fact_sets_existing_insert_guard
BEFORE INSERT ON kg_revision_fact_sets
WHEN EXISTS (
    SELECT 1 FROM kg_revision_fact_sets prior
    WHERE prior.memory_id = NEW.memory_id AND prior.memory_revision = NEW.memory_revision
) BEGIN
    SELECT RAISE(ABORT, 'kg_revision_fact_sets existing identity cannot be replaced');
END;

CREATE TRIGGER kg_revision_entities_existing_insert_guard
BEFORE INSERT ON kg_revision_entities
WHEN EXISTS (
    SELECT 1 FROM kg_revision_entities prior
    WHERE prior.memory_id = NEW.memory_id AND prior.memory_revision = NEW.memory_revision AND prior.entity_key = NEW.entity_key
) BEGIN
    SELECT RAISE(ABORT, 'kg_revision_entities existing identity cannot be replaced');
END;

CREATE TRIGGER kg_revision_relations_existing_insert_guard
BEFORE INSERT ON kg_revision_relations
WHEN EXISTS (
    SELECT 1 FROM kg_revision_relations prior
    WHERE prior.memory_id = NEW.memory_id AND prior.memory_revision = NEW.memory_revision AND prior.relation_key = NEW.relation_key
) BEGIN
    SELECT RAISE(ABORT, 'kg_revision_relations existing identity cannot be replaced');
END;

CREATE TRIGGER kg_projection_generation_receipts_existing_insert_guard
BEFORE INSERT ON kg_projection_generation_receipts
WHEN EXISTS (
    SELECT 1 FROM kg_projection_generation_receipts prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'kg_projection_generation_receipts existing identity cannot be replaced');
END;

CREATE TRIGGER kg_projection_node_entities_existing_insert_guard
BEFORE INSERT ON kg_projection_node_entities
WHEN EXISTS (
    SELECT 1 FROM kg_projection_node_entities prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation AND prior.node_id = NEW.node_id
) BEGIN
    SELECT RAISE(ABORT, 'kg_projection_node_entities existing identity cannot be replaced');
END;

CREATE TRIGGER kg_nodes_existing_insert_guard
BEFORE INSERT ON kg_nodes
WHEN EXISTS (
    SELECT 1 FROM kg_nodes prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation AND prior.node_id = NEW.node_id
) BEGIN
    SELECT RAISE(ABORT, 'kg_nodes existing identity cannot be replaced');
END;

CREATE TRIGGER kg_edges_existing_insert_guard
BEFORE INSERT ON kg_edges
WHEN EXISTS (
    SELECT 1 FROM kg_edges prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation AND prior.edge_id = NEW.edge_id
) BEGIN
    SELECT RAISE(ABORT, 'kg_edges existing identity cannot be replaced');
END;

CREATE TRIGGER kg_projection_generation_semantics_existing_insert_guard
BEFORE INSERT ON kg_projection_generation_semantics
WHEN EXISTS (
    SELECT 1 FROM kg_projection_generation_semantics prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'kg_projection_generation_semantics existing identity cannot be replaced');
END;

CREATE TRIGGER kg_projection_generation_storage_existing_insert_guard
BEFORE INSERT ON kg_projection_generation_storage
WHEN EXISTS (
    SELECT 1 FROM kg_projection_generation_storage prior
    WHERE prior.projection_scope = NEW.projection_scope AND prior.generation = NEW.generation
) BEGIN
    SELECT RAISE(ABORT, 'kg_projection_generation_storage existing identity cannot be replaced');
END;

CREATE TRIGGER kg_projection_existing_insert_guard
BEFORE INSERT ON kg_projection
WHEN EXISTS (
    SELECT 1 FROM kg_projection prior
    WHERE prior.projection_scope = NEW.projection_scope
) BEGIN
    SELECT RAISE(ABORT, 'kg_projection existing identity cannot be replaced');
END;
