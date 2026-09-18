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
