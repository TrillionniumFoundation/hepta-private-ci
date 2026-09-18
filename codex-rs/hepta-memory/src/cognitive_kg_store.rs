use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::DurableProjectionEdgeV2;
use codex_hepta_kg::DurableProjectionHeadV2;
use codex_hepta_kg::DurableProjectionNodeV2;
use codex_hepta_kg::durable_input_heads_digest_v2;
use codex_hepta_kg::durable_projection_digest_v2;
use codex_hepta_kg::build_durable_generation_from_snapshot_v2;
use codex_hepta_kg::build_durable_generation_v2;
use codex_hepta_kg::publish_generation;
use codex_hepta_kg::derive_incremental_delta;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use sqlx::Row;
use sqlx::Sqlite;
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

pub(crate) const MAX_SCOPE_HEADS: usize = 10_000;
pub(crate) const MAX_SCOPE_NODES: usize = 10_000;
pub(crate) const MAX_SCOPE_EDGES: usize = 50_000;
pub(crate) const MAX_PROJECTION_SCOPES: usize = 10_000;

pub(crate) type ProjectionHead = DurableProjectionHeadV2;
pub(crate) type ProjectionNode = DurableProjectionNodeV2;
pub(crate) type ProjectionEdge = DurableProjectionEdgeV2;

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
        let output_sha256 = output_digest(&projection_scope, &nodes, &edges)?;

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
        let next_generation = Generation::new(
            u64::try_from(next)
                .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?,
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let predecessor = if current == 0 {
            None
        } else {
            Some(
                self.load_durable_generation_tx(
                    transaction,
                    scope,
                    &projection_scope,
                    current,
                )
                .await?,
            )
        };
        let v2_generation = build_durable_generation_v2(
            next_generation,
            &projection_scope,
            &heads,
            &nodes,
            &edges,
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        if let Some(predecessor) = predecessor.as_ref() {
            let delta = derive_incremental_delta(predecessor, &v2_generation)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
            let incremental = apply_incremental_delta(predecessor, next_generation, delta)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
            if incremental != v2_generation {
                return Err(CognitiveStoreError::Corrupt(
                    "full and incremental KG V2 generation paths diverged".to_string(),
                ));
            }
        }
        let publication = publish_generation(predecessor.as_ref(), &v2_generation)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
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
        sqlx::query(
            "INSERT INTO kg_projection_v2_generation_receipts (
                projection_scope, generation, source_snapshot_sha256,
                generation_digest, predecessor_generation,
                predecessor_generation_digest, disposition, publication_digest
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&projection_scope)
        .bind(next)
        .bind(v2_generation.source_snapshot_digest.to_string())
        .bind(v2_generation.generation_digest.to_string())
        .bind(publication.predecessor_generation.map(|value| value.get()).map(|value| i64::try_from(value).unwrap_or(i64::MAX)))
        .bind(publication.predecessor_digest.map(|value| value.to_string()))
        .bind(match publication.disposition {
            codex_hepta_kg::KnowledgePublicationDispositionV2::Published => "published",
            codex_hepta_kg::KnowledgePublicationDispositionV2::Unchanged => "unchanged",
        })
        .bind(publication.publication_digest.to_string())
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

    pub(crate) async fn load_durable_generation_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        scope: &CognitiveScope,
        projection_scope: &str,
        generation: i64,
    ) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
        let source_snapshot: String = sqlx::query_scalar(
            "SELECT input_heads_sha256
             FROM kg_projection_generation_receipts
             WHERE projection_scope = ? AND generation = ?",
        )
        .bind(projection_scope)
        .bind(generation)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let source_snapshot = source_snapshot
            .parse::<Digest32>()
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;

        let node_rows = sqlx::query(
            "SELECT n.node_id, i.canonical_entity_id, n.entity_type, n.label,
                    n.valid_from_unix_seconds, n.valid_to_unix_seconds,
                    n.memory_id, n.memory_revision, n.source_id, n.source_revision
             FROM kg_nodes n
             JOIN kg_projection_node_entities i
               ON i.projection_scope = n.projection_scope
              AND i.generation = n.generation
              AND i.node_id = n.node_id
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
                "persisted KG predecessor exceeds the node limit".to_string(),
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
                    valid_from: row.try_get("valid_from_unix_seconds").map_err(unavailable)?,
                    valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                    memory_id: row.try_get("memory_id").map_err(unavailable)?,
                    memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                    source_id: row.try_get("source_id").map_err(unavailable)?,
                    source_revision: row.try_get("source_revision").map_err(unavailable)?,
                })
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;

        let edge_rows = sqlx::query(
            "SELECT e.edge_id, e.from_node_id, e.to_node_id, e.relation,
                    e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                    e.memory_id, e.memory_revision, e.source_id, e.source_revision,
                    fi.canonical_entity_id AS from_canonical_entity_id,
                    ti.canonical_entity_id AS to_canonical_entity_id
             FROM kg_edges e
             JOIN kg_projection_node_entities fi
               ON fi.projection_scope = e.projection_scope
              AND fi.generation = e.generation
              AND fi.node_id = e.from_node_id
             JOIN kg_projection_node_entities ti
               ON ti.projection_scope = e.projection_scope
              AND ti.generation = e.generation
              AND ti.node_id = e.to_node_id
             WHERE e.projection_scope = ? AND e.generation = ?
             ORDER BY e.edge_id LIMIT ?",
        )
        .bind(projection_scope)
        .bind(generation)
        .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if edge_rows.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Corrupt(
                "persisted KG predecessor exceeds the edge limit".to_string(),
            ));
        }
        let mut edges = Vec::with_capacity(edge_rows.len());
        for row in edge_rows {
            let relation: String = row.try_get("relation").map_err(unavailable)?;
            let from_canonical_entity_id: String =
                row.try_get("from_canonical_entity_id").map_err(unavailable)?;
            let to_canonical_entity_id: String =
                row.try_get("to_canonical_entity_id").map_err(unavailable)?;
            edges.push(ProjectionEdge {
                edge_id: row.try_get("edge_id").map_err(unavailable)?,
                canonical_relation_id: canonical_relation_id(
                    &self.owner_agent_id,
                    scope,
                    &from_canonical_entity_id,
                    &relation,
                    &to_canonical_entity_id,
                ),
                from_node_id: row.try_get("from_node_id").map_err(unavailable)?,
                to_node_id: row.try_get("to_node_id").map_err(unavailable)?,
                relation,
                valid_from: row.try_get("valid_from_unix_seconds").map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }

        let generation = Generation::new(
            u64::try_from(generation)
                .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?,
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let rebuilt = build_durable_generation_from_snapshot_v2(
            generation,
            projection_scope,
            source_snapshot,
            &nodes,
            &edges,
        )
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let persisted_digest: Option<String> = sqlx::query_scalar(
            "SELECT generation_digest
             FROM kg_projection_v2_generation_receipts
             WHERE projection_scope = ? AND generation = ?",
        )
        .bind(projection_scope)
        .bind(i64::try_from(generation.get()).unwrap_or(i64::MAX))
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if let Some(persisted_digest) = persisted_digest {
            let persisted_digest = persisted_digest
                .parse::<Digest32>()
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
            if persisted_digest != rebuilt.generation_digest {
                return Err(CognitiveStoreError::Corrupt(
                    "persisted KG V2 generation digest differs from canonical rebuild".to_string(),
                ));
            }
        }
        Ok(rebuilt)
    }

}

pub(crate) fn input_heads_digest(scope: &str, heads: &[ProjectionHead]) -> Sha256Digest {
    Sha256Digest::parse(durable_input_heads_digest_v2(scope, heads).to_string())
        .expect("hepta-kg durable input digest is canonical sha256")
}

pub(crate) fn output_digest(
    scope: &str,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<Sha256Digest, CognitiveStoreError> {
    let digest = durable_projection_digest_v2(scope, nodes, edges)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    Sha256Digest::parse(digest.to_string()).map_err(CognitiveStoreError::Corrupt)
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
