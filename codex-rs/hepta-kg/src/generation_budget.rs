//! Admission bounds for complete canonical encodings, including support lineage.
//!
//! Counts include revoked input records before canonicalization. These bounds
//! constrain retained lineage and the temporary digest encoding, not process RSS
//! or query latency. They cover the cognitive owner's 60,000 physical supports
//! and a maximum-sized kernel graph with one support per node and edge.

use super::*;

pub const MAX_TOTAL_KNOWLEDGE_SUPPORTS_V2: usize = 1_048_576;
pub const MAX_KNOWLEDGE_CANONICAL_BYTES_V2: usize = 256 * 1024 * 1024;

struct GenerationBudget {
    supports: usize,
    canonical_bytes: usize,
}

impl GenerationBudget {
    fn new() -> Self {
        Self {
            supports: 0,
            // Domain, generation, three digests and two collection lengths.
            canonical_bytes: GENERATION_DOMAIN.len() + 8 + 3 * 32 + 2 * 8,
        }
    }

    fn admit_supports(
        &mut self,
        supports: &[KnowledgeSupportV2],
    ) -> Result<(), KnowledgeGenerationErrorV2> {
        if supports.len() > MAX_SUPPORTS_PER_RELATION_V2 {
            return Err(KnowledgeGenerationErrorV2::SupportLimitExceeded);
        }
        self.supports = self
            .supports
            .checked_add(supports.len())
            .filter(|total| *total <= MAX_TOTAL_KNOWLEDGE_SUPPORTS_V2)
            .ok_or(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)?;
        self.admit_bytes(8)?;
        for support in supports {
            self.admit_bytes(
                8 + support.source_id.as_str().len()
                    + 8
                    + 2 * 32
                    + 2
                    + usize::from(support.valid_from_unix_seconds.is_some()) * 8
                    + usize::from(support.valid_to_unix_seconds.is_some()) * 8,
            )?;
        }
        Ok(())
    }

    fn admit_bytes(&mut self, bytes: usize) -> Result<(), KnowledgeGenerationErrorV2> {
        self.canonical_bytes = self
            .canonical_bytes
            .checked_add(bytes)
            .filter(|total| *total <= MAX_KNOWLEDGE_CANONICAL_BYTES_V2)
            .ok_or(KnowledgeGenerationErrorV2::CanonicalByteLimitExceeded)?;
        Ok(())
    }
}

pub(super) fn validate_generation_budget<'a>(
    nodes: impl ExactSizeIterator<Item = &'a KnowledgeNodeV2>,
    edges: impl ExactSizeIterator<Item = &'a KnowledgeEdgeV2>,
) -> Result<usize, KnowledgeGenerationErrorV2> {
    if nodes.len() > MAX_KNOWLEDGE_NODES_V2 {
        return Err(KnowledgeGenerationErrorV2::NodeLimitExceeded);
    }
    if edges.len() > MAX_KNOWLEDGE_EDGES_V2 {
        return Err(KnowledgeGenerationErrorV2::EdgeLimitExceeded);
    }
    let mut budget = GenerationBudget::new();
    for node in nodes {
        budget.admit_bytes(
            2 * 8 + node.node_id.as_str().len() + node.node_kind_id.as_str().len() + 32,
        )?;
        budget.admit_supports(&node.supports)?;
    }
    for edge in edges {
        let relation_bytes = match &edge.identity.relation {
            KnowledgeRelationKindV2::Custom(id) => 1 + 8 + id.as_str().len(),
            KnowledgeRelationKindV2::Supports
            | KnowledgeRelationKindV2::Contradicts
            | KnowledgeRelationKindV2::TemporalBefore
            | KnowledgeRelationKindV2::TemporalAfter
            | KnowledgeRelationKindV2::Causes
            | KnowledgeRelationKindV2::Enables
            | KnowledgeRelationKindV2::ProcedureStep
            | KnowledgeRelationKindV2::PromptComplements
            | KnowledgeRelationKindV2::PromptSubstitutes
            | KnowledgeRelationKindV2::PromptConflicts
            | KnowledgeRelationKindV2::PromptRequires
            | KnowledgeRelationKindV2::PromptDominates
            | KnowledgeRelationKindV2::PromptRedundant
            | KnowledgeRelationKindV2::PromptSupersedes => 1,
        };
        budget.admit_bytes(
            2 * 8
                + edge.identity.source_node_id.as_str().len()
                + edge.identity.target_node_id.as_str().len()
                + relation_bytes
                + 8
                + 32,
        )?;
        budget.admit_supports(&edge.supports)?;
    }
    Ok(budget.canonical_bytes)
}

#[cfg(test)]
#[path = "generation_budget_tests.rs"]
mod tests;
