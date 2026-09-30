use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeSupportV2;

use super::model::KnowledgeLocalMutationReceiptV3;
use super::model::KnowledgeLocalMutationWorkV3;
use super::model::KnowledgeLocalStorageDeltaV3;

const STATE_DOMAIN: &[u8] = b"hepta.knowledge-local-state.v3";
const PREPARED_DOMAIN: &[u8] = b"hepta.knowledge-local-prepared.v3";
const RECEIPT_DOMAIN: &[u8] = b"hepta.knowledge-local-receipt.v3";
const NODE_KEY_DOMAIN: &[u8] = b"hepta.knowledge-local-node-key.v3";
const EDGE_KEY_DOMAIN: &[u8] = b"hepta.knowledge-local-edge-key.v3";
const NODE_VALUE_DOMAIN: &[u8] = b"hepta.knowledge-local-node-value.v3";
const EDGE_VALUE_DOMAIN: &[u8] = b"hepta.knowledge-local-edge-value.v3";

pub(super) fn node_entry_key(node_id: &StableId) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(NODE_KEY_DOMAIN);
    push_id(&mut bytes, node_id);
    *Digest32::of_bytes(&bytes).as_array()
}

pub(super) fn edge_entry_key(identity: &KnowledgeEdgeIdentityV2) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EDGE_KEY_DOMAIN);
    push_edge_identity(&mut bytes, identity);
    *Digest32::of_bytes(&bytes).as_array()
}

pub(super) fn node_value_hash(node: &KnowledgeNodeV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(NODE_VALUE_DOMAIN);
    push_id(&mut bytes, &node.node_id);
    push_id(&mut bytes, &node.node_kind_id);
    push_digest(&mut bytes, node.payload_digest);
    push_supports(&mut bytes, &node.supports);
    Digest32::of_bytes(&bytes)
}

pub(super) fn edge_value_hash(edge: &KnowledgeEdgeV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EDGE_VALUE_DOMAIN);
    push_edge_identity(&mut bytes, &edge.identity);
    push_u64(&mut bytes, edge.confidence.raw());
    push_digest(&mut bytes, edge.validity_digest);
    push_supports(&mut bytes, &edge.supports);
    Digest32::of_bytes(&bytes)
}

pub(super) fn compute_state_root(
    generation: Generation,
    source_snapshot_digest: Digest32,
    generation_vector_digest: Digest32,
    graph_profile_digest: Digest32,
    tree_hash: Digest32,
    node_count: u64,
    edge_count: u64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(STATE_DOMAIN);
    push_u64(&mut bytes, generation.get());
    push_digest(&mut bytes, source_snapshot_digest);
    push_digest(&mut bytes, generation_vector_digest);
    push_digest(&mut bytes, graph_profile_digest);
    push_digest(&mut bytes, tree_hash);
    push_u64(&mut bytes, node_count);
    push_u64(&mut bytes, edge_count);
    Digest32::of_bytes(&bytes)
}

pub(super) fn compute_preparation_digest(
    prepared: &KnowledgeLocalStorageDeltaV3,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PREPARED_DOMAIN);
    push_u64(
        &mut bytes,
        prepared.expected_predecessor_generation.get(),
    );
    push_digest(&mut bytes, prepared.expected_predecessor_state_root);
    push_u64(&mut bytes, prepared.generation.get());
    push_digest(&mut bytes, prepared.source_snapshot_digest);
    push_digest(&mut bytes, prepared.generation_vector_digest);
    push_digest(&mut bytes, prepared.graph_profile_digest);
    push_len(&mut bytes, prepared.remove_edge_identities.len());
    for identity in &prepared.remove_edge_identities {
        push_edge_identity(&mut bytes, identity);
    }
    push_len(&mut bytes, prepared.remove_node_ids.len());
    for node_id in &prepared.remove_node_ids {
        push_id(&mut bytes, node_id);
    }
    push_len(&mut bytes, prepared.upsert_nodes.len());
    for node in &prepared.upsert_nodes {
        push_digest(&mut bytes, node_value_hash(node));
    }
    push_len(&mut bytes, prepared.upsert_edges.len());
    for edge in &prepared.upsert_edges {
        push_digest(&mut bytes, edge_value_hash(edge));
    }
    push_digest(&mut bytes, prepared.resulting_state_root);
    push_u64(&mut bytes, prepared.resulting_node_count);
    push_u64(&mut bytes, prepared.resulting_edge_count);
    bytes.push(u8::from(prepared.full_rebuild_audit_due));
    push_work(&mut bytes, prepared.work);
    Digest32::of_bytes(&bytes)
}

pub(super) fn compute_receipt_digest(
    receipt: &KnowledgeLocalMutationReceiptV3,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(RECEIPT_DOMAIN);
    push_u64(&mut bytes, receipt.predecessor_generation.get());
    push_digest(&mut bytes, receipt.predecessor_state_root);
    push_u64(&mut bytes, receipt.generation.get());
    push_digest(&mut bytes, receipt.source_snapshot_digest);
    push_digest(&mut bytes, receipt.generation_vector_digest);
    push_digest(&mut bytes, receipt.graph_profile_digest);
    push_digest(&mut bytes, receipt.state_root);
    push_u64(&mut bytes, receipt.node_count);
    push_u64(&mut bytes, receipt.edge_count);
    bytes.push(u8::from(receipt.full_rebuild_audit_due));
    push_digest(&mut bytes, receipt.preparation_digest);
    Digest32::of_bytes(&bytes)
}

fn push_work(bytes: &mut Vec<u8>, work: KnowledgeLocalMutationWorkV3) {
    push_u64(bytes, work.predecessor_nodes_read);
    push_u64(bytes, work.predecessor_edges_read);
    push_u64(bytes, work.supports_inspected);
    push_u64(bytes, work.treap_leaf_updates);
    push_u64(bytes, work.treap_nodes_rehashed);
    push_u64(bytes, work.full_entries_scanned);
}

pub(super) fn push_edge_identity(
    bytes: &mut Vec<u8>,
    identity: &KnowledgeEdgeIdentityV2,
) {
    push_id(bytes, &identity.source_node_id);
    push_relation_kind(bytes, &identity.relation);
    push_id(bytes, &identity.target_node_id);
}

fn push_supports(bytes: &mut Vec<u8>, supports: &[KnowledgeSupportV2]) {
    push_len(bytes, supports.len());
    for support in supports {
        push_id(bytes, &support.source_id);
        push_u64(bytes, support.source_revision.get());
        push_digest(bytes, support.source_fact_digest);
        push_digest(bytes, support.validity_digest);
        match support.valid_from_unix_seconds {
            Some(value) => {
                bytes.push(1);
                push_i64(bytes, value);
            }
            None => bytes.push(0),
        }
        match support.valid_to_unix_seconds {
            Some(value) => {
                bytes.push(1);
                push_i64(bytes, value);
            }
            None => bytes.push(0),
        }
        bytes.push(u8::from(support.tombstoned));
    }
}

fn push_relation_kind(bytes: &mut Vec<u8>, value: &KnowledgeRelationKindV2) {
    match value {
        KnowledgeRelationKindV2::Supports => bytes.push(0),
        KnowledgeRelationKindV2::Contradicts => bytes.push(1),
        KnowledgeRelationKindV2::TemporalBefore => bytes.push(2),
        KnowledgeRelationKindV2::TemporalAfter => bytes.push(3),
        KnowledgeRelationKindV2::Causes => bytes.push(4),
        KnowledgeRelationKindV2::Enables => bytes.push(5),
        KnowledgeRelationKindV2::ProcedureStep => bytes.push(6),
        KnowledgeRelationKindV2::PromptComplements => bytes.push(7),
        KnowledgeRelationKindV2::PromptSubstitutes => bytes.push(8),
        KnowledgeRelationKindV2::PromptConflicts => bytes.push(9),
        KnowledgeRelationKindV2::Custom(identifier) => {
            bytes.push(10);
            push_id(bytes, identifier);
        }
        KnowledgeRelationKindV2::PromptRequires => bytes.push(11),
        KnowledgeRelationKindV2::PromptDominates => bytes.push(12),
        KnowledgeRelationKindV2::PromptRedundant => bytes.push(13),
        KnowledgeRelationKindV2::PromptSupersedes => bytes.push(14),
    }
}

pub(super) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

pub(super) fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, usize_to_u64(value));
}

pub(super) fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

pub(super) fn usize_to_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}
