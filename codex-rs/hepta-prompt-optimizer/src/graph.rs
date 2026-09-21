//! Generation-bound knowledge.graph consumer for prompt portfolio selection.

use std::collections::BTreeSet;

use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::MAX_KNOWLEDGE_EDGES_V2;
use codex_hepta_kg::PromptFactorProjectionV1;
use codex_hepta_kg::query_relations;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::OptimizationRequest;
use crate::PromptPortfolioReceipt;
use crate::canonical_factor_pair;
use crate::optimize_with_factor_graph_constraints;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphBoundPromptPortfolioReceipt {
    pub portfolio: PromptPortfolioReceipt,
    pub factor_graph_generation_digest: Digest32,
    pub relation_request_digest: Digest32,
    pub relation_result_digest: Digest32,
    pub observed_relation_count: u32,
    pub observed_complement_count: u32,
    pub observed_substitute_count: u32,
    pub observed_conflict_count: u32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl GraphBoundPromptPortfolioReceipt {
    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.graph-bound-portfolio.v1".to_vec();
        bytes.extend_from_slice(self.portfolio.receipt_digest.as_array());
        bytes.extend_from_slice(self.factor_graph_generation_digest.as_array());
        bytes.extend_from_slice(self.relation_request_digest.as_array());
        bytes.extend_from_slice(self.relation_result_digest.as_array());
        bytes.extend_from_slice(&self.observed_relation_count.to_be_bytes());
        bytes.extend_from_slice(&self.observed_complement_count.to_be_bytes());
        bytes.extend_from_slice(&self.observed_substitute_count.to_be_bytes());
        bytes.extend_from_slice(&self.observed_conflict_count.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        let typed_relation_count = u64::from(self.observed_complement_count)
            + u64::from(self.observed_substitute_count)
            + u64::from(self.observed_conflict_count);
        if self.factor_graph_generation_digest.is_zero()
            || self.relation_request_digest.is_zero()
            || self.relation_result_digest.is_zero()
            || typed_relation_count != u64::from(self.observed_relation_count)
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
    factor_graph: &PromptFactorProjectionV1,
) -> Result<GraphBoundPromptPortfolioReceipt, Error> {
    factor_graph
        .validate()
        .map_err(|error| Error::FactorGraph(format!("invalid factor graph: {error}")))?;
    if request.registry_snapshot_digest != factor_graph.registry_snapshot_digest() {
        return Err(Error::FactorGraph(
            "optimizer registry snapshot diverged from factor graph owner source".to_string(),
        ));
    }

    let factor_ids = request
        .candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<BTreeSet<_>>();
    let graph_nodes = factor_graph
        .generation()
        .nodes
        .iter()
        .map(|node| node.node_id.clone())
        .collect::<BTreeSet<_>>();
    if let Some(missing) = factor_ids
        .iter()
        .find(|factor_id| !graph_nodes.contains(*factor_id))
    {
        return Err(Error::FactorGraph(format!(
            "candidate factor missing from complete graph: {missing}"
        )));
    }

    let maximum_edges = u32::try_from(MAX_KNOWLEDGE_EDGES_V2)
        .map_err(|_| Error::FactorGraph("knowledge graph edge bound exceeds u32".to_string()))?;
    let query_id = StableId::new("query:prompt-optimizer-factor-relations-v1")
        .map_err(|error| Error::FactorGraph(format!("invalid query identity: {error}")))?;
    let relation_result = query_relations(
        factor_graph.generation(),
        KnowledgeRelationQueryV2 {
            query_id,
            generation_digest: factor_graph.generation().generation_digest,
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
    let mut substitutes = BTreeSet::new();
    let mut complement_count = 0_u32;
    let mut substitute_count = 0_u32;
    let mut conflict_count = 0_u32;
    for edge in &relation_result.edges {
        let candidate_pair = factor_ids.contains(&edge.identity.source_node_id)
            && factor_ids.contains(&edge.identity.target_node_id);
        match &edge.identity.relation {
            KnowledgeRelationKindV2::PromptComplements => {
                // The relation carries no calibrated marginal magnitude. Bind
                // the evidence, but do not manufacture additive utility.
                complement_count = complement_count.saturating_add(1);
            }
            KnowledgeRelationKindV2::PromptSubstitutes => {
                substitute_count = substitute_count.saturating_add(1);
                if candidate_pair {
                    substitutes.insert(canonical_factor_pair(
                        &edge.identity.source_node_id,
                        &edge.identity.target_node_id,
                    ));
                }
            }
            KnowledgeRelationKindV2::PromptConflicts => {
                conflict_count = conflict_count.saturating_add(1);
                if candidate_pair {
                    conflicts.insert(canonical_factor_pair(
                        &edge.identity.source_node_id,
                        &edge.identity.target_node_id,
                    ));
                }
            }
            _ => {}
        }
    }

    let portfolio = optimize_with_factor_graph_constraints(request, &conflicts, &substitutes)?;
    let mut result = GraphBoundPromptPortfolioReceipt {
        portfolio,
        factor_graph_generation_digest: factor_graph.generation().generation_digest,
        relation_request_digest: relation_result.request_digest,
        relation_result_digest: relation_result.result_digest,
        observed_relation_count: u32::try_from(relation_result.edges.len()).unwrap_or(u32::MAX),
        observed_complement_count: complement_count,
        observed_substitute_count: substitute_count,
        observed_conflict_count: conflict_count,
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
