use std::collections::BTreeMap;
use std::str::FromStr;

use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgePublicationDispositionV2;
use codex_hepta_kg::KnowledgePublicationReceiptV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::publish_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::CognitiveStoreError;
use crate::cognitive_kg_store::ProjectionEdge;
use crate::cognitive_kg_store::ProjectionHead;
use crate::cognitive_kg_store::ProjectionNode;
use crate::cognitive_store::unavailable;

const SQLITE_KG_PROFILE_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-profile.v1";
const GENERATION_VECTOR_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-generation-vector.v1";
const NODE_KIND_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-node-kind.v1";
const NODE_PAYLOAD_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-node-payload.v1";
const NODE_VALIDITY_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-node-validity.v1";
const EDGE_VALIDITY_DOMAIN: &[u8] = b"hepta.cognitive.sqlite-kg-edge-validity.v1";

pub(crate) fn support_fact_digests(
    heads: &[ProjectionHead],
) -> BTreeMap<(String, i64), String> {
    heads
        .iter()
        .map(|head| {
            (
                (head.memory_id.clone(), head.revision),
                head.fact_set_sha256.clone(),
            )
        })
        .collect()
}

pub(crate) fn build_kernel_generation(
    generation: u64,
    input_heads_sha256: &str,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
    support_fact_digests: &BTreeMap<(String, i64), String>,
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let source_snapshot_digest = parse_digest(input_heads_sha256, "KG source snapshot")?;
    let generation_vector_digest = digest_parts(
        GENERATION_VECTOR_DOMAIN,
        &[source_snapshot_digest.as_array().as_slice()],
    );
    let graph_profile_digest = Digest32::of_bytes(SQLITE_KG_PROFILE_DOMAIN);

    let nodes = nodes
        .iter()
        .map(|node| {
            let validity_digest = validity_digest(
                NODE_VALIDITY_DOMAIN,
                node.valid_from,
                node.valid_to,
                &[],
            );
            Ok(KnowledgeNodeV2 {
                node_id: stable_id(&node.node_id, "KG node")?,
                node_kind_id: stable_id(
                    &format!(
                        "kg-kind:v1:{}",
                        digest_parts(NODE_KIND_DOMAIN, &[node.entity_type.as_bytes()])
                    ),
                    "KG node kind",
                )?,
                payload_digest: digest_parts(
                    NODE_PAYLOAD_DOMAIN,
                    &[
                        node.canonical_entity_id.as_bytes(),
                        node.entity_type.as_bytes(),
                        node.label.as_bytes(),
                    ],
                ),
                supports: vec![support(
                    &node.memory_id,
                    node.memory_revision,
                    &node.source_id,
                    node.source_revision,
                    validity_digest,
                    support_fact_digests,
                )?],
            })
        })
        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;

    let edges = edges
        .iter()
        .map(|edge| {
            let validity_digest = validity_digest(
                EDGE_VALIDITY_DOMAIN,
                edge.valid_from,
                edge.valid_to,
                &[edge.relation.as_bytes()],
            );
            Ok(KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: stable_id(&edge.from_node_id, "KG edge source node")?,
                    relation_id: stable_id(&edge.edge_id, "KG relation occurrence")?,
                    relation: relation_kind(&edge.relation),
                    target_node_id: stable_id(&edge.to_node_id, "KG edge target node")?,
                },
                confidence: ProbabilityQ32::ONE,
                validity_digest,
                supports: vec![support(
                    &edge.memory_id,
                    edge.memory_revision,
                    &edge.source_id,
                    edge.source_revision,
                    validity_digest,
                    support_fact_digests,
                )?],
            })
        })
        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;

    build_complete_generation(
        Generation::new(generation)
            .map_err(|error| CognitiveStoreError::Corrupt(format!("invalid KG generation: {error}")))?,
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
            "hepta-kg rejected the SQLite projection source cut: {error}"
        ))
    })
}

pub(crate) async fn load_kernel_generation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: i64,
) -> Result<Option<KnowledgeGenerationV2>, CognitiveStoreError> {
    let input_heads_sha256 = sqlx::query_scalar::<_, String>(
        "SELECT input_heads_sha256
         FROM kg_projection_generation_receipts
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let Some(input_heads_sha256) = input_heads_sha256 else {
        return Ok(None);
    };

    let node_rows = sqlx::query(
        "SELECT n.node_id, i.canonical_entity_id, n.entity_type, n.label,
                n.valid_from_unix_seconds, n.valid_to_unix_seconds,
                n.memory_id, n.memory_revision, n.source_id, n.source_revision,
                s.fact_set_sha256
         FROM kg_nodes n
         JOIN kg_projection_node_entities i
           ON i.projection_scope = n.projection_scope
          AND i.generation = n.generation AND i.node_id = n.node_id
         JOIN kg_revision_fact_sets s
           ON s.memory_id = n.memory_id AND s.memory_revision = n.memory_revision
         WHERE n.projection_scope = ? AND n.generation = ?
         ORDER BY n.node_id",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let mut facts = BTreeMap::new();
    let mut nodes = Vec::with_capacity(node_rows.len());
    for row in node_rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        facts.insert(
            (memory_id.clone(), memory_revision),
            row.try_get("fact_set_sha256").map_err(unavailable)?,
        );
        nodes.push(ProjectionNode {
            node_id: row.try_get("node_id").map_err(unavailable)?,
            canonical_entity_id: row.try_get("canonical_entity_id").map_err(unavailable)?,
            entity_type: row.try_get("entity_type").map_err(unavailable)?,
            label: row.try_get("label").map_err(unavailable)?,
            valid_from: row.try_get("valid_from_unix_seconds").map_err(unavailable)?,
            valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
            memory_id,
            memory_revision,
            source_id: row.try_get("source_id").map_err(unavailable)?,
            source_revision: row.try_get("source_revision").map_err(unavailable)?,
        });
    }

    let edge_rows = sqlx::query(
        "SELECT e.edge_id, e.from_node_id, e.to_node_id, e.relation,
                e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                e.memory_id, e.memory_revision, e.source_id, e.source_revision,
                s.fact_set_sha256
         FROM kg_edges e
         JOIN kg_revision_fact_sets s
           ON s.memory_id = e.memory_id AND s.memory_revision = e.memory_revision
         WHERE e.projection_scope = ? AND e.generation = ?
         ORDER BY e.edge_id",
    )
    .bind(projection_scope)
    .bind(generation)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    let mut edges = Vec::with_capacity(edge_rows.len());
    for row in edge_rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        facts.insert(
            (memory_id.clone(), memory_revision),
            row.try_get("fact_set_sha256").map_err(unavailable)?,
        );
        edges.push(ProjectionEdge {
            edge_id: row.try_get("edge_id").map_err(unavailable)?,
            canonical_relation_id: String::new(),
            from_node_id: row.try_get("from_node_id").map_err(unavailable)?,
            to_node_id: row.try_get("to_node_id").map_err(unavailable)?,
            relation: row.try_get("relation").map_err(unavailable)?,
            valid_from: row.try_get("valid_from_unix_seconds").map_err(unavailable)?,
            valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
            memory_id,
            memory_revision,
            source_id: row.try_get("source_id").map_err(unavailable)?,
            source_revision: row.try_get("source_revision").map_err(unavailable)?,
        });
    }

    let generation = u64::try_from(generation)
        .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?;
    build_kernel_generation(generation, &input_heads_sha256, &nodes, &edges, &facts).map(Some)
}

pub(crate) async fn persist_kernel_receipt_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: &KnowledgeGenerationV2,
    publication: &KnowledgePublicationReceiptV2,
) -> Result<(), CognitiveStoreError> {
    let disposition = match publication.disposition {
        KnowledgePublicationDispositionV2::Published => "published",
        KnowledgePublicationDispositionV2::Unchanged => "unchanged",
    };
    let predecessor_generation = publication
        .predecessor_generation
        .map(|value| i64::try_from(value.get()))
        .transpose()
        .map_err(|_| CognitiveStoreError::Corrupt("KG predecessor generation exceeds i64".to_string()))?;
    let predecessor_sha256 = publication.predecessor_digest.map(|value| value.to_string());
    let existing = sqlx::query(
        "SELECT source_snapshot_sha256, generation_vector_sha256,
                graph_profile_sha256, generation_sha256,
                predecessor_generation, predecessor_sha256,
                publication_sha256, disposition, node_count, edge_count
         FROM kg_projection_kernel_receipts
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(projection_scope)
    .bind(i64::try_from(generation.generation.get()).map_err(|_| {
        CognitiveStoreError::Corrupt("KG generation exceeds i64".to_string())
    })?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;

    if let Some(row) = existing {
        let exact = row
            .try_get::<String, _>("source_snapshot_sha256")
            .map_err(unavailable)?
            == generation.source_snapshot_digest.to_string()
            && row
                .try_get::<String, _>("generation_vector_sha256")
                .map_err(unavailable)?
                == generation.generation_vector_digest.to_string()
            && row
                .try_get::<String, _>("graph_profile_sha256")
                .map_err(unavailable)?
                == generation.graph_profile_digest.to_string()
            && row
                .try_get::<String, _>("generation_sha256")
                .map_err(unavailable)?
                == generation.generation_digest.to_string()
            && row
                .try_get::<Option<i64>, _>("predecessor_generation")
                .map_err(unavailable)?
                == predecessor_generation
            && row
                .try_get::<Option<String>, _>("predecessor_sha256")
                .map_err(unavailable)?
                == predecessor_sha256
            && row
                .try_get::<String, _>("publication_sha256")
                .map_err(unavailable)?
                == publication.publication_digest.to_string()
            && row.try_get::<String, _>("disposition").map_err(unavailable)? == disposition
            && row.try_get::<i64, _>("node_count").map_err(unavailable)?
                == i64::try_from(generation.nodes.len()).unwrap_or(i64::MAX)
            && row.try_get::<i64, _>("edge_count").map_err(unavailable)?
                == i64::try_from(generation.edges.len()).unwrap_or(i64::MAX);
        if !exact {
            return Err(CognitiveStoreError::Corrupt(format!(
                "stored hepta-kg receipt disagrees with rebuilt projection {projection_scope}/{}",
                generation.generation.get()
            )));
        }
        return Ok(());
    }

    sqlx::query(
        "INSERT INTO kg_projection_kernel_receipts (
             projection_scope, generation, source_snapshot_sha256,
             generation_vector_sha256, graph_profile_sha256, generation_sha256,
             predecessor_generation, predecessor_sha256, publication_sha256,
             disposition, node_count, edge_count, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
    )
    .bind(projection_scope)
    .bind(i64::try_from(generation.generation.get()).map_err(|_| {
        CognitiveStoreError::Corrupt("KG generation exceeds i64".to_string())
    })?)
    .bind(generation.source_snapshot_digest.to_string())
    .bind(generation.generation_vector_digest.to_string())
    .bind(generation.graph_profile_digest.to_string())
    .bind(generation.generation_digest.to_string())
    .bind(predecessor_generation)
    .bind(predecessor_sha256)
    .bind(publication.publication_digest.to_string())
    .bind(disposition)
    .bind(i64::try_from(generation.nodes.len()).map_err(|_| {
        CognitiveStoreError::Corrupt("KG kernel node count exceeds i64".to_string())
    })?)
    .bind(i64::try_from(generation.edges.len()).map_err(|_| {
        CognitiveStoreError::Corrupt("KG kernel edge count exceeds i64".to_string())
    })?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(crate) async fn backfill_kernel_receipts(
    pool: &SqlitePool,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool.begin().await.map_err(unavailable)?;
    let missing_receipts: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM kg_projection_generation_receipts r
         LEFT JOIN kg_projection_kernel_receipts k
           ON k.projection_scope = r.projection_scope
          AND k.generation = r.generation
         WHERE k.projection_scope IS NULL",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if missing_receipts == 0 {
        transaction.commit().await.map_err(unavailable)?;
        return Ok(());
    }
    let rows = sqlx::query(
        "SELECT projection_scope, generation
         FROM kg_projection_generation_receipts
         ORDER BY projection_scope, generation",
    )
    .fetch_all(&mut *transaction)
    .await
    .map_err(unavailable)?;
    let mut current_scope = String::new();
    let mut predecessor: Option<KnowledgeGenerationV2> = None;
    for row in rows {
        let projection_scope: String = row.try_get("projection_scope").map_err(unavailable)?;
        let generation_number: i64 = row.try_get("generation").map_err(unavailable)?;
        if projection_scope != current_scope {
            current_scope = projection_scope.clone();
            predecessor = None;
        }
        let generation = load_kernel_generation_tx(
            &mut transaction,
            &projection_scope,
            generation_number,
        )
        .await?
        .ok_or_else(|| {
            CognitiveStoreError::Corrupt(format!(
                "KG projection receipt {projection_scope}/{generation_number} has no durable rows"
            ))
        })?;
        let publication = publish_generation(predecessor.as_ref(), &generation).map_err(|error| {
            CognitiveStoreError::Corrupt(format!(
                "hepta-kg rejected persisted generation chain {projection_scope}/{generation_number}: {error}"
            ))
        })?;
        persist_kernel_receipt_tx(
            &mut transaction,
            &projection_scope,
            &generation,
            &publication,
        )
        .await?;
        predecessor = Some(generation);
    }
    transaction.commit().await.map_err(unavailable)?;
    Ok(())
}

fn support(
    memory_id: &str,
    memory_revision: i64,
    source_id: &str,
    source_revision: i64,
    validity_digest: Digest32,
    support_fact_digests: &BTreeMap<(String, i64), String>,
) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    let fact = support_fact_digests
        .get(&(memory_id.to_string(), memory_revision))
        .ok_or_else(|| {
            CognitiveStoreError::Corrupt(format!(
                "KG projection row {memory_id}/{memory_revision} has no immutable fact-set digest"
            ))
        })?;
    Ok(KnowledgeSupportV2 {
        source_id: stable_id(source_id, "KG support source")?,
        source_revision: Revision::new(u64::try_from(source_revision).map_err(|_| {
            CognitiveStoreError::Corrupt("negative KG support source revision".to_string())
        })?)
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!("invalid KG support source revision: {error}"))
        })?,
        source_fact_digest: parse_digest(fact, "KG support fact set")?,
        validity_digest,
        tombstoned: false,
    })
}

fn relation_kind(value: &str) -> KnowledgeRelationKindV2 {
    match value {
        "supports" => KnowledgeRelationKindV2::Supports,
        "contradicts" => KnowledgeRelationKindV2::Contradicts,
        "temporal_before" => KnowledgeRelationKindV2::TemporalBefore,
        "temporal_after" => KnowledgeRelationKindV2::TemporalAfter,
        "causes" => KnowledgeRelationKindV2::Causes,
        "enables" => KnowledgeRelationKindV2::Enables,
        "procedure_step" => KnowledgeRelationKindV2::ProcedureStep,
        "prompt_complements" => KnowledgeRelationKindV2::PromptComplements,
        "prompt_substitutes" => KnowledgeRelationKindV2::PromptSubstitutes,
        "prompt_conflicts" => KnowledgeRelationKindV2::PromptConflicts,
        _ => KnowledgeRelationKindV2::Domain,
    }
}

fn stable_id(value: &str, label: &str) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string()).map_err(|error| {
        CognitiveStoreError::Corrupt(format!("{label} is not a stable V2 identity: {error}"))
    })
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, CognitiveStoreError> {
    Digest32::from_str(value).map_err(|error| {
        CognitiveStoreError::Corrupt(format!("{label} is not a canonical SHA-256 digest: {error}"))
    })
}

fn validity_digest(
    domain: &[u8],
    valid_from: i64,
    valid_to: Option<i64>,
    extra: &[&[u8]],
) -> Digest32 {
    let from = valid_from.to_be_bytes();
    let to = valid_to.unwrap_or(i64::MIN).to_be_bytes();
    let mut parts = Vec::with_capacity(extra.len() + 2);
    parts.push(from.as_slice());
    parts.push(to.as_slice());
    parts.extend_from_slice(extra);
    digest_parts(domain, &parts)
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&u64::try_from(parts.len()).unwrap_or(u64::MAX).to_be_bytes());
    for part in parts {
        bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Digest32::of_bytes(&bytes)
}
