//! Admission bounds shared by full rebuilds, deltas and restored generations.

use super::KnowledgeEdgeV2;
use super::KnowledgeGenerationErrorV2;
use super::KnowledgeNodeV2;
use super::MAX_KNOWLEDGE_EDGES_V2;
use super::MAX_KNOWLEDGE_NODES_V2;
use super::MAX_KNOWLEDGE_SUPPORTS_V2;
use super::MAX_SUPPORTS_PER_RELATION_V2;

pub(super) fn validate_generation_limits<'a>(
    nodes: impl IntoIterator<Item = &'a KnowledgeNodeV2>,
    edges: impl IntoIterator<Item = &'a KnowledgeEdgeV2>,
) -> Result<(), KnowledgeGenerationErrorV2> {
    let mut total_supports = 0_usize;
    for (index, node) in nodes.into_iter().enumerate() {
        if index == MAX_KNOWLEDGE_NODES_V2 {
            return Err(KnowledgeGenerationErrorV2::NodeLimitExceeded);
        }
        admit_supports(&mut total_supports, node.supports.len())?;
    }
    for (index, edge) in edges.into_iter().enumerate() {
        if index == MAX_KNOWLEDGE_EDGES_V2 {
            return Err(KnowledgeGenerationErrorV2::EdgeLimitExceeded);
        }
        admit_supports(&mut total_supports, edge.supports.len())?;
    }
    Ok(())
}

fn admit_supports(
    total_supports: &mut usize,
    count: usize,
) -> Result<(), KnowledgeGenerationErrorV2> {
    if count > MAX_SUPPORTS_PER_RELATION_V2 {
        return Err(KnowledgeGenerationErrorV2::SupportLimitExceeded);
    }
    *total_supports = total_supports
        .checked_add(count)
        .ok_or(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)?;
    if *total_supports > MAX_KNOWLEDGE_SUPPORTS_V2 {
        return Err(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded);
    }
    Ok(())
}
