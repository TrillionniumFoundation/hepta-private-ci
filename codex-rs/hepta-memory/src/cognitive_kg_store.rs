use std::collections::BTreeMap;

#[cfg(test)]
use std::fs::OpenOptions;
#[cfg(test)]
use std::io::Write;
#[cfg(test)]
use std::path::PathBuf;
#[cfg(test)]
use std::thread;
#[cfg(test)]
use std::time::Duration;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
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

#[cfg(test)]
const KG_CRASH_STAGE_ENV: &str = "HEPTA_KG_CRASH_STAGE";
#[cfg(test)]
const KG_CRASH_MARKER_ENV: &str = "HEPTA_KG_CRASH_MARKER";

/// Test-only process crash rendezvous. The parent qualification test waits for
/// the fsynced marker and kills the child while the SQLite transaction remains
/// open. Production builds contain neither the environment seam nor the stall.
#[cfg(test)]
fn kg_projection_crash_rendezvous(stage: &str) {
    if std::env::var(KG_CRASH_STAGE_ENV).ok().as_deref() != Some(stage) {
        return;
    }
    let marker = std::env::var_os(KG_CRASH_MARKER_ENV)
        .map(PathBuf::from)
        .expect("KG crash probe marker path");
    let parent = marker.parent().expect("KG crash marker parent");
    std::fs::create_dir_all(parent).expect("create KG crash marker parent");
    let temporary = marker.with_extension(format!("tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .expect("create KG crash marker");
    file.write_all(stage.as_bytes())
        .expect("write KG crash marker");
    file.sync_all().expect("sync KG crash marker");
    drop(file);
    std::fs::rename(&temporary, &marker).expect("publish KG crash marker");
    if let Ok(directory) = std::fs::File::open(parent) {
        let _ = directory.sync_all();
    }
    loop {
        thread::sleep(Duration::from_secs(60));
    }
}

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

const KG_GRAPH_PROFILE_V2: &[u8] = b"hepta:cognitive:kg-sqlite-adapter:v1";

pub(crate) fn canonical_generation_from_projection(
    generation: u64,
    source_snapshot_sha256: &Sha256Digest,
    generation_vector_digest: Digest32,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let source_snapshot_digest = digest32_from_sha256(source_snapshot_sha256)?;
    let graph_profile_digest = Digest32::of_bytes(KG_GRAPH_PROFILE_V2);

    let mut occurrence_to_canonical = BTreeMap::<String, StableId>::new();
    let mut canonical_nodes =
        BTreeMap::<StableId, (StableId, Digest32, Vec<KnowledgeSupportV2>)>::new();
    for node in nodes {
        let canonical_id = stable_id(&node.canonical_entity_id, "canonical entity id")?;
        occurrence_to_canonical.insert(node.node_id.clone(), canonical_id.clone());
        let kind_id = stable_digest_id(
            "kg-kind:v1:",
            b"hepta:cognitive:kg-node-kind:v1",
            &[node.entity_type.as_bytes()],
        )?;
        let payload_digest = framed_digest32(
            b"hepta:cognitive:kg-node-payload:v1",
            &[
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
            ],
        );
        let support = node_support(node)?;
        match canonical_nodes.entry(canonical_id) {
            std::collections::btree_map::Entry::Vacant(entry) => {
                entry.insert((kind_id, payload_digest, vec![support]));
            }
            std::collections::btree_map::Entry::Occupied(mut entry) => {
                let (existing_kind, existing_payload, supports) = entry.get_mut();
                if *existing_kind != kind_id || *existing_payload != payload_digest {
                    return Err(CognitiveStoreError::Conflict(
                        "canonical KG node supports disagree on kind or payload".to_string(),
                    ));
                }
                supports.push(support);
            }
        }
    }

    let canonical_nodes = canonical_nodes
        .into_iter()
        .map(
            |(node_id, (node_kind_id, payload_digest, supports))| KnowledgeNodeV2 {
                node_id,
                node_kind_id,
                payload_digest,
                supports,
            },
        )
        .collect::<Vec<_>>();

    let mut canonical_edges = BTreeMap::<KnowledgeEdgeIdentityV2, Vec<KnowledgeSupportV2>>::new();
    for edge in edges {
        let source_node_id = occurrence_to_canonical
            .get(&edge.from_node_id)
            .cloned()
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "KG edge source occurrence has no canonical node identity".to_string(),
                )
            })?;
        let target_node_id = occurrence_to_canonical
            .get(&edge.to_node_id)
            .cloned()
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "KG edge target occurrence has no canonical node identity".to_string(),
                )
            })?;
        let identity = KnowledgeEdgeIdentityV2 {
            source_node_id,
            relation: canonical_relation_kind(&edge.relation)?,
            target_node_id,
        };
        canonical_edges
            .entry(identity)
            .or_default()
            .push(edge_support(edge)?);
    }
    let canonical_edges = canonical_edges
        .into_iter()
        .map(|(identity, mut supports)| {
            supports.sort();
            let support_validity = supports
                .iter()
                .map(|support| support.validity_digest.as_array().as_slice())
                .collect::<Vec<_>>();
            KnowledgeEdgeV2 {
                identity,
                confidence: ProbabilityQ32::ONE,
                validity_digest: framed_digest32(
                    b"hepta:cognitive:kg-edge-validity-set:v1",
                    &support_validity,
                ),
                supports,
            }
        })
        .collect::<Vec<_>>();

    let generation = Generation::new(generation).map_err(|error| {
        CognitiveStoreError::Corrupt(format!("invalid KG generation identity: {error}"))
    })?;
    build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest,
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes: canonical_nodes,
            edges: canonical_edges,
        },
    )
    .map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "canonical hepta-kg V2 generation rejected SQLite projection: {error}"
        ))
    })
}

pub(crate) async fn load_canonical_generation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: i64,
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    if generation <= 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG generation must be positive".to_string(),
        ));
    }
    let source_snapshot_sha256: String = sqlx::query_scalar(
        "SELECT input_heads_sha256
         FROM kg_projection_generation_receipts
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let source_snapshot_sha256 =
        Sha256Digest::parse(source_snapshot_sha256).map_err(CognitiveStoreError::Corrupt)?;
    let semantic_row = sqlx::query(
        "SELECT generation_vector_sha256, generation_sha256
         FROM kg_projection_generation_semantics
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let generation_vector_digest = match semantic_row.as_ref() {
        Some(row) => row
            .try_get::<String, _>("generation_vector_sha256")
            .map_err(unavailable)?
            .parse()
            .map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "invalid persisted KG generation vector digest: {error}"
                ))
            })?,
        None => framed_digest32(
            b"hepta:cognitive:kg-legacy-source-vector:v1",
            &[digest32_from_sha256(&source_snapshot_sha256)?.as_array()],
        ),
    };

    // A generation is an immutable cut over revision facts. For every memory
    // identity, select the latest trigger at or before the requested generation.
    // This replaces complete graph copies per generation while preserving exact
    // historical reconstruction from source-owned immutable revisions.
    let node_rows = sqlx::query(
        "WITH selected_heads AS (
             SELECT h.trigger_memory_id AS memory_id,
                    h.trigger_memory_revision AS memory_revision
             FROM kg_projection_generation_receipts h
             WHERE h.projection_scope = ?
               AND h.generation <= ?
               AND h.generation = (
                   SELECT MAX(x.generation)
                   FROM kg_projection_generation_receipts x
                   WHERE x.projection_scope = h.projection_scope
                     AND x.trigger_memory_id = h.trigger_memory_id
                     AND x.generation <= ?
               )
         )
         SELECT e.memory_id, e.memory_revision, e.entity_key,
                e.canonical_entity_id, e.entity_type, e.label,
                e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                e.source_id, e.source_revision
         FROM selected_heads h
         JOIN memory_revisions m
           ON m.memory_id = h.memory_id AND m.revision = h.memory_revision
         JOIN kg_revision_entities e
           ON e.memory_id = h.memory_id AND e.memory_revision = h.memory_revision
         WHERE m.verification = 'verified' AND m.lifecycle = 'active'
         ORDER BY e.memory_id, e.memory_revision, e.entity_key LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_NODES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if node_rows.len() > MAX_SCOPE_NODES {
        return Err(CognitiveStoreError::Corrupt(
            "historical KG projection exceeds the canonical node limit".to_string(),
        ));
    }
    let mut nodes = Vec::with_capacity(node_rows.len());
    for row in node_rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        let entity_key: String = row.try_get("entity_key").map_err(unavailable)?;
        nodes.push(ProjectionNode {
            node_id: occurrence_node_id(&memory_id, memory_revision, &entity_key),
            canonical_entity_id: row.try_get("canonical_entity_id").map_err(unavailable)?,
            entity_type: row.try_get("entity_type").map_err(unavailable)?,
            label: row.try_get("label").map_err(unavailable)?,
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

    let edge_rows = sqlx::query(
        "WITH selected_heads AS (
             SELECT h.trigger_memory_id AS memory_id,
                    h.trigger_memory_revision AS memory_revision
             FROM kg_projection_generation_receipts h
             WHERE h.projection_scope = ?
               AND h.generation <= ?
               AND h.generation = (
                   SELECT MAX(x.generation)
                   FROM kg_projection_generation_receipts x
                   WHERE x.projection_scope = h.projection_scope
                     AND x.trigger_memory_id = h.trigger_memory_id
                     AND x.generation <= ?
               )
         )
         SELECT q.memory_id, q.memory_revision, q.relation_key,
                q.canonical_relation_id, q.from_entity_key, q.to_entity_key,
                q.relation, q.valid_from_unix_seconds, q.valid_to_unix_seconds,
                q.source_id, q.source_revision
         FROM selected_heads h
         JOIN memory_revisions m
           ON m.memory_id = h.memory_id AND m.revision = h.memory_revision
         JOIN kg_revision_relations q
           ON q.memory_id = h.memory_id AND q.memory_revision = h.memory_revision
         WHERE m.verification = 'verified' AND m.lifecycle = 'active'
         ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if edge_rows.len() > MAX_SCOPE_EDGES {
        return Err(CognitiveStoreError::Corrupt(
            "historical KG projection exceeds the canonical edge limit".to_string(),
        ));
    }
    let mut edges = Vec::with_capacity(edge_rows.len());
    for row in edge_rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
        let from_entity_key: String = row.try_get("from_entity_key").map_err(unavailable)?;
        let to_entity_key: String = row.try_get("to_entity_key").map_err(unavailable)?;
        edges.push(ProjectionEdge {
            edge_id: occurrence_edge_id(&memory_id, memory_revision, &relation_key),
            canonical_relation_id: row.try_get("canonical_relation_id").map_err(unavailable)?,
            from_node_id: occurrence_node_id(&memory_id, memory_revision, &from_entity_key),
            to_node_id: occurrence_node_id(&memory_id, memory_revision, &to_entity_key),
            relation: row.try_get("relation").map_err(unavailable)?,
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

    let generation_u64 = u64::try_from(generation)
        .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?;
    let rebuilt = canonical_generation_from_projection(
        generation_u64,
        &source_snapshot_sha256,
        generation_vector_digest,
        &nodes,
        &edges,
    )?;
    let stored_digest = semantic_row
        .as_ref()
        .map(|row| row.try_get::<String, _>("generation_sha256"))
        .transpose()
        .map_err(unavailable)?;
    if stored_digest.is_some_and(|digest| digest != rebuilt.generation_digest.to_string()) {
        return Err(CognitiveStoreError::Corrupt(
            "persisted KG generation digest does not match canonical hepta-kg reconstruction"
                .to_string(),
        ));
    }
    Ok(rebuilt)
}

pub(crate) async fn load_compact_edge_support_index_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: i64,
) -> Result<Option<BTreeMap<String, (String, i64)>>, CognitiveStoreError> {
    let storage_mode: Option<String> = sqlx::query_scalar(
        "SELECT storage_mode
         FROM kg_projection_generation_storage
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let Some(storage_mode) = storage_mode else {
        return Ok(None);
    };
    if storage_mode != "revision_facts_v1" {
        return Err(CognitiveStoreError::Corrupt(format!(
            "unsupported KG generation storage mode `{storage_mode}`"
        )));
    }

    let rows = sqlx::query(
        "WITH selected_heads AS (
             SELECT h.trigger_memory_id AS memory_id,
                    h.trigger_memory_revision AS memory_revision
             FROM kg_projection_generation_receipts h
             WHERE h.projection_scope = ?
               AND h.generation <= ?
               AND h.generation = (
                   SELECT MAX(x.generation)
                   FROM kg_projection_generation_receipts x
                   WHERE x.projection_scope = h.projection_scope
                     AND x.trigger_memory_id = h.trigger_memory_id
                     AND x.generation <= ?
               )
         )
         SELECT q.memory_id, q.memory_revision, q.relation_key
         FROM selected_heads h
         JOIN memory_revisions m
           ON m.memory_id = h.memory_id AND m.revision = h.memory_revision
         JOIN kg_revision_relations q
           ON q.memory_id = h.memory_id AND q.memory_revision = h.memory_revision
         WHERE m.verification = 'verified' AND m.lifecycle = 'active'
         ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if rows.len() > MAX_SCOPE_EDGES {
        return Err(CognitiveStoreError::Corrupt(
            "compact KG edge-support index exceeds the canonical edge limit".to_string(),
        ));
    }
    let mut index = BTreeMap::new();
    for row in rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
        let edge_id = occurrence_edge_id(&memory_id, memory_revision, &relation_key);
        if index
            .insert(edge_id, (memory_id, memory_revision))
            .is_some()
        {
            return Err(CognitiveStoreError::Corrupt(
                "duplicate compact KG edge occurrence identity".to_string(),
            ));
        }
    }
    Ok(Some(index))
}

fn node_support(node: &ProjectionNode) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    Ok(KnowledgeSupportV2 {
        source_id: stable_id(&node.node_id, "KG node occurrence id")?,
        source_revision: revision_from_i64(node.memory_revision, "KG node memory revision")?,
        source_fact_digest: framed_digest32(
            b"hepta:cognitive:kg-node-support:v1",
            &[
                node.node_id.as_bytes(),
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
                node.memory_id.as_bytes(),
                &node.memory_revision.to_be_bytes(),
                node.source_id.as_bytes(),
                &node.source_revision.to_be_bytes(),
            ],
        ),
        validity_digest: validity_digest(node.valid_from, node.valid_to),
        valid_from_unix_seconds: Some(node.valid_from),
        valid_to_unix_seconds: node.valid_to,
        tombstoned: false,
    })
}

fn edge_support(edge: &ProjectionEdge) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    Ok(KnowledgeSupportV2 {
        source_id: stable_id(&edge.edge_id, "KG edge occurrence id")?,
        source_revision: revision_from_i64(edge.memory_revision, "KG edge memory revision")?,
        source_fact_digest: framed_digest32(
            b"hepta:cognitive:kg-edge-support:v1",
            &[
                edge.edge_id.as_bytes(),
                edge.from_node_id.as_bytes(),
                edge.to_node_id.as_bytes(),
                edge.relation.as_bytes(),
                edge.memory_id.as_bytes(),
                &edge.memory_revision.to_be_bytes(),
                edge.source_id.as_bytes(),
                &edge.source_revision.to_be_bytes(),
            ],
        ),
        validity_digest: validity_digest(edge.valid_from, edge.valid_to),
        valid_from_unix_seconds: Some(edge.valid_from),
        valid_to_unix_seconds: edge.valid_to,
        tombstoned: false,
    })
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

fn revision_from_i64(value: i64, label: &str) -> Result<Revision, CognitiveStoreError> {
    let value = u64::try_from(value)
        .map_err(|_| CognitiveStoreError::Corrupt(format!("{label} is negative")))?;
    Revision::new(value)
        .map_err(|error| CognitiveStoreError::Corrupt(format!("{label} is invalid: {error}")))
}

fn stable_id(value: &str, label: &str) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string())
        .map_err(|error| CognitiveStoreError::Corrupt(format!("{label} is not stable: {error}")))
}

fn stable_digest_id(
    prefix: &str,
    domain: &[u8],
    parts: &[&[u8]],
) -> Result<StableId, CognitiveStoreError> {
    stable_id(
        &format!("{prefix}{}", framed_sha256_hex(domain, parts)),
        "derived KG stable id",
    )
}

fn digest32_from_sha256(value: &Sha256Digest) -> Result<Digest32, CognitiveStoreError> {
    value
        .as_str()
        .parse()
        .map_err(|error| CognitiveStoreError::Corrupt(format!("invalid KG digest: {error}")))
}

pub(crate) async fn graph_source_vector_digest_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    owner_agent_id: &str,
    scope: &CognitiveScope,
    source_snapshot_digest: Digest32,
) -> Result<Digest32, CognitiveStoreError> {
    let (scope_kind, workspace_sha256) = scope.database_parts();
    let memory_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    // The graph cut contains cited evidence. A standalone source append has
    // no graph facts and must not invalidate a previously published generation
    // when reopening the owner. The broader Lane C snapshot still fences all
    // source-ledger changes independently.
    let source_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM source_ledger s
         WHERE s.owner_agent_id = ? AND s.scope_kind = ? AND s.workspace_sha256 IS ?
           AND EXISTS (SELECT 1 FROM memory_citations c
                       WHERE c.source_id = s.source_id AND c.source_revision = s.source_revision)",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let tombstone_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_revisions
         WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?
           AND lifecycle = 'tombstoned'",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let knowledge_fact_frontier: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM kg_revision_fact_sets f
         JOIN memory_revisions r
           ON r.memory_id = f.memory_id AND r.revision = f.memory_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?",
    )
    .bind(owner_agent_id)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .map_err(unavailable)?;

    let frontiers = [
        u64::try_from(memory_frontier)
            .map_err(|_| CognitiveStoreError::Corrupt("negative memory frontier".to_string()))?,
        u64::try_from(knowledge_fact_frontier).map_err(|_| {
            CognitiveStoreError::Corrupt("negative knowledge-fact frontier".to_string())
        })?,
        u64::try_from(tombstone_frontier)
            .map_err(|_| CognitiveStoreError::Corrupt("negative tombstone frontier".to_string()))?,
        u64::try_from(source_frontier)
            .map_err(|_| CognitiveStoreError::Corrupt("negative source frontier".to_string()))?,
    ];
    let frontier_bytes = frontiers
        .iter()
        .map(|value| value.to_be_bytes())
        .collect::<Vec<_>>();
    let projection_key = scope.projection_key();
    let parts = [
        owner_agent_id.as_bytes(),
        projection_key.as_bytes(),
        frontier_bytes[0].as_slice(),
        frontier_bytes[1].as_slice(),
        frontier_bytes[2].as_slice(),
        frontier_bytes[3].as_slice(),
        source_snapshot_digest.as_array().as_slice(),
    ];
    Ok(framed_digest32(
        b"hepta:cognitive:kg-source-vector:v1",
        &parts,
    ))
}

pub(crate) fn sha256_from_digest32(value: Digest32) -> Result<Sha256Digest, CognitiveStoreError> {
    Sha256Digest::parse(value.to_string()).map_err(CognitiveStoreError::Corrupt)
}

fn framed_sha256_hex(domain: &[u8], parts: &[&[u8]]) -> String {
    framed_digest32(domain, parts).to_string()
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
        let generation_vector_digest = graph_source_vector_digest_tx(
            transaction,
            self.owner_agent_id.as_str(),
            scope,
            digest32_from_sha256(&input_heads_sha256)?,
        )
        .await?;

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
        let next_u64 = u64::try_from(next)
            .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?;
        let candidate = canonical_generation_from_projection(
            next_u64,
            &input_heads_sha256,
            generation_vector_digest,
            &nodes,
            &edges,
        )?;
        let predecessor = if current == 0 {
            None
        } else {
            Some(load_canonical_generation_tx(transaction, &projection_scope, current).await?)
        };
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "canonical hepta-kg V2 publication rejected SQLite projection: {error}"
                ))
            })?;
        let generation_sha256 = sha256_from_digest32(candidate.generation_digest)?;
        let publication_sha256 = sha256_from_digest32(publication.publication_digest)?;
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
        #[cfg(test)]
        kg_projection_crash_rendezvous("before_semantic_receipt");
        sqlx::query(
            "INSERT INTO kg_projection_generation_semantics (
                projection_scope, generation, source_snapshot_sha256,
                generation_vector_sha256, graph_profile_sha256,
                generation_sha256, publication_sha256
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&projection_scope)
        .bind(next)
        .bind(candidate.source_snapshot_digest.to_string())
        .bind(candidate.generation_vector_digest.to_string())
        .bind(candidate.graph_profile_digest.to_string())
        .bind(generation_sha256.as_str())
        .bind(publication_sha256.as_str())
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        sqlx::query(
            "INSERT INTO kg_projection_generation_storage (
                projection_scope, generation, storage_mode
             ) VALUES (?, ?, 'revision_facts_v1')",
        )
        .bind(&projection_scope)
        .bind(next)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        #[cfg(test)]
        kg_projection_crash_rendezvous("after_semantic_receipt_before_current_pointer");
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
            generation_sha256,
            publication_sha256,
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

/// Preserve the canonical stored relation identity when selecting typed channels.
pub(crate) fn canonical_relation_kind(
    relation: &str,
) -> Result<KnowledgeRelationKindV2, CognitiveStoreError> {
    Ok(KnowledgeRelationKindV2::Custom(stable_digest_id(
        "kg-rel-kind:v1:",
        b"hepta:cognitive:kg-relation-kind:v1",
        &[relation.as_bytes()],
    )?))
}
