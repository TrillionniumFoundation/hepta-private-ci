use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgePublicationReceiptV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::publish_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::CognitiveProjectionReceipt;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryRevisionRecord;
use crate::ProjectionGeneration;
use crate::SourceRevisionId;
use crate::cognitive_intelligence_writer::CanonicalFactSet;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_intelligence_writer::canonical_relation_id;
use crate::cognitive_intelligence_writer::occurrence_edge_id;
use crate::cognitive_intelligence_writer::occurrence_node_id;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

pub(crate) const MAX_SCOPE_HEADS: usize = 10_000;
pub(crate) const MAX_SCOPE_NODES: usize = 10_000;
pub(crate) const MAX_SCOPE_EDGES: usize = 50_000;
pub(crate) const MAX_PROJECTION_SCOPES: usize = 10_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ProjectionHead {
    pub(crate) memory_id: String,
    pub(crate) revision: i64,
    pub(crate) content_sha256: String,
    pub(crate) verification: String,
    pub(crate) lifecycle: String,
    pub(crate) fact_set_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ProjectionNode {
    pub(crate) node_id: String,
    pub(crate) canonical_entity_id: String,
    pub(crate) entity_type: String,
    pub(crate) label: String,
    pub(crate) valid_from: i64,
    pub(crate) valid_to: Option<i64>,
    pub(crate) memory_id: String,
    pub(crate) memory_revision: i64,
    pub(crate) source_id: String,
    pub(crate) source_revision: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ProjectionEdge {
    pub(crate) edge_id: String,
    pub(crate) canonical_relation_id: String,
    pub(crate) from_node_id: String,
    pub(crate) to_node_id: String,
    pub(crate) relation: String,
    pub(crate) valid_from: i64,
    pub(crate) valid_to: Option<i64>,
    pub(crate) memory_id: String,
    pub(crate) memory_revision: i64,
    pub(crate) source_id: String,
    pub(crate) source_revision: i64,
}

impl CognitiveStore {
    /// Materializes a complete exact-scope projection inside the product
    /// mutation transaction. Only verified active current heads participate;
    /// every historical generation remains append-only.
    pub(crate) async fn refresh_scope_projection_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        scope: &CognitiveScope,
        trigger_memory: &MemoryRevisionRecord,
        trigger_source: &SourceRevisionId,
        trigger_facts: &CanonicalFactSet,
    ) -> Result<CognitiveProjectionReceipt, CognitiveStoreError> {
        let projection_scope = scope.projection_key();
        let projection_scope_exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(
                 SELECT 1 FROM kg_projection WHERE projection_scope = ?
             )",
        )
        .bind(&projection_scope)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if !projection_scope_exists {
            let projection_scope_count: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM kg_projection")
                    .fetch_one(&mut **transaction)
                    .await
                    .map_err(unavailable)?;
            if projection_scope_count >= to_i64_len(MAX_PROJECTION_SCOPES, "projection scope")? {
                return Err(CognitiveStoreError::Invalid(format!(
                    "cognitive store exceeds the {MAX_PROJECTION_SCOPES}-projection-scope limit"
                )));
            }
        }
        let (scope_kind, workspace_sha256) = scope.database_parts();
        let head_rows = sqlx::query(
            "SELECT r.memory_id, r.revision, r.content_sha256,
                    r.verification, r.lifecycle, s.fact_set_sha256,
                    s.entity_count, s.relation_count,
                    (SELECT COUNT(*) FROM kg_revision_entities e
                     WHERE e.memory_id = r.memory_id
                       AND e.memory_revision = r.revision) AS actual_entity_count,
                    (SELECT COUNT(*) FROM kg_revision_relations q
                     WHERE q.memory_id = r.memory_id
                       AND q.memory_revision = r.revision) AS actual_relation_count
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             LEFT JOIN kg_revision_fact_sets s
               ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
             ORDER BY r.memory_id LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(limit_plus_one(MAX_SCOPE_HEADS)?)
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if head_rows.len() > MAX_SCOPE_HEADS {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_HEADS}-head scope limit"
            )));
        }
        let mut heads = Vec::with_capacity(head_rows.len());
        for row in head_rows {
            let fact_set_sha256: Option<String> =
                row.try_get("fact_set_sha256").map_err(unavailable)?;
            let Some(fact_set_sha256) = fact_set_sha256 else {
                return Err(CognitiveStoreError::Corrupt(
                    "current memory head has no immutable KG fact-set receipt".to_string(),
                ));
            };
            let entity_count: i64 = row.try_get("entity_count").map_err(unavailable)?;
            let relation_count: i64 = row.try_get("relation_count").map_err(unavailable)?;
            let actual_entity_count: i64 =
                row.try_get("actual_entity_count").map_err(unavailable)?;
            let actual_relation_count: i64 =
                row.try_get("actual_relation_count").map_err(unavailable)?;
            if entity_count != actual_entity_count || relation_count != actual_relation_count {
                return Err(CognitiveStoreError::Corrupt(
                    "current memory head has an incomplete immutable KG fact set".to_string(),
                ));
            }
            Sha256Digest::parse(fact_set_sha256.clone()).map_err(CognitiveStoreError::Corrupt)?;
            heads.push(ProjectionHead {
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                revision: row.try_get("revision").map_err(unavailable)?,
                content_sha256: row.try_get("content_sha256").map_err(unavailable)?,
                verification: row.try_get("verification").map_err(unavailable)?,
                lifecycle: row.try_get("lifecycle").map_err(unavailable)?,
                fact_set_sha256,
            });
        }
        let input_heads_sha256 = input_heads_digest(&projection_scope, &heads);

        let entity_rows = sqlx::query(
            "SELECT e.memory_id, e.memory_revision, e.entity_key,
                    e.canonical_entity_id, e.entity_type, e.label,
                    e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                    e.source_id, e.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_entities e
               ON e.memory_id = r.memory_id AND e.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY e.memory_id, e.memory_revision, e.entity_key LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(limit_plus_one(MAX_SCOPE_NODES)?)
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if entity_rows.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_NODES}-node scope limit"
            )));
        }
        let mut canonical_shapes = BTreeMap::<String, (String, String)>::new();
        let mut nodes = Vec::with_capacity(entity_rows.len());
        for row in entity_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let entity_key: String = row.try_get("entity_key").map_err(unavailable)?;
            let stored_canonical_entity_id: String =
                row.try_get("canonical_entity_id").map_err(unavailable)?;
            let expected_canonical_entity_id =
                canonical_entity_id(&self.owner_agent_id, scope, &entity_key);
            if stored_canonical_entity_id != expected_canonical_entity_id {
                return Err(CognitiveStoreError::Corrupt(
                    "KG entity identity does not match its canonical scoped key".to_string(),
                ));
            }
            let entity_type: String = row.try_get("entity_type").map_err(unavailable)?;
            let label: String = row.try_get("label").map_err(unavailable)?;
            if let Some(shape) = canonical_shapes.get(&stored_canonical_entity_id) {
                if shape != &(entity_type.clone(), label.clone()) {
                    return Err(CognitiveStoreError::Conflict(format!(
                        "active KG supports disagree on type or label for {stored_canonical_entity_id}"
                    )));
                }
            } else {
                canonical_shapes.insert(
                    stored_canonical_entity_id.clone(),
                    (entity_type.clone(), label.clone()),
                );
            }
            nodes.push(ProjectionNode {
                node_id: occurrence_node_id(&memory_id, memory_revision, &entity_key),
                canonical_entity_id: stored_canonical_entity_id,
                entity_type,
                label,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id,
                memory_revision,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }

        let relation_rows = sqlx::query(
            "SELECT q.memory_id, q.memory_revision, q.relation_key,
                    q.canonical_relation_id, q.from_entity_key,
                    q.from_canonical_entity_id, q.to_entity_key,
                    q.to_canonical_entity_id, q.relation,
                    q.valid_from_unix_seconds, q.valid_to_unix_seconds,
                    q.source_id, q.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_relations q
               ON q.memory_id = r.memory_id AND q.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if relation_rows.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Invalid(format!(
                "KG projection exceeds the {MAX_SCOPE_EDGES}-edge scope limit"
            )));
        }
        let mut edges = Vec::with_capacity(relation_rows.len());
        for row in relation_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
            let from_entity_key: String = row.try_get("from_entity_key").map_err(unavailable)?;
            let to_entity_key: String = row.try_get("to_entity_key").map_err(unavailable)?;
            let from_canonical_entity_id: String = row
                .try_get("from_canonical_entity_id")
                .map_err(unavailable)?;
            let to_canonical_entity_id: String =
                row.try_get("to_canonical_entity_id").map_err(unavailable)?;
            let relation: String = row.try_get("relation").map_err(unavailable)?;
            let stored_canonical_relation_id: String =
                row.try_get("canonical_relation_id").map_err(unavailable)?;
            let expected_canonical_relation_id = canonical_relation_id(
                &self.owner_agent_id,
                scope,
                &from_canonical_entity_id,
                &relation,
                &to_canonical_entity_id,
            );
            if stored_canonical_relation_id != expected_canonical_relation_id {
                return Err(CognitiveStoreError::Corrupt(
                    "KG relation identity does not match its canonical endpoints".to_string(),
                ));
            }
            edges.push(ProjectionEdge {
                edge_id: occurrence_edge_id(&memory_id, memory_revision, &relation_key),
                canonical_relation_id: stored_canonical_relation_id,
                from_node_id: occurrence_node_id(&memory_id, memory_revision, &from_entity_key),
                to_node_id: occurrence_node_id(&memory_id, memory_revision, &to_entity_key),
                relation,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id,
                memory_revision,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }
        let output_sha256 = output_digest(&projection_scope, &nodes, &edges);

        sqlx::query(
            "INSERT INTO kg_projection (projection_scope, generation)
             VALUES (?, 0) ON CONFLICT(projection_scope) DO NOTHING",
        )
        .bind(&projection_scope)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let current: i64 =
            sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
                .bind(&projection_scope)
                .fetch_one(&mut **transaction)
                .await
                .map_err(unavailable)?;
        let next = current
            .checked_add(1)
            .ok_or_else(|| CognitiveStoreError::Corrupt("KG generation overflow".to_string()))?;

        // The product projection is admitted only after the exact same SQLite
        // rows pass the canonical hepta-kg V2 generation semantics. For an
        // existing predecessor we additionally derive and replay the minimal
        // delta and require byte-for-byte semantic equality with a full rebuild.
        let predecessor_v2 = if current > 0 {
            let (predecessor_input, predecessor_nodes, predecessor_edges) =
                load_persisted_projection_tx(transaction, &projection_scope, current).await?;
            Some(build_v2_generation(
                current,
                &projection_scope,
                &predecessor_input,
                &predecessor_nodes,
                &predecessor_edges,
            )?)
        } else {
            None
        };
        let generation_v2 =
            build_v2_generation(next, &projection_scope, &input_heads_sha256, &nodes, &edges)?;
        if generation_v2.nodes.len() != nodes.len() || generation_v2.edges.len() != edges.len() {
            return Err(CognitiveStoreError::Corrupt(
                "canonical KG V2 generation changed the eligible SQLite projection cardinality"
                    .to_string(),
            ));
        }
        let publication_v2 =
            qualify_v2_transition(predecessor_v2.as_ref(), &generation_v2)?;

        sqlx::query(
            "INSERT INTO kg_projection_generation_receipts (
                projection_scope, generation, trigger_memory_id,
                trigger_memory_revision, fact_set_sha256, input_heads_sha256,
                output_sha256, entity_count, relation_count, node_count,
                edge_count, recorded_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
        )
        .bind(&projection_scope)
        .bind(next)
        .bind(trigger_memory.id.memory_id.as_str())
        .bind(to_i64(trigger_memory.id.revision, "memory revision")?)
        .bind(trigger_facts.digest.as_str())
        .bind(input_heads_sha256.as_str())
        .bind(output_sha256.as_str())
        .bind(to_i64_len(trigger_facts.entities.len(), "entity count")?)
        .bind(to_i64_len(trigger_facts.relations.len(), "relation count")?)
        .bind(to_i64_len(nodes.len(), "projection node count")?)
        .bind(to_i64_len(edges.len(), "projection edge count")?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        for node in &nodes {
            sqlx::query(
                "INSERT INTO kg_nodes (
                    projection_scope, generation, node_id, entity_type, label,
                    valid_from_unix_seconds, valid_to_unix_seconds, memory_id,
                    memory_revision, source_id, source_revision
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&projection_scope)
            .bind(next)
            .bind(&node.node_id)
            .bind(&node.entity_type)
            .bind(&node.label)
            .bind(node.valid_from)
            .bind(node.valid_to)
            .bind(&node.memory_id)
            .bind(node.memory_revision)
            .bind(&node.source_id)
            .bind(node.source_revision)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
            sqlx::query(
                "INSERT INTO kg_entity_fts (
                    projection_scope, generation, node_id, entity_type, label
                 ) VALUES (?, ?, ?, ?, ?)",
            )
            .bind(&projection_scope)
            .bind(next)
            .bind(&node.node_id)
            .bind(&node.entity_type)
            .bind(&node.label)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
            sqlx::query(
                "INSERT INTO kg_projection_node_entities (
                    projection_scope, generation, node_id, canonical_entity_id
                 ) VALUES (?, ?, ?, ?)",
            )
            .bind(&projection_scope)
            .bind(next)
            .bind(&node.node_id)
            .bind(&node.canonical_entity_id)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        }
        for edge in &edges {
            sqlx::query(
                "INSERT INTO kg_edges (
                    projection_scope, generation, edge_id, from_node_id,
                    to_node_id, relation, valid_from_unix_seconds,
                    valid_to_unix_seconds, memory_id, memory_revision,
                    source_id, source_revision
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&projection_scope)
            .bind(next)
            .bind(&edge.edge_id)
            .bind(&edge.from_node_id)
            .bind(&edge.to_node_id)
            .bind(&edge.relation)
            .bind(edge.valid_from)
            .bind(edge.valid_to)
            .bind(&edge.memory_id)
            .bind(edge.memory_revision)
            .bind(&edge.source_id)
            .bind(edge.source_revision)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        }
        insert_v2_publication_tx(
            transaction,
            &projection_scope,
            &generation_v2,
            &publication_v2,
        )
        .await?;

        let updated = sqlx::query(
            "UPDATE kg_projection SET generation = ?
             WHERE projection_scope = ? AND generation = ?",
        )
        .bind(next)
        .bind(&projection_scope)
        .bind(current)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(CognitiveStoreError::Conflict(
                "KG projection generation changed during product write".to_string(),
            ));
        }
        if trigger_memory.citations.first() != Some(trigger_source) {
            return Err(CognitiveStoreError::Corrupt(
                "projection trigger source is not the revision's exact citation".to_string(),
            ));
        }
        Ok(CognitiveProjectionReceipt {
            generation: ProjectionGeneration(
                u64::try_from(next).map_err(|_| {
                    CognitiveStoreError::Corrupt("negative KG generation".to_string())
                })?,
            ),
            fact_set_sha256: trigger_facts.digest.clone(),
            input_heads_sha256,
            output_sha256,
            entity_count: u64::try_from(trigger_facts.entities.len()).unwrap_or(u64::MAX),
            relation_count: u64::try_from(trigger_facts.relations.len()).unwrap_or(u64::MAX),
            node_count: u64::try_from(nodes.len()).unwrap_or(u64::MAX),
            edge_count: u64::try_from(edges.len()).unwrap_or(u64::MAX),
        })
    }
}


const KG_V2_GRAPH_PROFILE: &[u8] =
    b"hepta:cognitive:sqlite-kg-profile:v2:occurrence-identity+exact-predicate";

pub(crate) async fn certify_current_v2_publications(
    pool: &SqlitePool,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool.begin().await.map_err(unavailable)?;
    let rows = sqlx::query(
        "SELECT p.projection_scope, p.generation
         FROM kg_projection p
         LEFT JOIN kg_projection_v2_publications v
           ON v.projection_scope = p.projection_scope
          AND v.generation = p.generation
         WHERE p.generation > 0 AND v.projection_scope IS NULL
         ORDER BY p.projection_scope LIMIT ?",
    )
    .bind(limit_plus_one(MAX_PROJECTION_SCOPES)?)
    .fetch_all(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if rows.len() > MAX_PROJECTION_SCOPES {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cognitive store exceeds the {MAX_PROJECTION_SCOPES}-projection-scope certification limit"
        )));
    }

    for row in rows {
        let projection_scope: String = row.try_get("projection_scope").map_err(unavailable)?;
        let generation: i64 = row.try_get("generation").map_err(unavailable)?;
        let (input_heads, nodes, edges) =
            load_persisted_projection_tx(&mut transaction, &projection_scope, generation).await?;
        let candidate =
            build_v2_generation(generation, &projection_scope, &input_heads, &nodes, &edges)?;
        let predecessor = if generation > 1 {
            let predecessor_generation = generation - 1;
            let (previous_input, previous_nodes, previous_edges) = load_persisted_projection_tx(
                &mut transaction,
                &projection_scope,
                predecessor_generation,
            )
            .await?;
            Some(build_v2_generation(
                predecessor_generation,
                &projection_scope,
                &previous_input,
                &previous_nodes,
                &previous_edges,
            )?)
        } else {
            None
        };
        let publication = qualify_v2_transition(predecessor.as_ref(), &candidate)?;
        insert_v2_publication_tx(
            &mut transaction,
            &projection_scope,
            &candidate,
            &publication,
        )
        .await?;
    }
    transaction.commit().await.map_err(unavailable)?;
    Ok(())
}

pub(crate) fn build_v2_generation(
    generation: i64,
    scope: &str,
    input_heads_sha256: &Sha256Digest,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let generation_u64 = u64::try_from(generation)
        .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?;
    let generation = Generation::new(generation_u64)
        .map_err(|error| CognitiveStoreError::Corrupt(format!("invalid KG generation: {error}")))?;
    let source_snapshot_digest = digest32_from_sha256(input_heads_sha256, "input-head snapshot")?;
    let generation_vector_digest = framed_digest32(
        b"hepta:cognitive:kg-generation-vector:v1",
        &[scope.as_bytes(), input_heads_sha256.as_str().as_bytes()],
    );
    let graph_profile_digest = Digest32::of_bytes(KG_V2_GRAPH_PROFILE);

    let nodes = nodes
        .iter()
        .map(projection_node_v2)
        .collect::<Result<Vec<_>, _>>()?;
    let edges = edges
        .iter()
        .map(projection_edge_v2)
        .collect::<Result<Vec<_>, _>>()?;

    build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest,
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "SQLite KG projection failed canonical V2 generation: {error}"
        ))
    })
}

pub(crate) fn qualify_v2_transition(
    predecessor: Option<&KnowledgeGenerationV2>,
    candidate: &KnowledgeGenerationV2,
) -> Result<KnowledgePublicationReceiptV2, CognitiveStoreError> {
    if let Some(predecessor) = predecessor {
        let delta = derive_v2_delta(predecessor, candidate);
        let incremental = apply_incremental_delta(predecessor, candidate.generation, delta)
            .map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "SQLite KG projection failed canonical V2 incremental replay: {error}"
                ))
            })?;
        if &incremental != candidate {
            return Err(CognitiveStoreError::Corrupt(
                "full and incremental KG V2 rebuilds diverged for the same source cut".to_string(),
            ));
        }
    }
    publish_generation(predecessor, candidate).map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "SQLite KG projection failed canonical V2 publication: {error}"
        ))
    })
}

fn derive_v2_delta(
    predecessor: &KnowledgeGenerationV2,
    candidate: &KnowledgeGenerationV2,
) -> KnowledgeProjectionDeltaV2 {
    let predecessor_nodes = predecessor
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let candidate_nodes = candidate
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let predecessor_edges = predecessor
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();
    let candidate_edges = candidate
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();

    let remove_node_ids = predecessor_nodes
        .keys()
        .filter(|node_id| !candidate_nodes.contains_key(*node_id))
        .cloned()
        .collect();
    let upsert_nodes = candidate_nodes
        .iter()
        .filter_map(|(node_id, node)| match predecessor_nodes.get(node_id) {
            Some(previous) if *previous == *node => None,
            _ => Some((**node).clone()),
        })
        .collect();
    let remove_edge_identities = predecessor_edges
        .keys()
        .filter(|identity| !candidate_edges.contains_key(*identity))
        .cloned()
        .collect();
    let upsert_edges = candidate_edges
        .iter()
        .filter_map(|(identity, edge)| match predecessor_edges.get(identity) {
            Some(previous) if *previous == *edge => None,
            _ => Some((**edge).clone()),
        })
        .collect();

    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: candidate.source_snapshot_digest,
        generation_vector_digest: candidate.generation_vector_digest,
        graph_profile_digest: candidate.graph_profile_digest,
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}

async fn insert_v2_publication_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: &KnowledgeGenerationV2,
    publication: &KnowledgePublicationReceiptV2,
) -> Result<(), CognitiveStoreError> {
    let predecessor_generation = publication
        .predecessor_generation
        .map(|value| to_i64(value.get(), "KG predecessor generation"))
        .transpose()?;
    let predecessor_digest = publication.predecessor_digest.map(|value| value.to_string());

    sqlx::query(
        "INSERT INTO kg_projection_v2_publications (
            projection_scope, generation, source_snapshot_digest,
            generation_vector_digest, graph_profile_digest,
            predecessor_generation, predecessor_digest, generation_digest,
            publication_digest, node_count, edge_count, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
    )
    .bind(projection_scope)
    .bind(to_i64(generation.generation.get(), "KG generation")?)
    .bind(generation.source_snapshot_digest.to_string())
    .bind(generation.generation_vector_digest.to_string())
    .bind(generation.graph_profile_digest.to_string())
    .bind(predecessor_generation)
    .bind(predecessor_digest)
    .bind(generation.generation_digest.to_string())
    .bind(publication.publication_digest.to_string())
    .bind(to_i64_len(generation.nodes.len(), "V2 projection node count")?)
    .bind(to_i64_len(generation.edges.len(), "V2 projection edge count")?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn load_persisted_projection_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: i64,
) -> Result<(Sha256Digest, Vec<ProjectionNode>, Vec<ProjectionEdge>), CognitiveStoreError> {
    if generation <= 0 {
        return Err(CognitiveStoreError::Corrupt(
            "persisted KG generation must be positive".to_string(),
        ));
    }
    let input_heads_sha256: String = sqlx::query_scalar(
        "SELECT input_heads_sha256
         FROM kg_projection_generation_receipts
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or_else(|| {
        CognitiveStoreError::Corrupt(format!(
            "KG generation {generation} for {projection_scope} has no immutable receipt"
        ))
    })?;
    let input_heads_sha256 =
        Sha256Digest::parse(input_heads_sha256).map_err(CognitiveStoreError::Corrupt)?;

    let node_rows = sqlx::query(
        "SELECT n.node_id, i.canonical_entity_id, n.entity_type, n.label,
                n.valid_from_unix_seconds, n.valid_to_unix_seconds,
                n.memory_id, n.memory_revision, n.source_id, n.source_revision
         FROM kg_nodes n
         JOIN kg_projection_node_entities i
           ON i.projection_scope = n.projection_scope
          AND i.generation = n.generation AND i.node_id = n.node_id
         WHERE n.projection_scope = ? AND n.generation = ?
         ORDER BY n.node_id LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_NODES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if node_rows.len() > MAX_SCOPE_NODES {
        return Err(CognitiveStoreError::Corrupt(
            "persisted KG generation exceeds the V2 node certification limit".to_string(),
        ));
    }
    let nodes = node_rows
        .into_iter()
        .map(|row| {
            Ok(ProjectionNode {
                node_id: row.try_get("node_id").map_err(unavailable)?,
                canonical_entity_id: row.try_get("canonical_entity_id").map_err(unavailable)?,
                entity_type: row.try_get("entity_type").map_err(unavailable)?,
                label: row.try_get("label").map_err(unavailable)?,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            })
        })
        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;

    let edge_rows = sqlx::query(
        "SELECT edge_id, from_node_id, to_node_id, relation,
                valid_from_unix_seconds, valid_to_unix_seconds,
                memory_id, memory_revision, source_id, source_revision
         FROM kg_edges
         WHERE projection_scope = ? AND generation = ?
         ORDER BY edge_id LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if edge_rows.len() > MAX_SCOPE_EDGES {
        return Err(CognitiveStoreError::Corrupt(
            "persisted KG generation exceeds the V2 edge certification limit".to_string(),
        ));
    }
    let edges = edge_rows
        .into_iter()
        .map(|row| {
            Ok(ProjectionEdge {
                edge_id: row.try_get("edge_id").map_err(unavailable)?,
                // The canonical relation id is a physical SQLite companion
                // identity and is not part of the V2 semantic adapter. Exact
                // predicate identity is derived from the stored predicate text.
                canonical_relation_id: String::new(),
                from_node_id: row.try_get("from_node_id").map_err(unavailable)?,
                to_node_id: row.try_get("to_node_id").map_err(unavailable)?,
                relation: row.try_get("relation").map_err(unavailable)?,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            })
        })
        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
    Ok((input_heads_sha256, nodes, edges))
}

fn projection_node_v2(node: &ProjectionNode) -> Result<KnowledgeNodeV2, CognitiveStoreError> {
    let validity_digest = validity_digest(node.valid_from, node.valid_to);
    Ok(KnowledgeNodeV2 {
        node_id: stable_id(&node.node_id, "projection node id")?,
        node_kind_id: digest_stable_id("kind", node.entity_type.as_bytes())?,
        payload_digest: framed_digest32(
            b"hepta:cognitive:kg-node-payload:v1",
            &[
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
            ],
        ),
        supports: vec![KnowledgeSupportV2 {
            source_id: stable_id(&node.source_id, "node source id")?,
            source_revision: positive_revision(node.source_revision, "node source revision")?,
            source_fact_digest: framed_digest32(
                b"hepta:cognitive:kg-node-fact:v1",
                &[
                    node.node_id.as_bytes(),
                    node.canonical_entity_id.as_bytes(),
                    node.entity_type.as_bytes(),
                    node.label.as_bytes(),
                    node.memory_id.as_bytes(),
                    &node.memory_revision.to_be_bytes(),
                    node.source_id.as_bytes(),
                    &node.source_revision.to_be_bytes(),
                    validity_digest.as_array(),
                ],
            ),
            validity_digest,
            tombstoned: false,
        }],
    })
}

fn projection_edge_v2(edge: &ProjectionEdge) -> Result<KnowledgeEdgeV2, CognitiveStoreError> {
    let validity_digest = validity_digest(edge.valid_from, edge.valid_to);
    Ok(KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            edge_id: stable_id(&edge.edge_id, "projection edge id")?,
            source_node_id: stable_id(&edge.from_node_id, "edge source node id")?,
            relation: relation_kind_v2(&edge.relation),
            predicate_id: digest_stable_id("predicate", edge.relation.as_bytes())?,
            target_node_id: stable_id(&edge.to_node_id, "edge target node id")?,
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest,
        supports: vec![KnowledgeSupportV2 {
            source_id: stable_id(&edge.source_id, "edge source id")?,
            source_revision: positive_revision(edge.source_revision, "edge source revision")?,
            source_fact_digest: framed_digest32(
                b"hepta:cognitive:kg-edge-fact:v1",
                &[
                    edge.edge_id.as_bytes(),
                    edge.from_node_id.as_bytes(),
                    edge.to_node_id.as_bytes(),
                    edge.relation.as_bytes(),
                    edge.memory_id.as_bytes(),
                    &edge.memory_revision.to_be_bytes(),
                    edge.source_id.as_bytes(),
                    &edge.source_revision.to_be_bytes(),
                    validity_digest.as_array(),
                ],
            ),
            validity_digest,
            tombstoned: false,
        }],
    })
}

fn relation_kind_v2(relation: &str) -> KnowledgeRelationKindV2 {
    match relation.trim().to_ascii_lowercase().as_str() {
        "supports" | "support" => KnowledgeRelationKindV2::Supports,
        "contradicts" | "contradict" => KnowledgeRelationKindV2::Contradicts,
        "before" | "temporal_before" | "temporal-before" => {
            KnowledgeRelationKindV2::TemporalBefore
        }
        "after" | "temporal_after" | "temporal-after" => {
            KnowledgeRelationKindV2::TemporalAfter
        }
        "causes" | "cause" => KnowledgeRelationKindV2::Causes,
        "enables" | "enable" => KnowledgeRelationKindV2::Enables,
        "procedure_step" | "procedure-step" => KnowledgeRelationKindV2::ProcedureStep,
        "prompt_complements" | "prompt-complements" => {
            KnowledgeRelationKindV2::PromptComplements
        }
        "prompt_substitutes" | "prompt-substitutes" => {
            KnowledgeRelationKindV2::PromptSubstitutes
        }
        "prompt_conflicts" | "prompt-conflicts" => KnowledgeRelationKindV2::PromptConflicts,
        _ => KnowledgeRelationKindV2::Related,
    }
}

fn stable_id(value: &str, label: &str) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string()).map_err(|error| {
        CognitiveStoreError::Corrupt(format!("{label} is not a valid stable V2 identity: {error}"))
    })
}

fn digest_stable_id(prefix: &str, value: &[u8]) -> Result<StableId, CognitiveStoreError> {
    stable_id(&format!("{prefix}:{}", Digest32::of_bytes(value)), prefix)
}

fn positive_revision(value: i64, label: &str) -> Result<Revision, CognitiveStoreError> {
    let value = u64::try_from(value)
        .map_err(|_| CognitiveStoreError::Corrupt(format!("{label} is negative")))?;
    Revision::new(value)
        .map_err(|error| CognitiveStoreError::Corrupt(format!("{label} is invalid: {error}")))
}

fn validity_digest(valid_from: i64, valid_to: Option<i64>) -> Digest32 {
    framed_digest32(
        b"hepta:cognitive:kg-validity:v1",
        &[
            &valid_from.to_be_bytes(),
            &valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        ],
    )
}

fn digest32_from_sha256(
    value: &Sha256Digest,
    label: &str,
) -> Result<Digest32, CognitiveStoreError> {
    value.as_str().parse().map_err(|error| {
        CognitiveStoreError::Corrupt(format!("{label} is not a canonical digest: {error}"))
    })
}

fn framed_digest32(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    let output = hasher.finalize();
    let mut bytes = [0_u8; 32];
    bytes.copy_from_slice(&output);
    Digest32::from_array(bytes)
}

pub(crate) fn input_heads_digest(scope: &str, heads: &[ProjectionHead]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:cognitive:kg-projection-input:v1");
    frame_part(&mut hasher, scope.as_bytes());
    frame_part(
        &mut hasher,
        &u64::try_from(heads.len()).unwrap_or(u64::MAX).to_be_bytes(),
    );
    for head in heads {
        frame_part(&mut hasher, head.memory_id.as_bytes());
        frame_part(&mut hasher, &head.revision.to_be_bytes());
        frame_part(&mut hasher, head.content_sha256.as_bytes());
        frame_part(&mut hasher, head.verification.as_bytes());
        frame_part(&mut hasher, head.lifecycle.as_bytes());
        frame_part(&mut hasher, head.fact_set_sha256.as_bytes());
    }
    finish_digest(hasher)
}

pub(crate) fn output_digest(
    scope: &str,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:cognitive:kg-projection-output:v1");
    frame_part(&mut hasher, scope.as_bytes());
    frame_part(
        &mut hasher,
        &u64::try_from(nodes.len()).unwrap_or(u64::MAX).to_be_bytes(),
    );
    for node in nodes {
        frame_part(&mut hasher, node.node_id.as_bytes());
        frame_part(&mut hasher, node.canonical_entity_id.as_bytes());
        frame_part(&mut hasher, node.entity_type.as_bytes());
        frame_part(&mut hasher, node.label.as_bytes());
        frame_part(&mut hasher, &node.valid_from.to_be_bytes());
        frame_part(
            &mut hasher,
            &node.valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        );
        frame_part(&mut hasher, node.memory_id.as_bytes());
        frame_part(&mut hasher, &node.memory_revision.to_be_bytes());
        frame_part(&mut hasher, node.source_id.as_bytes());
        frame_part(&mut hasher, &node.source_revision.to_be_bytes());
    }
    frame_part(
        &mut hasher,
        &u64::try_from(edges.len()).unwrap_or(u64::MAX).to_be_bytes(),
    );
    for edge in edges {
        frame_part(&mut hasher, edge.edge_id.as_bytes());
        frame_part(&mut hasher, edge.canonical_relation_id.as_bytes());
        frame_part(&mut hasher, edge.from_node_id.as_bytes());
        frame_part(&mut hasher, edge.to_node_id.as_bytes());
        frame_part(&mut hasher, edge.relation.as_bytes());
        frame_part(&mut hasher, &edge.valid_from.to_be_bytes());
        frame_part(
            &mut hasher,
            &edge.valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        );
        frame_part(&mut hasher, edge.memory_id.as_bytes());
        frame_part(&mut hasher, &edge.memory_revision.to_be_bytes());
        frame_part(&mut hasher, edge.source_id.as_bytes());
        frame_part(&mut hasher, &edge.source_revision.to_be_bytes());
    }
    finish_digest(hasher)
}

fn finish_digest(hasher: Sha256) -> Sha256Digest {
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

fn to_i64_len(value: usize, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

fn limit_plus_one(value: usize) -> Result<i64, CognitiveStoreError> {
    value
        .checked_add(1)
        .and_then(|value| i64::try_from(value).ok())
        .ok_or_else(|| CognitiveStoreError::Invalid("KG scope limit exceeds i64".to_string()))
}
