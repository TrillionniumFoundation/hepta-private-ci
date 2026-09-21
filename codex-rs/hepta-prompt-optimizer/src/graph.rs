//! Generation-bound knowledge.graph consumer for prompt portfolio selection.

use std::collections::BTreeSet;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::MAX_KNOWLEDGE_EDGES_V2;
use codex_hepta_kg::query_relations;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::OptimizationRequest;
use crate::PromptPortfolioReceipt;
use crate::canonical_factor_pair;
use crate::optimize_with_factor_conflicts;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphBoundPromptPortfolioReceipt {
    pub portfolio: PromptPortfolioReceipt,
    pub factor_graph_generation_digest: Digest32,
    pub relation_result_digest: Digest32,
    pub observed_relation_count: u32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl GraphBoundPromptPortfolioReceipt {
    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.graph-bound-portfolio.v1".to_vec();
        bytes.extend_from_slice(self.portfolio.receipt_digest.as_array());
        bytes.extend_from_slice(self.factor_graph_generation_digest.as_array());
        bytes.extend_from_slice(self.relation_result_digest.as_array());
        bytes.extend_from_slice(&self.observed_relation_count.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.factor_graph_generation_digest.is_zero()
            || self.relation_result_digest.is_zero()
            || self.receipt_digest != self.compute_receipt_digest()
            || self.authority.grants_any()
        {
            return Err(Error::FactorGraph(
                "invalid graph-bound portfolio receipt".to_string(),
            ));
        }
        Ok(())
    }
}

pub fn optimize_with_factor_graph(
    request: OptimizationRequest,
    factor_graph: &KnowledgeGenerationV2,
) -> Result<GraphBoundPromptPortfolioReceipt, Error> {
    factor_graph
        .validate()
        .map_err(|error| Error::FactorGraph(format!("invalid factor graph: {error}")))?;

    let factor_ids = request
        .candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<BTreeSet<_>>();
    let graph_nodes = factor_graph
        .nodes
        .iter()
        .map(|node| node.node_id.clone())
        .collect::<BTreeSet<_>>();
    if let Some(missing) = factor_ids.iter().find(|factor_id| !graph_nodes.contains(*factor_id)) {
        return Err(Error::FactorGraph(format!(
            "candidate factor missing from complete graph: {missing}"
        )));
    }

    let maximum_edges = u32::try_from(MAX_KNOWLEDGE_EDGES_V2)
        .map_err(|_| Error::FactorGraph("knowledge graph edge bound exceeds u32".to_string()))?;
    let query_id = StableId::new("query:prompt-optimizer-factor-relations-v1")
        .map_err(|error| Error::FactorGraph(format!("invalid query identity: {error}")))?;
    let relation_result = query_relations(
        factor_graph,
        KnowledgeRelationQueryV2 {
            query_id,
            generation_digest: factor_graph.generation_digest,
            seed_node_ids: factor_ids.iter().cloned().collect(),
            relation_kinds: vec![
                KnowledgeRelationKindV2::PromptComplements,
                KnowledgeRelationKindV2::PromptSubstitutes,
                KnowledgeRelationKindV2::PromptConflicts,
            ],
            valid_at_unix_seconds: None,
            maximum_edges,
        },
    )
    .map_err(|error| Error::FactorGraph(format!("factor relation query failed: {error}")))?;
    if relation_result.omitted_count != 0 {
        return Err(Error::FactorGraph(
            "factor relation query was truncated".to_string(),
        ));
    }

    let mut conflicts = BTreeSet::new();
    for edge in &relation_result.edges {
        if edge.identity.relation != KnowledgeRelationKindV2::PromptConflicts {
            continue;
        }
        if factor_ids.contains(&edge.identity.source_node_id)
            && factor_ids.contains(&edge.identity.target_node_id)
        {
            conflicts.insert(canonical_factor_pair(
                &edge.identity.source_node_id,
                &edge.identity.target_node_id,
            ));
        }
    }

    let portfolio = optimize_with_factor_conflicts(request, &conflicts)?;
    let mut result = GraphBoundPromptPortfolioReceipt {
        portfolio,
        factor_graph_generation_digest: factor_graph.generation_digest,
        relation_result_digest: relation_result.result_digest,
        observed_relation_count: u32::try_from(relation_result.edges.len()).unwrap_or(u32::MAX),
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.receipt_digest = result.compute_receipt_digest();
    result.validate()?;
    Ok(result)
}

#[cfg(test)]
#[path = "graph_tests.rs"]
mod tests;
