//! Canonical durable projection semantics shared by the knowledge-graph kernel
//! and the SQLite cognitive owner.
//!
//! This module intentionally models the physical projection rows without
//! narrowing product-defined relation labels into the closed symbolic
//! `KnowledgeRelationKindV2` set. It centralizes the invariants that must agree
//! across in-memory generation logic and durable materialization: stable
//! identity, support lineage binding, edge endpoint completeness and canonical
//! digest framing. The digest domains remain byte-compatible with the existing
//! SQLite v1 receipts so reopening an existing database does not invalidate
//! previously published generations.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeSupportV2;
use crate::build_complete_generation;
use sha2::Digest;
use sha2::Sha256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableProjectionHeadV2 {
    pub memory_id: String,
    pub revision: i64,
    pub content_sha256: String,
    pub verification: String,
    pub lifecycle: String,
    pub fact_set_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableProjectionNodeV2 {
    pub node_id: String,
    pub canonical_entity_id: String,
    pub entity_type: String,
    pub label: String,
    pub valid_from: i64,
    pub valid_to: Option<i64>,
    pub memory_id: String,
    pub memory_revision: i64,
    pub source_id: String,
    pub source_revision: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableProjectionEdgeV2 {
    pub edge_id: String,
    pub canonical_relation_id: String,
    pub from_node_id: String,
    pub to_node_id: String,
    pub relation: String,
    pub valid_from: i64,
    pub valid_to: Option<i64>,
    pub memory_id: String,
    pub memory_revision: i64,
    pub source_id: String,
    pub source_revision: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableProjectionErrorV2 {
    DuplicateNodeId(String),
    DuplicateEdgeId(String),
    MissingEdgeEndpoint(String),
    InvalidMemoryRevision,
    InvalidSourceRevision,
    EmptyIdentity(&'static str),
    InvalidStableIdentity(&'static str),
    Generation(KnowledgeGenerationErrorV2),
}

impl fmt::Display for DurableProjectionErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateNodeId(id) => write!(formatter, "duplicate durable KG node id: {id}"),
            Self::DuplicateEdgeId(id) => write!(formatter, "duplicate durable KG edge id: {id}"),
            Self::MissingEdgeEndpoint(id) => {
                write!(formatter, "durable KG edge references an unknown node: {id}")
            }
            Self::InvalidMemoryRevision => {
                formatter.write_str("durable KG support memory revision must be positive")
            }
            Self::InvalidSourceRevision => {
                formatter.write_str("durable KG support source revision must be positive")
            }
            Self::EmptyIdentity(label) => write!(formatter, "durable KG {label} must not be empty"),
            Self::InvalidStableIdentity(label) => {
                write!(formatter, "durable KG {label} cannot be represented as a stable identity")
            }
            Self::Generation(error) => error.fmt(formatter),
        }
    }
}

impl StdError for DurableProjectionErrorV2 {}

pub fn validate_durable_projection_v2(
    nodes: &[DurableProjectionNodeV2],
    edges: &[DurableProjectionEdgeV2],
) -> Result<(), DurableProjectionErrorV2> {
    let mut node_ids = BTreeSet::new();
    for node in nodes {
        ensure_nonempty("node id", &node.node_id)?;
        ensure_nonempty("canonical entity id", &node.canonical_entity_id)?;
        ensure_nonempty("memory id", &node.memory_id)?;
        ensure_nonempty("source id", &node.source_id)?;
        if node.memory_revision <= 0 {
            return Err(DurableProjectionErrorV2::InvalidMemoryRevision);
        }
        if node.source_revision <= 0 {
            return Err(DurableProjectionErrorV2::InvalidSourceRevision);
        }
        if !node_ids.insert(node.node_id.clone()) {
            return Err(DurableProjectionErrorV2::DuplicateNodeId(
                node.node_id.clone(),
            ));
        }
    }

    let mut edge_ids = BTreeSet::new();
    for edge in edges {
        ensure_nonempty("edge id", &edge.edge_id)?;
        ensure_nonempty("canonical relation id", &edge.canonical_relation_id)?;
        ensure_nonempty("relation", &edge.relation)?;
        ensure_nonempty("memory id", &edge.memory_id)?;
        ensure_nonempty("source id", &edge.source_id)?;
        if edge.memory_revision <= 0 {
            return Err(DurableProjectionErrorV2::InvalidMemoryRevision);
        }
        if edge.source_revision <= 0 {
            return Err(DurableProjectionErrorV2::InvalidSourceRevision);
        }
        if !edge_ids.insert(edge.edge_id.clone()) {
            return Err(DurableProjectionErrorV2::DuplicateEdgeId(
                edge.edge_id.clone(),
            ));
        }
        if !node_ids.contains(&edge.from_node_id) {
            return Err(DurableProjectionErrorV2::MissingEdgeEndpoint(
                edge.from_node_id.clone(),
            ));
        }
        if !node_ids.contains(&edge.to_node_id) {
            return Err(DurableProjectionErrorV2::MissingEdgeEndpoint(
                edge.to_node_id.clone(),
            ));
        }
    }
    Ok(())
}

pub fn durable_input_heads_digest_v2(
    scope: &str,
    heads: &[DurableProjectionHeadV2],
) -> Digest32 {
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

pub fn durable_projection_digest_v2(
    scope: &str,
    nodes: &[DurableProjectionNodeV2],
    edges: &[DurableProjectionEdgeV2],
) -> Result<Digest32, DurableProjectionErrorV2> {
    validate_durable_projection_v2(nodes, edges)?;

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
    Ok(finish_digest(hasher))
}


/// Adapts one exact durable SQLite projection cut into the canonical V2
/// generation model without losing open-ended product relation vocabulary.
///
/// The legacy durable output digest remains the persisted physical digest. The
/// returned V2 generation adds typed relation identity and explicit support
/// lineage over the same rows.
pub fn build_durable_generation_v2(
    generation: Generation,
    scope: &str,
    heads: &[DurableProjectionHeadV2],
    nodes: &[DurableProjectionNodeV2],
    edges: &[DurableProjectionEdgeV2],
) -> Result<KnowledgeGenerationV2, DurableProjectionErrorV2> {
    build_durable_generation_from_snapshot_v2(
        generation,
        scope,
        durable_input_heads_digest_v2(scope, heads),
        nodes,
        edges,
    )
}

pub fn build_durable_generation_from_snapshot_v2(
    generation: Generation,
    scope: &str,
    source_snapshot_digest: Digest32,
    nodes: &[DurableProjectionNodeV2],
    edges: &[DurableProjectionEdgeV2],
) -> Result<KnowledgeGenerationV2, DurableProjectionErrorV2> {
    validate_durable_projection_v2(nodes, edges)?;
    let generation_vector_digest = domain_digest(
        b"hepta.knowledge-durable-generation-vector.v2",
        &[scope.as_bytes(), source_snapshot_digest.as_array()],
    );
    let graph_profile_digest =
        Digest32::of_bytes(b"hepta.knowledge-durable-sqlite-profile.v2");

    let v2_nodes = nodes
        .iter()
        .map(durable_node_to_v2)
        .collect::<Result<Vec<_>, _>>()?;
    let v2_edges = edges
        .iter()
        .map(durable_edge_to_v2)
        .collect::<Result<Vec<_>, _>>()?;

    build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest,
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes: v2_nodes,
            edges: v2_edges,
        },
    )
    .map_err(DurableProjectionErrorV2::Generation)
}

pub fn durable_relation_kind_v2(
    relation: &str,
) -> Result<KnowledgeRelationKindV2, DurableProjectionErrorV2> {
    let builtin = match relation {
        "supports" => Some(KnowledgeRelationKindV2::Supports),
        "contradicts" => Some(KnowledgeRelationKindV2::Contradicts),
        "temporal_before" => Some(KnowledgeRelationKindV2::TemporalBefore),
        "temporal_after" => Some(KnowledgeRelationKindV2::TemporalAfter),
        "causes" => Some(KnowledgeRelationKindV2::Causes),
        "enables" => Some(KnowledgeRelationKindV2::Enables),
        "procedure_step" => Some(KnowledgeRelationKindV2::ProcedureStep),
        "prompt_complements" => Some(KnowledgeRelationKindV2::PromptComplements),
        "prompt_substitutes" => Some(KnowledgeRelationKindV2::PromptSubstitutes),
        "prompt_conflicts" => Some(KnowledgeRelationKindV2::PromptConflicts),
        _ => None,
    };
    if let Some(kind) = builtin {
        return Ok(kind);
    }
    ensure_nonempty("relation", relation)?;
    let digest = Digest32::of_bytes(relation.as_bytes());
    let predicate_id = StableId::new(format!("kg-predicate:v2:{digest}"))
        .map_err(|_| DurableProjectionErrorV2::InvalidStableIdentity("relation predicate"))?;
    Ok(KnowledgeRelationKindV2::CustomPredicate(predicate_id))
}

fn durable_node_to_v2(
    node: &DurableProjectionNodeV2,
) -> Result<KnowledgeNodeV2, DurableProjectionErrorV2> {
    let node_id = stable_id("node id", &node.node_id)?;
    let kind_digest = Digest32::of_bytes(node.entity_type.as_bytes());
    let node_kind_id = StableId::new(format!("kg-node-kind:v2:{kind_digest}"))
        .map_err(|_| DurableProjectionErrorV2::InvalidStableIdentity("node kind"))?;
    let payload_digest = domain_digest(
        b"hepta.knowledge-durable-node-payload.v2",
        &[
            node.canonical_entity_id.as_bytes(),
            node.entity_type.as_bytes(),
            node.label.as_bytes(),
            &node.valid_from.to_be_bytes(),
            &node.valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        ],
    );
    Ok(KnowledgeNodeV2 {
        node_id,
        node_kind_id,
        payload_digest,
        supports: vec![durable_support_v2(
            &node.source_id,
            node.source_revision,
            b"hepta.knowledge-durable-node-support.v2",
            &[
                node.memory_id.as_bytes(),
                &node.memory_revision.to_be_bytes(),
                node.canonical_entity_id.as_bytes(),
                node.entity_type.as_bytes(),
                node.label.as_bytes(),
            ],
            node.valid_from,
            node.valid_to,
        )?],
    })
}

fn durable_edge_to_v2(
    edge: &DurableProjectionEdgeV2,
) -> Result<KnowledgeEdgeV2, DurableProjectionErrorV2> {
    let validity_digest = validity_digest(edge.valid_from, edge.valid_to);
    Ok(KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: stable_id("edge source node id", &edge.from_node_id)?,
            relation: durable_relation_kind_v2(&edge.relation)?,
            target_node_id: stable_id("edge target node id", &edge.to_node_id)?,
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest,
        supports: vec![durable_support_v2(
            &edge.source_id,
            edge.source_revision,
            b"hepta.knowledge-durable-edge-support.v2",
            &[
                edge.memory_id.as_bytes(),
                &edge.memory_revision.to_be_bytes(),
                edge.canonical_relation_id.as_bytes(),
                edge.relation.as_bytes(),
                edge.from_node_id.as_bytes(),
                edge.to_node_id.as_bytes(),
            ],
            edge.valid_from,
            edge.valid_to,
        )?],
    })
}

fn durable_support_v2(
    source_id: &str,
    source_revision: i64,
    domain: &[u8],
    fact_parts: &[&[u8]],
    valid_from: i64,
    valid_to: Option<i64>,
) -> Result<KnowledgeSupportV2, DurableProjectionErrorV2> {
    let source_revision = u64::try_from(source_revision)
        .ok()
        .and_then(|value| Revision::new(value).ok())
        .ok_or(DurableProjectionErrorV2::InvalidSourceRevision)?;
    let mut support_parts = Vec::with_capacity(fact_parts.len() + 2);
    support_parts.extend_from_slice(fact_parts);
    let from = valid_from.to_be_bytes();
    let to = valid_to.unwrap_or(i64::MIN).to_be_bytes();
    support_parts.push(&from);
    support_parts.push(&to);
    Ok(KnowledgeSupportV2 {
        source_id: stable_id("support source id", source_id)?,
        source_revision,
        source_fact_digest: domain_digest(domain, &support_parts),
        validity_digest: validity_digest(valid_from, valid_to),
        tombstoned: false,
    })
}

fn stable_id(
    label: &'static str,
    value: &str,
) -> Result<StableId, DurableProjectionErrorV2> {
    StableId::new(value.to_string())
        .map_err(|_| DurableProjectionErrorV2::InvalidStableIdentity(label))
}

fn validity_digest(valid_from: i64, valid_to: Option<i64>) -> Digest32 {
    domain_digest(
        b"hepta.knowledge-durable-validity.v2",
        &[
            &valid_from.to_be_bytes(),
            &valid_to.unwrap_or(i64::MIN).to_be_bytes(),
        ],
    )
}

fn domain_digest(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    finish_digest(hasher)
}

fn ensure_nonempty(
    label: &'static str,
    value: &str,
) -> Result<(), DurableProjectionErrorV2> {
    if value.is_empty() {
        return Err(DurableProjectionErrorV2::EmptyIdentity(label));
    }
    Ok(())
}

fn frame_part(hasher: &mut Sha256, part: &[u8]) {
    hasher.update((part.len() as u64).to_be_bytes());
    hasher.update(part);
}

fn finish_digest(hasher: Sha256) -> Digest32 {
    let output = hasher.finalize();
    let mut bytes = [0_u8; 32];
    bytes.copy_from_slice(&output);
    Digest32::from_array(bytes)
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;
