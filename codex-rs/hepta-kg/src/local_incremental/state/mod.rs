use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeSupportIdentityV2;

use super::commitment::LocalEntryIdentityV3;
use super::commitment::LocalTreapNodeV3;

mod apply;
mod build;
mod indexes;
mod prepare;

#[derive(Debug)]
pub struct KnowledgeLocalIncrementalStateV3 {
    generation: Generation,
    source_snapshot_digest: Digest32,
    generation_vector_digest: Digest32,
    graph_profile_digest: Digest32,
    nodes: BTreeMap<StableId, KnowledgeNodeV2>,
    edges: BTreeMap<KnowledgeEdgeIdentityV2, KnowledgeEdgeV2>,
    support_to_nodes: BTreeMap<KnowledgeSupportIdentityV2, BTreeSet<StableId>>,
    support_to_edges:
        BTreeMap<KnowledgeSupportIdentityV2, BTreeSet<KnowledgeEdgeIdentityV2>>,
    node_to_edges: BTreeMap<StableId, BTreeSet<KnowledgeEdgeIdentityV2>>,
    identities: BTreeMap<[u8; 32], LocalEntryIdentityV3>,
    tree_root: Option<Arc<LocalTreapNodeV3>>,
    state_root: Digest32,
}
