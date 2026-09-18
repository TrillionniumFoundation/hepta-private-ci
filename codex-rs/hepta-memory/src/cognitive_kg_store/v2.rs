use std::collections::BTreeMap;
use std::str::FromStr;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::MAX_SCOPE_EDGES;
use super::MAX_SCOPE_NODES;
use super::ProjectionEdge;
use super::ProjectionHead;
use super::ProjectionNode;
use crate::CognitiveStoreError;
use crate::cognitive_intelligence_writer::occurrence_edge_id;
use crate::cognitive_store::unavailable;

const PROFILE_DOMAIN: &[u8] = b"hepta:cognitive:sqlite-kg-profile:v2";
const VECTOR_DOMAIN: &[u8] = b"hepta:cognitive:kg-generation-vector:v2";
const NODE_PAYLOAD_DOMAIN: &[u8] = b"hepta:cognitive:kg-node-payload:v2";
const NODE_VALIDITY_DOMAIN: &[u8] = b"hepta:cognitive:kg-node-validity:v2";
const EDGE_VALIDITY_DOMAIN: &[u8] = b"hepta:cognitive:kg-edge-validity:v2";
const NODE_SUPPORT_DOMAIN: &[u8] = b"hepta:cognitive:kg-node-support:v2";
const EDGE_SUPPORT_DOMAIN: &[u8] = b"hepta:cognitive:kg-edge-support:v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct NodeMetadataV2 {
    pub(crate) canonical_entity_id: String,
    pub(crate) valid_from: i64,
    pub(crate) valid_to: Option<i64>,
    pub(crate) memory_id: String,
    pub(crate) memory_revision: i64,
}

impl NodeMetadataV2 {
    pub(crate) fn visible_at(&self, now: i64) -> bool {
        self.valid_from <= now && self.valid_to.is_none_or(|until| now < until)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EdgeMetadataV2 {
    pub(crate) edge_id: String,
    pub(crate) valid_from: i64,
    pub(crate) valid_to: Option<i64>,
    pub(crate) memory_id: String,
    pub(crate) memory_revision: i64,
}

impl EdgeMetadataV2 {
    pub(crate) fn visible_at(&self, now: i64) -> bool {
        self.valid_from <= now && self.valid_to.is_none_or(|until| now < until)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct LoadedProjectionV2 {
    pub(crate) generation: KnowledgeGenerationV2,
    pub(crate) nodes: BTreeMap<StableId, NodeMetadataV2>,
    pub(crate) edges: BTreeMap<KnowledgeEdgeIdentityV2, EdgeMetadataV2>,
}

impl LoadedProjectionV2 {
    pub(crate) fn seed_node_ids(&self, canonical_entity_id: &str, now: i64) -> Vec<StableId> {
        self.nodes
            .iter()
            .filter(|(_, metadata)| {
                metadata.canonical_entity_id == canonical_entity_id && metadata.visible_at(now)
            })
            .map(|(node_id, _)| node_id.clone())
            .collect()
    }
}

pub(crate) fn build_generation(
    projection_scope: &str,
    generation: u64,
    input_heads_sha256: &Sha256Digest,
    heads: &[ProjectionHead],
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let support_digests = support_digests_from_heads(heads)?;
    build_generation_with_supports(
        projection_scope,
        generation,
        input_heads_sha256,
        nodes,
        edges,
        &support_digests,
        FailureClass::Invalid,
    )
}

pub(crate) fn generation_digest(
    projection_scope: &str,
    generation: u64,
    input_heads_sha256: &Sha256Digest,
    heads: &[ProjectionHead],
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
) -> Result<Sha256Digest, CognitiveStoreError> {
    let generation = build_generation(
        projection_scope,
        generation,
        input_heads_sha256,
        heads,
        nodes,
        edges,
    )?;
    Sha256Digest::parse(generation.generation_digest.to_string())
        .map_err(CognitiveStoreError::Corrupt)
}

pub(crate) async fn load_generation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    generation: i64,
) -> Result<LoadedProjectionV2, CognitiveStoreError> {
    let generation_u64 = u64::try_from(generation)
        .map_err(|_| CognitiveStoreError::Corrupt("negative KG generation".to_string()))?;
    let receipt = sqlx::query(
        "SELECT input_heads_sha256, output_sha256, node_count, edge_count
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
    let stored_output_sha256 = Sha256Digest::parse(
        receipt
            .try_get::<String, _>("output_sha256")
            .map_err(unavailable)?,
    )
    .map_err(CognitiveStoreError::Corrupt)?;
    let expected_node_count: i64 = receipt.try_get("node_count").map_err(unavailable)?;
    let expected_edge_count: i64 = receipt.try_get("edge_count").map_err(unavailable)?;

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
         ORDER BY n.node_id LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_NODES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if node_rows.len() > MAX_SCOPE_NODES {
        return Err(CognitiveStoreError::Corrupt(format!(
            "stored KG projection exceeds the {MAX_SCOPE_NODES}-node V2 load limit"
        )));
    }
    if i64::try_from(node_rows.len()).ok() != Some(expected_node_count) {
        return Err(CognitiveStoreError::Corrupt(
            "stored KG node count does not match its immutable generation receipt".to_string(),
        ));
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
         ORDER BY e.edge_id LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if edge_rows.len() > MAX_SCOPE_EDGES {
        return Err(CognitiveStoreError::Corrupt(format!(
            "stored KG projection exceeds the {MAX_SCOPE_EDGES}-edge V2 load limit"
        )));
    }
    if i64::try_from(edge_rows.len()).ok() != Some(expected_edge_count) {
        return Err(CognitiveStoreError::Corrupt(
            "stored KG edge count does not match its immutable generation receipt".to_string(),
        ));
    }

    let relation_rows = sqlx::query(
        "SELECT q.memory_id, q.memory_revision, q.relation_key,
                q.canonical_relation_id
         FROM kg_revision_relations q
         WHERE EXISTS (
             SELECT 1 FROM kg_edges e
             WHERE e.projection_scope = ? AND e.generation = ?
               AND e.memory_id = q.memory_id
               AND e.memory_revision = q.memory_revision
         )
         ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
    )
    .bind(projection_scope)
    .bind(generation)
    .bind(limit_plus_one(MAX_SCOPE_EDGES)?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if relation_rows.len() > MAX_SCOPE_EDGES {
        return Err(CognitiveStoreError::Corrupt(format!(
            "stored KG relation supports exceed the {MAX_SCOPE_EDGES}-edge V2 load limit"
        )));
    }
    let relation_ids = relation_rows
        .into_iter()
        .map(|row| {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
            let edge_id = occurrence_edge_id(&memory_id, memory_revision, &relation_key);
            let canonical_relation_id: String =
                row.try_get("canonical_relation_id").map_err(unavailable)?;
            Ok((edge_id, canonical_relation_id))
        })
        .collect::<Result<BTreeMap<_, _>, CognitiveStoreError>>()?;

    let mut nodes = Vec::with_capacity(node_rows.len());
    let mut node_metadata = BTreeMap::new();
    for row in node_rows {
        let projection_node = ProjectionNode {
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
        };
        let fact_set_sha256: String = row.try_get("fact_set_sha256").map_err(unavailable)?;
        let node = adapt_node(&projection_node, &fact_set_sha256, FailureClass::Corrupt)?;
        node_metadata.insert(
            node.node_id.clone(),
            NodeMetadataV2 {
                canonical_entity_id: projection_node.canonical_entity_id.clone(),
                valid_from: projection_node.valid_from,
                valid_to: projection_node.valid_to,
                memory_id: projection_node.memory_id.clone(),
                memory_revision: projection_node.memory_revision,
            },
        );
        nodes.push(node);
    }

    let mut edges = Vec::with_capacity(edge_rows.len());
    let mut edge_metadata = BTreeMap::new();
    for row in edge_rows {
        let edge_id: String = row.try_get("edge_id").map_err(unavailable)?;
        let canonical_relation_id = relation_ids.get(&edge_id).ok_or_else(|| {
            CognitiveStoreError::Corrupt(format!(
                "stored KG edge `{edge_id}` has no immutable relation support"
            ))
        })?;
        let projection_edge = ProjectionEdge {
            edge_id,
            canonical_relation_id: canonical_relation_id.clone(),
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
        };
        let fact_set_sha256: String = row.try_get("fact_set_sha256").map_err(unavailable)?;
        let edge = adapt_edge(&projection_edge, &fact_set_sha256, FailureClass::Corrupt)?;
        edge_metadata.insert(
            edge.identity.clone(),
            EdgeMetadataV2 {
                edge_id: projection_edge.edge_id.clone(),
                valid_from: projection_edge.valid_from,
                valid_to: projection_edge.valid_to,
                memory_id: projection_edge.memory_id.clone(),
                memory_revision: projection_edge.memory_revision,
            },
        );
        edges.push(edge);
    }

    let generation = build_complete_generation(
        Generation::new(generation_u64).map_err(|error| {
            CognitiveStoreError::Corrupt(format!("invalid persisted KG generation: {error}"))
        })?,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: parse_digest(
                input_heads_sha256.as_str(),
                FailureClass::Corrupt,
            )?,
            generation_vector_digest: generation_vector_digest(
                projection_scope,
                &input_heads_sha256,
            ),
            graph_profile_digest: Digest32::of_bytes(PROFILE_DOMAIN),
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "persisted KG projection fails canonical V2 validation: {error}"
        ))
    })?;

    let v2_digest = Sha256Digest::parse(generation.generation_digest.to_string())
        .map_err(CognitiveStoreError::Corrupt)?;
    if stored_output_sha256 != v2_digest {
        // Historical generations written before the V2 composition retain the
        // predecessor projection digest. CognitiveStore::open verifies the
        // selected legacy generation against the immutable fact rows before any
        // product read is admitted. All generations published by the V2 path
        // bind this equality directly.
        let is_current: bool = sqlx::query_scalar(
            "SELECT EXISTS(
                 SELECT 1 FROM kg_projection
                 WHERE projection_scope = ? AND generation = ?
             )",
        )
        .bind(projection_scope)
        .bind(generation)
        .fetch_one(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if !is_current {
            return Err(CognitiveStoreError::Corrupt(
                "historical KG generation is not bound to the canonical V2 digest".to_string(),
            ));
        }
    }

    Ok(LoadedProjectionV2 {
        generation,
        nodes: node_metadata,
        edges: edge_metadata,
    })
}

fn support_digests_from_heads(
    heads: &[ProjectionHead],
) -> Result<BTreeMap<(String, i64), String>, CognitiveStoreError> {
    let mut result = BTreeMap::new();
    for head in heads {
        parse_digest(&head.fact_set_sha256, FailureClass::Invalid)?;
        if result
            .insert(
                (head.memory_id.clone(), head.revision),
                head.fact_set_sha256.clone(),
            )
            .is_some()
        {
            return Err(CognitiveStoreError::Corrupt(
                "duplicate current KG head identity".to_string(),
            ));
        }
    }
    Ok(result)
}

fn build_generation_with_supports(
    projection_scope: &str,
    generation: u64,
    input_heads_sha256: &Sha256Digest,
    nodes: &[ProjectionNode],
    edges: &[ProjectionEdge],
    support_digests: &BTreeMap<(String, i64), String>,
    failure_class: FailureClass,
) -> Result<KnowledgeGenerationV2, CognitiveStoreError> {
    let mut adapted_nodes = Vec::with_capacity(nodes.len());
    for node in nodes {
        let fact_set_sha256 = support_digests
            .get(&(node.memory_id.clone(), node.memory_revision))
            .ok_or_else(|| failure(
                failure_class,
                "projected KG node has no immutable current-head fact set".to_string(),
            ))?;
        adapted_nodes.push(adapt_node(node, fact_set_sha256, failure_class)?);
    }
    let mut adapted_edges = Vec::with_capacity(edges.len());
    for edge in edges {
        let fact_set_sha256 = support_digests
            .get(&(edge.memory_id.clone(), edge.memory_revision))
            .ok_or_else(|| failure(
                failure_class,
                "projected KG edge has no immutable current-head fact set".to_string(),
            ))?;
        adapted_edges.push(adapt_edge(edge, fact_set_sha256, failure_class)?);
    }

    build_complete_generation(
        Generation::new(generation).map_err(|error| {
            failure(
                failure_class,
                format!("invalid KG projection generation: {error}"),
            )
        })?,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: parse_digest(input_heads_sha256.as_str(), failure_class)?,
            generation_vector_digest: generation_vector_digest(
                projection_scope,
                input_heads_sha256,
            ),
            graph_profile_digest: Digest32::of_bytes(PROFILE_DOMAIN),
            complete_source_cut: true,
            nodes: adapted_nodes,
            edges: adapted_edges,
        },
    )
    .map_err(|error| {
        failure(
            failure_class,
            format!("canonical KG V2 rejected projection: {error}"),
        )
    })
}

fn adapt_node(
    node: &ProjectionNode,
    fact_set_sha256: &str,
    failure_class: FailureClass,
) -> Result<KnowledgeNodeV2, CognitiveStoreError> {
    parse_digest(fact_set_sha256, failure_class)?;
    let node_id = stable_id(&node.node_id, "KG node", failure_class)?;
    let node_kind_id = stable_id(
        "kind:cognitive-entity-occurrence-v2",
        "KG node kind",
        failure_class,
    )?;
    let node_validity = validity_digest(NODE_VALIDITY_DOMAIN, node.valid_from, node.valid_to);
    let source_fact_digest = framed_digest(
        NODE_SUPPORT_DOMAIN,
        &[
            fact_set_sha256.as_bytes(),
            node.canonical_entity_id.as_bytes(),
            node.node_id.as_bytes(),
        ],
    );
    let support = support(
        &node.source_id,
        node.source_revision,
        source_fact_digest,
        node_validity,
        failure_class,
    )?;
    Ok(KnowledgeNodeV2 {
        node_id,
        node_kind_id,
        payload_digest: framed_digest(
            NODE_PAYLOAD_DOMAIN,
            &[
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
                &node.valid_from.to_be_bytes(),
                &node.valid_to.unwrap_or(i64::MIN).to_be_bytes(),
                node.memory_id.as_bytes(),
                &node.memory_revision.to_be_bytes(),
                node.source_id.as_bytes(),
                &node.source_revision.to_be_bytes(),
            ],
        ),
        supports: vec![support],
    })
}

fn adapt_edge(
    edge: &ProjectionEdge,
    fact_set_sha256: &str,
    failure_class: FailureClass,
) -> Result<KnowledgeEdgeV2, CognitiveStoreError> {
    parse_digest(fact_set_sha256, failure_class)?;
    let validity_digest = framed_digest(
        EDGE_VALIDITY_DOMAIN,
        &[
            edge.canonical_relation_id.as_bytes(),
            edge.relation.as_bytes(),
            &edge.valid_from.to_be_bytes(),
            &edge.valid_to.unwrap_or(i64::MIN).to_be_bytes(),
            edge.memory_id.as_bytes(),
            &edge.memory_revision.to_be_bytes(),
        ],
    );
    Ok(KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: stable_id(&edge.from_node_id, "KG edge source", failure_class)?,
            relation: KnowledgeRelationKindV2::named_instance(
                edge.relation.as_bytes(),
                edge.edge_id.as_bytes(),
            ),
            target_node_id: stable_id(&edge.to_node_id, "KG edge target", failure_class)?,
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest,
        supports: vec![support(
            &edge.source_id,
            edge.source_revision,
            framed_digest(
                EDGE_SUPPORT_DOMAIN,
                &[
                    fact_set_sha256.as_bytes(),
                    edge.canonical_relation_id.as_bytes(),
                    edge.edge_id.as_bytes(),
                ],
            ),
            validity_digest,
            failure_class,
        )?],
    })
}

fn support(
    source_id: &str,
    source_revision: i64,
    source_fact_digest: Digest32,
    validity_digest: Digest32,
    failure_class: FailureClass,
) -> Result<KnowledgeSupportV2, CognitiveStoreError> {
    Ok(KnowledgeSupportV2 {
        source_id: stable_id(source_id, "KG support source", failure_class)?,
        source_revision: Revision::new(u64::try_from(source_revision).map_err(|_| {
            failure(
                failure_class,
                "negative KG source revision".to_string(),
            )
        })?)
        .map_err(|error| {
            failure(
                failure_class,
                format!("invalid KG source revision: {error}"),
            )
        })?,
        source_fact_digest,
        validity_digest,
        tombstoned: false,
    })
}

fn generation_vector_digest(projection_scope: &str, input_heads_sha256: &Sha256Digest) -> Digest32 {
    framed_digest(
        VECTOR_DOMAIN,
        &[projection_scope.as_bytes(), input_heads_sha256.as_str().as_bytes()],
    )
}

fn validity_digest(domain: &[u8], valid_from: i64, valid_to: Option<i64>) -> Digest32 {
    framed_digest(
        domain,
        &[
            &valid_from.to_be_bytes(),
            &valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        ],
    )
}

fn framed_digest(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::new();
    push_part(&mut bytes, domain);
    for part in parts {
        push_part(&mut bytes, part);
    }
    Digest32::of_bytes(&bytes)
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn stable_id(
    value: &str,
    label: &str,
    failure_class: FailureClass,
) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string()).map_err(|error| {
        failure(
            failure_class,
            format!("{label} is not a valid stable identifier: {error}"),
        )
    })
}

fn parse_digest(
    value: &str,
    failure_class: FailureClass,
) -> Result<Digest32, CognitiveStoreError> {
    Digest32::from_str(value).map_err(|error| {
        failure(
            failure_class,
            format!("invalid KG digest `{value}`: {error}"),
        )
    })
}

#[derive(Clone, Copy)]
enum FailureClass {
    Invalid,
    Corrupt,
}

fn failure(class: FailureClass, message: String) -> CognitiveStoreError {
    match class {
        FailureClass::Invalid => CognitiveStoreError::Invalid(message),
        FailureClass::Corrupt => CognitiveStoreError::Corrupt(message),
    }
}

fn limit_plus_one(value: usize) -> Result<i64, CognitiveStoreError> {
    value
        .checked_add(1)
        .and_then(|value| i64::try_from(value).ok())
        .ok_or_else(|| CognitiveStoreError::Invalid("KG V2 load limit exceeds i64".to_string()))
}
