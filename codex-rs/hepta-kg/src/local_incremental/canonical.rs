use std::collections::BTreeSet;

use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeSupportV2;
use crate::MAX_SUPPORTS_PER_RELATION_V2;

use super::model::KnowledgeLocalIncrementalErrorV3;
use super::model::ensure_nonzero;

pub(super) fn canonicalize_node(
    mut node: KnowledgeNodeV2,
) -> Result<Option<KnowledgeNodeV2>, KnowledgeLocalIncrementalErrorV3> {
    ensure_nonzero("node_payload", node.payload_digest)?;
    canonicalize_supports(&mut node.supports)?;
    node.supports.retain(|support| !support.tombstoned);
    Ok((!node.supports.is_empty()).then_some(node))
}

pub(super) fn canonicalize_edge(
    mut edge: KnowledgeEdgeV2,
) -> Result<Option<KnowledgeEdgeV2>, KnowledgeLocalIncrementalErrorV3> {
    ensure_nonzero("edge_validity", edge.validity_digest)?;
    canonicalize_supports(&mut edge.supports)?;
    edge.supports.retain(|support| !support.tombstoned);
    Ok((!edge.supports.is_empty()).then_some(edge))
}

pub(super) fn is_canonical_node(node: &KnowledgeNodeV2) -> bool {
    canonicalize_node(node.clone())
        .ok()
        .flatten()
        .as_ref()
        == Some(node)
}

pub(super) fn is_canonical_edge(edge: &KnowledgeEdgeV2) -> bool {
    canonicalize_edge(edge.clone())
        .ok()
        .flatten()
        .as_ref()
        == Some(edge)
}

fn canonicalize_supports(
    supports: &mut [KnowledgeSupportV2],
) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
    if supports.len() > MAX_SUPPORTS_PER_RELATION_V2 {
        return Err(KnowledgeGenerationErrorV2::SupportLimitExceeded.into());
    }
    supports.sort();
    let mut identities = BTreeSet::<(StableId, Revision)>::new();
    for support in supports {
        ensure_nonzero("support_fact", support.source_fact_digest)?;
        ensure_nonzero("support_validity", support.validity_digest)?;
        if support
            .valid_from_unix_seconds
            .zip(support.valid_to_unix_seconds)
            .is_some_and(|(valid_from, valid_to)| valid_to <= valid_from)
        {
            return Err(KnowledgeGenerationErrorV2::InvalidValidityWindow.into());
        }
        if !identities.insert((support.source_id.clone(), support.source_revision)) {
            return Err(KnowledgeGenerationErrorV2::DuplicateSupport.into());
        }
    }
    Ok(())
}

pub(super) fn collect_unique<T>(
    values: Vec<T>,
) -> Result<BTreeSet<T>, KnowledgeLocalIncrementalErrorV3>
where
    T: Ord,
{
    let original_len = values.len();
    let values = values.into_iter().collect::<BTreeSet<_>>();
    if values.len() != original_len {
        return Err(KnowledgeLocalIncrementalErrorV3::DuplicateDeltaIdentity);
    }
    Ok(values)
}

pub(super) fn strictly_sorted_unique<T>(values: &[T]) -> bool
where
    T: Ord,
{
    values.windows(2).all(|pair| pair[0] < pair[1])
}

pub(super) fn strictly_sorted_nodes(values: &[KnowledgeNodeV2]) -> bool {
    values
        .windows(2)
        .all(|pair| pair[0].node_id < pair[1].node_id)
}

pub(super) fn strictly_sorted_edges(values: &[KnowledgeEdgeV2]) -> bool {
    values
        .windows(2)
        .all(|pair| pair[0].identity < pair[1].identity)
}

pub(super) fn support_identity(
    support: &KnowledgeSupportV2,
) -> crate::KnowledgeSupportIdentityV2 {
    crate::KnowledgeSupportIdentityV2 {
        source_id: support.source_id.clone(),
        source_revision: support.source_revision,
    }
}

