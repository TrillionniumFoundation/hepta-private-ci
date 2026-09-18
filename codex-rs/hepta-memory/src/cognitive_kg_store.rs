use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::publish_generation;
use codex_hepta_kg::relation_kind_from_name;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sha2::Digest;
use sha2::Sha256;
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

pub(crate) struct KernelProjection {
    pub(crate) generation: KnowledgeGenerationV2,
    pub(crate) nodes: Vec<ProjectionNode>,
    pub(crate) edges: Vec<ProjectionEdge>,
    pub(crate) node_index_by_id: BTreeMap<String, usize>,
    pub(crate) seed_node_ids_by_canonical: BTreeMap<String, Vec<StableId>>,
    pub(crate) edge_indices_by_identity: BTreeMap<KnowledgeEdgeIdentityV2, Vec<usize>>,
}

pub(crate) fn build_kernel_generation(
    projection_scope: &str,
    generation: i64,
    input_heads_sha256: &Sha256Digest,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let generation = u64::try_from(generation)
        .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))
        .and_then(|value| {
            Generation::new(value)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
        })?;
    let source_snapshot_digest = input_heads_sha256
        .as_str()
        .parse::<Digest32>()
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let generation_vector_digest = kernel_digest(
        b"hepta:cognitive:kg-generation-vector:v1",
        &[projection_scope.as_bytes(), input_heads_sha256.as_str().as_bytes()],
    );
    let graph_profile_digest = Digest32::of_bytes(b"hepta:cognitive:kg-sqlite-profile:v1");

    let mut kernel_nodes = Vec::with_capacity(nodes.len());
    for node in nodes {
        let support = kernel_node_support(node)?;
        let node_kind_digest = kernel_digest(
            b"hepta:cognitive:kg-node-kind:v1",
            &[node.entity_type.as_bytes()],
        );
        kernel_nodes.push(KnowledgeNodeV2 {
            node_id: stable_id(&node.node_id, "KG node ID")?,
            node_kind_id: stable_id(
                &format!("kg-kind:v1:{node_kind_digest}"),
                "KG node kind ID",
            )?,
            payload_digest: kernel_digest(
                b"hepta:cognitive:kg-node-payload:v1",
                &[
                    node.canonical_entity_id.as_bytes(),
                    node.entity_type.as_bytes(),
                    node.label.as_bytes(),
                ],
            ),
            supports: vec![support],
        });
    }

    let mut kernel_edges = BTreeMap::<KnowledgeEdgeIdentityV2, KnowledgeEdgeV2>::new();
    for edge in edges {
        let identity = kernel_edge_identity(edge)?;
        let support = kernel_edge_support(edge)?;
        if let Some(existing) = kernel_edges.get_mut(&identity) {
            existing.supports.push(support);
        } else {
            kernel_edges.insert(
                identity.clone(),
                KnowledgeEdgeV2 {
                    identity,
                    confidence: ProbabilityQ32::ONE,
                    validity_digest: support.validity_digest,
                    supports: vec![support],
                },
            );
        }
    }
    for edge in kernel_edges.values_mut() {
        edge.supports.sort();
        edge.validity_digest = kernel_support_set_validity_digest(&edge.supports);
    }

    build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest,
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes: kernel_nodes,
            edges: kernel_edges.into_values().collect(),
        },
    )
    .map_err(|error| CognitiveStoreError::Corrupt(format!(
        "canonical KG generation rejected SQLite projection: {error}"
    )))
}

pub(crate) fn kernel_edge_identity(
    edge: &ProjectionEdge,
) -> Result<KnowledgeEdgeIdentityV2, CognitiveStoreError> {
    Ok(KnowledgeEdgeIdentityV2 {
        source_node_id: stable_id(&edge.from_node_id, "KG edge source node ID")?,
        relation: relation_kind_from_name(&edge.relation),
        target_node_id: stable_id(&edge.to_node_id, "KG edge target node ID")?,
    })
}

pub(crate) fn kernel_query_id(
    projection_scope: &str,
    generation: i64,
    canonical_entity_id: &str,
) -> Result<StableId, CognitiveStoreError> {
    let generation_bytes = generation.to_be_bytes();
    let digest = kernel_digest(
        b"hepta:cognitive:kg-query:v1",
        &[
            projection_scope.as_bytes(),
            &generation_bytes,
            canonical_entity_id.as_bytes(),
        ],
    );
    stable_id(&format!("kg-query:v1:{digest}"), "KG query ID")
}

fn kernel_node_support(node: &ProjectionNode) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    let memory_revision = node.memory_revision.to_be_bytes();
    let source_revision = node.source_revision.to_be_bytes();
    Ok(KnowledgeSupportV2 {
        support_id: stable_id(&node.node_id, "KG node support ID")?,
        source_id: stable_id(&node.source_id, "KG node source ID")?,
        source_revision: revision(node.source_revision, "KG node source revision")?,
        source_fact_digest: kernel_digest(
            b"hepta:cognitive:kg-node-support:v1",
            &[
                node.node_id.as_bytes(),
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
                node.memory_id.as_bytes(),
                &memory_revision,
                node.source_id.as_bytes(),
                &source_revision,
            ],
        ),
        validity_digest: kernel_validity_digest(node.valid_from, node.valid_to),
        tombstoned: false,
    })
}

fn kernel_edge_support(node: &ProjectionEdge) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    let memory_revision = node.memory_revision.to_be_bytes();
    let source_revision = node.source_revision.to_be_bytes();
    Ok(KnowledgeSupportV2 {
        support_id: stable_id(&node.edge_id, "KG edge support ID")?,
        source_id: stable_id(&node.source_id, "KG edge source ID")?,
        source_revision: revision(node.source_revision, "KG edge source revision")?,
        source_fact_digest: kernel_digest(
            b"hepta:cognitive:kg-edge-support:v1",
            &[
                node.edge_id.as_bytes(),
                node.canonical_relation_id.as_bytes(),
                node.from_node_id.as_bytes(),
                node.to_node_id.as_bytes(),
                node.relation.as_bytes(),
                node.memory_id.as_bytes(),
                &memory_revision,
                node.source_id.as_bytes(),
                &source_revision,
            ],
        ),
        validity_digest: kernel_validity_digest(node.valid_from, node.valid_to),
        tombstoned: false,
    })
}

fn kernel_support_set_validity_digest(supports: &[KnowledgeSupportV2]) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(
        &mut hasher,
        b"hepta:cognitive:kg-relation-validity-set:v1",
    );
    frame_part(
        &mut hasher,
        &u64::try_from(supports.len()).unwrap_or(u64::MAX).to_be_bytes(),
    );
    for support in supports {
        frame_part(&mut hasher, support.support_id.as_str().as_bytes());
        frame_part(&mut hasher, support.validity_digest.as_array());
    }
    digest32_from_hasher(hasher)
}

fn kernel_validity_digest(valid_from: i64, valid_to: Option<i64>) -> Digest32 {
    let from = valid_from.to_be_bytes();
    let to = valid_to.unwrap_or(i64::MIN).to_be_bytes();
    kernel_digest(
        b"hepta:cognitive:kg-validity:v1",
        &[&from, &to],
    )
}

fn kernel_digest(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    digest32_from_hasher(hasher)
}

fn digest32_from_hasher(hasher: Sha256) -> Digest32 {
    let output = hasher.finalize();
    let mut bytes = [0_u8; 32];
    bytes.copy_from_slice(&output);
    Digest32::from_array(bytes)
}

fn stable_id(value: &str, label: &str) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(format!("{label} is invalid: {error}")))
}

fn revision(value: i64, label: &str) -> Result<Revision, CognitiveStoreError> {
    u64::try_from(value)
        .map_err(|_| CognitiveStoreError::Corrupt(format!("{label} is negative")))
        .and_then(|value| {
            Revision::new(value)
                .map_err(|error| CognitiveStoreError::Corrupt(format!("{label}: {error}")))
        })
}

fn scope_from_projection_key(value: &str) -> Result<CognitiveScope, CognitiveStoreError> {
    if value == "agent_private" {
        return Ok(CognitiveScope::AgentPrivate);
    }
    let workspace = value
        .strip_prefix("workspace_private:")
        .ok_or_else(|| CognitiveStoreError::Corrupt("invalid KG projection scope".to_string()))?;
    let workspace_sha256 =
        Sha256Digest::parse(workspace.to_string()).map_err(CognitiveStoreError::Corrupt)?;
    Ok(CognitiveScope::WorkspacePrivate { workspace_sha256 })
}

impl CognitiveStore {
    pub(crate) async fn load_kernel_projection_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        projection_scope: &str,
        generation: i64,
    ) -> Result<KernelProjection, CognitiveStoreError> {
        let receipt = sqlx::query(
            "SELECT input_heads_sha256, kernel_generation_sha256
             FROM kg_projection_generation_receipts
             WHERE projection_scope = ? AND generation = ?",
        )
        .bind(projection_scope)
        .bind(generation)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        let input_heads_sha256 = Sha256Digest::parse(
            receipt
                .try_get::<String, _>("input_heads_sha256")
                .map_err(unavailable)?,
        )
        .map_err(CognitiveStoreError::Corrupt)?;
        let stored_kernel_digest: Option<String> = receipt
            .try_get("kernel_generation_sha256")
            .map_err(unavailable)?;

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
                "stored KG projection exceeds the kernel node load limit".to_string(),
            ));
        }
        let mut nodes = Vec::with_capacity(node_rows.len());
        for row in node_rows {
            nodes.push(ProjectionNode {
                node_id: row.try_get("node_id").map_err(unavailable)?,
                canonical_entity_id: row
                    .try_get("canonical_entity_id")
                    .map_err(unavailable)?,
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
            });
        }
        let canonical_by_node = nodes
            .iter()
            .map(|node| (node.node_id.clone(), node.canonical_entity_id.clone()))
            .collect::<BTreeMap<_, _>>();
        let scope = scope_from_projection_key(projection_scope)?;

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
                "stored KG projection exceeds the kernel edge load limit".to_string(),
            ));
        }
        let mut edges = Vec::with_capacity(edge_rows.len());
        for row in edge_rows {
            let from_node_id: String = row.try_get("from_node_id").map_err(unavailable)?;
            let to_node_id: String = row.try_get("to_node_id").map_err(unavailable)?;
            let relation: String = row.try_get("relation").map_err(unavailable)?;
            let from_canonical = canonical_by_node.get(&from_node_id).ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "stored KG edge source has no canonical entity mapping".to_string(),
                )
            })?;
            let to_canonical = canonical_by_node.get(&to_node_id).ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "stored KG edge target has no canonical entity mapping".to_string(),
                )
            })?;
            edges.push(ProjectionEdge {
                edge_id: row.try_get("edge_id").map_err(unavailable)?,
                canonical_relation_id: canonical_relation_id(
                    &self.owner_agent_id,
                    &scope,
                    from_canonical,
                    &relation,
                    to_canonical,
                ),
                from_node_id,
                to_node_id,
                relation,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id: row.try_get("memory_id").map_err(unavailable)?,
                memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }

        let kernel_generation = build_kernel_generation(
            projection_scope,
            generation,
            &input_heads_sha256,
            &nodes,
            &edges,
        )?;
        if let Some(stored) = stored_kernel_digest
            && stored != kernel_generation.generation_digest.to_string()
        {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG projection `{projection_scope}` kernel digest failed canonical recomputation"
            )));
        }

        let mut node_index_by_id = BTreeMap::new();
        let mut seed_node_ids_by_canonical = BTreeMap::<String, Vec<StableId>>::new();
        for (index, node) in nodes.iter().enumerate() {
            node_index_by_id.insert(node.node_id.clone(), index);
            seed_node_ids_by_canonical
                .entry(node.canonical_entity_id.clone())
                .or_default()
                .push(stable_id(&node.node_id, "KG seed node ID")?);
        }
        let mut edge_indices_by_identity =
            BTreeMap::<KnowledgeEdgeIdentityV2, Vec<usize>>::new();
        for (index, edge) in edges.iter().enumerate() {
            edge_indices_by_identity
                .entry(kernel_edge_identity(edge)?)
                .or_default()
                .push(index);
        }

        Ok(KernelProjection {
            generation: kernel_generation,
            nodes,
            edges,
            node_index_by_id,
            seed_node_ids_by_canonical,
            edge_indices_by_identity,
        })
    }

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
        let kernel_generation = build_kernel_generation(
            &projection_scope,
            next,
            &input_heads_sha256,
            &nodes,
            &edges,
        )?;
        let predecessor = if current == 0 {
            None
        } else {
            Some(
                self.load_kernel_projection_tx(transaction, &projection_scope, current)
                    .await?
                    .generation,
            )
        };
        publish_generation(predecessor.as_ref(), &kernel_generation).map_err(|error| {
            CognitiveStoreError::Conflict(format!(
                "canonical KG publication rejected SQLite generation: {error}"
            ))
        })?;
        let kernel_generation_sha256 =
            Sha256Digest::parse(kernel_generation.generation_digest.to_string())
                .map_err(CognitiveStoreError::Corrupt)?;
        sqlx::query(
            "INSERT INTO kg_projection_generation_receipts (
                projection_scope, generation, trigger_memory_id,
                trigger_memory_revision, fact_set_sha256, input_heads_sha256,
                output_sha256, kernel_generation_sha256, entity_count,
                relation_count, node_count, edge_count, recorded_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
        )
        .bind(&projection_scope)
        .bind(next)
        .bind(trigger_memory.id.memory_id.as_str())
        .bind(to_i64(trigger_memory.id.revision, "memory revision")?)
        .bind(trigger_facts.digest.as_str())
        .bind(input_heads_sha256.as_str())
        .bind(output_sha256.as_str())
        .bind(kernel_generation_sha256.as_str())
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
            kernel_generation_sha256,
            entity_count: u64::try_from(trigger_facts.entities.len()).unwrap_or(u64::MAX),
            relation_count: u64::try_from(trigger_facts.relations.len()).unwrap_or(u64::MAX),
            node_count: u64::try_from(nodes.len()).unwrap_or(u64::MAX),
            edge_count: u64::try_from(edges.len()).unwrap_or(u64::MAX),
        })
    }
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
