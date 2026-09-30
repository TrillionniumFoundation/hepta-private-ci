use std::cmp::Ordering;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;

use super::digest::push_digest;
use super::digest::push_u64;
use super::model::KnowledgeLocalIncrementalErrorV3;
use super::model::KnowledgeLocalMutationWorkV3;

const EMPTY_DOMAIN: &[u8] = b"hepta.knowledge-local-treap-empty.v3";
const PRIORITY_DOMAIN: &[u8] = b"hepta.knowledge-local-treap-priority.v3";
const NODE_DOMAIN: &[u8] = b"hepta.knowledge-local-treap-node.v3";
const MAX_DEPTH: usize = 512;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) enum LocalEntryIdentityV3 {
    Node(StableId),
    Edge(KnowledgeEdgeIdentityV2),
}

#[derive(Clone, Debug)]
pub(super) struct LocalTreapNodeV3 {
    key: [u8; 32],
    priority: [u8; 32],
    value_hash: Digest32,
    left: Option<Arc<Self>>,
    right: Option<Arc<Self>>,
    subtree_size: u64,
    hash: Digest32,
}

pub(super) fn insert(
    root: Option<Arc<LocalTreapNodeV3>>,
    key: [u8; 32],
    value_hash: Digest32,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<Arc<LocalTreapNodeV3>, KnowledgeLocalIncrementalErrorV3> {
    insert_at(root, key, value_hash, 0, work)
}

pub(super) fn remove(
    root: Option<Arc<LocalTreapNodeV3>>,
    key: [u8; 32],
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<Option<Arc<LocalTreapNodeV3>>, KnowledgeLocalIncrementalErrorV3> {
    remove_at(root, key, 0, work)
}

pub(super) fn root_hash(root: &Option<Arc<LocalTreapNodeV3>>) -> Digest32 {
    root.as_ref()
        .map_or_else(|| Digest32::of_bytes(EMPTY_DOMAIN), |node| node.hash)
}

fn insert_at(
    root: Option<Arc<LocalTreapNodeV3>>,
    key: [u8; 32],
    value_hash: Digest32,
    depth: usize,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<Arc<LocalTreapNodeV3>, KnowledgeLocalIncrementalErrorV3> {
    ensure_depth(depth)?;
    let Some(node) = root else {
        return Ok(make_node(key, value_hash, None, None, work));
    };
    if key == node.key {
        return Ok(make_node(
            key,
            value_hash,
            node.left.clone(),
            node.right.clone(),
            work,
        ));
    }
    let priority = entry_priority(&key);
    if heap_order(&priority, &key, &node.priority, &node.key) == Ordering::Less {
        let (left, right) = split(Some(node), key, depth + 1, work)?;
        return Ok(make_node(key, value_hash, left, right, work));
    }
    if key < node.key {
        let left = insert_at(node.left.clone(), key, value_hash, depth + 1, work)?;
        Ok(make_node(
            node.key,
            node.value_hash,
            Some(left),
            node.right.clone(),
            work,
        ))
    } else {
        let right = insert_at(node.right.clone(), key, value_hash, depth + 1, work)?;
        Ok(make_node(
            node.key,
            node.value_hash,
            node.left.clone(),
            Some(right),
            work,
        ))
    }
}

fn remove_at(
    root: Option<Arc<LocalTreapNodeV3>>,
    key: [u8; 32],
    depth: usize,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<Option<Arc<LocalTreapNodeV3>>, KnowledgeLocalIncrementalErrorV3> {
    ensure_depth(depth)?;
    let Some(node) = root else {
        return Ok(None);
    };
    match key.cmp(&node.key) {
        Ordering::Less => {
            let left = remove_at(node.left.clone(), key, depth + 1, work)?;
            Ok(Some(make_node(
                node.key,
                node.value_hash,
                left,
                node.right.clone(),
                work,
            )))
        }
        Ordering::Greater => {
            let right = remove_at(node.right.clone(), key, depth + 1, work)?;
            Ok(Some(make_node(
                node.key,
                node.value_hash,
                node.left.clone(),
                right,
                work,
            )))
        }
        Ordering::Equal => merge(node.left.clone(), node.right.clone(), depth + 1, work),
    }
}

fn split(
    root: Option<Arc<LocalTreapNodeV3>>,
    key: [u8; 32],
    depth: usize,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<
    (
        Option<Arc<LocalTreapNodeV3>>,
        Option<Arc<LocalTreapNodeV3>>,
    ),
    KnowledgeLocalIncrementalErrorV3,
> {
    ensure_depth(depth)?;
    let Some(node) = root else {
        return Ok((None, None));
    };
    match node.key.cmp(&key) {
        Ordering::Less => {
            let (left_of_right, right) = split(node.right.clone(), key, depth + 1, work)?;
            let left = Some(make_node(
                node.key,
                node.value_hash,
                node.left.clone(),
                left_of_right,
                work,
            ));
            Ok((left, right))
        }
        Ordering::Greater => {
            let (left, right_of_left) = split(node.left.clone(), key, depth + 1, work)?;
            let right = Some(make_node(
                node.key,
                node.value_hash,
                right_of_left,
                node.right.clone(),
                work,
            ));
            Ok((left, right))
        }
        Ordering::Equal => Ok((node.left.clone(), node.right.clone())),
    }
}

fn merge(
    left: Option<Arc<LocalTreapNodeV3>>,
    right: Option<Arc<LocalTreapNodeV3>>,
    depth: usize,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Result<Option<Arc<LocalTreapNodeV3>>, KnowledgeLocalIncrementalErrorV3> {
    ensure_depth(depth)?;
    match (left, right) {
        (None, value) | (value, None) => Ok(value),
        (Some(left), Some(right)) => {
            if heap_order(
                &left.priority,
                &left.key,
                &right.priority,
                &right.key,
            ) == Ordering::Less
            {
                let merged = merge(left.right.clone(), Some(right), depth + 1, work)?;
                Ok(Some(make_node(
                    left.key,
                    left.value_hash,
                    left.left.clone(),
                    merged,
                    work,
                )))
            } else {
                let merged = merge(Some(left), right.left.clone(), depth + 1, work)?;
                Ok(Some(make_node(
                    right.key,
                    right.value_hash,
                    merged,
                    right.right.clone(),
                    work,
                )))
            }
        }
    }
}

fn make_node(
    key: [u8; 32],
    value_hash: Digest32,
    left: Option<Arc<LocalTreapNodeV3>>,
    right: Option<Arc<LocalTreapNodeV3>>,
    work: &mut KnowledgeLocalMutationWorkV3,
) -> Arc<LocalTreapNodeV3> {
    let priority = entry_priority(&key);
    let subtree_size = 1_u64
        .saturating_add(left.as_ref().map_or(0, |node| node.subtree_size))
        .saturating_add(right.as_ref().map_or(0, |node| node.subtree_size));
    let mut bytes = Vec::new();
    bytes.extend_from_slice(NODE_DOMAIN);
    push_digest(&mut bytes, root_hash(&left));
    bytes.extend_from_slice(&key);
    bytes.extend_from_slice(&priority);
    push_digest(&mut bytes, value_hash);
    push_digest(&mut bytes, root_hash(&right));
    push_u64(&mut bytes, subtree_size);
    let hash = Digest32::of_bytes(&bytes);
    work.treap_nodes_rehashed = work.treap_nodes_rehashed.saturating_add(1);
    Arc::new(LocalTreapNodeV3 {
        key,
        priority,
        value_hash,
        left,
        right,
        subtree_size,
        hash,
    })
}

fn entry_priority(key: &[u8; 32]) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PRIORITY_DOMAIN);
    bytes.extend_from_slice(key);
    *Digest32::of_bytes(&bytes).as_array()
}

fn heap_order(
    left_priority: &[u8; 32],
    left_key: &[u8; 32],
    right_priority: &[u8; 32],
    right_key: &[u8; 32],
) -> Ordering {
    left_priority
        .cmp(right_priority)
        .then_with(|| left_key.cmp(right_key))
}

fn ensure_depth(depth: usize) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
    if depth > MAX_DEPTH {
        Err(KnowledgeLocalIncrementalErrorV3::CommitmentDepthExceeded)
    } else {
        Ok(())
    }
}
