//! Time admission for the single canonical selector.
//!
//! A graph digest freezes facts, not the passage of time. A future support can
//! become visible without changing the generation digest. Never let a selected
//! portfolio outlive the next visibility transition of its graph.

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use super::CanonicalPromptError;
use super::PricedPromptCandidatesV1;
use super::PromptPairUtilityEvidenceV1;
use super::PromptPortfolioRequestV1;
use super::SelectedPromptPortfolioV1;
use super::solver;

/// Admit time before invoking the existing constraint/utility solver. This is
/// not a second selection algorithm and cannot construct a verified portfolio.
pub fn select_portfolio_v1(
    priced: &PricedPromptCandidatesV1,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    mut request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    graph
        .validate()
        .map_err(|error| CanonicalPromptError::KnowledgeGraph(format!("{error:?}")))?;
    if let Some(transition) = next_graph_transition_unix_ms(graph, now_unix_ms)? {
        request.requested_valid_until_unix_ms =
            request.requested_valid_until_unix_ms.min(transition);
    }
    solver::select_portfolio_v1(priced, graph, pair_evidence, verifier, request, now_unix_ms)
}

/// Scan the immutable generation, not just the current relation-query result:
/// that result necessarily omits future conflicts/prerequisites. Node supports
/// matter too. The whole-generation bound is deliberately conservative; an
/// unrelated transition can force reselection but can never extend admission.
fn next_graph_transition_unix_ms(
    graph: &KnowledgeGenerationV2,
    now_unix_ms: u64,
) -> Result<Option<u64>, CanonicalPromptError> {
    let supports = graph
        .nodes
        .iter()
        .flat_map(|node| node.supports.iter())
        .chain(graph.edges.iter().flat_map(|edge| edge.supports.iter()));
    next_support_transition_unix_ms(supports, now_unix_ms)
}

fn next_support_transition_unix_ms<'a>(
    supports: impl Iterator<Item = &'a KnowledgeSupportV2>,
    now_unix_ms: u64,
) -> Result<Option<u64>, CanonicalPromptError> {
    if now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    let mut earliest: Option<u64> = None;
    for support in supports {
        // A tombstone cannot become visible merely because time advances.
        // Clearing it would change the graph generation and fail revalidation.
        if support.tombstoned {
            continue;
        }
        for seconds in [support.valid_from_unix_seconds, support.valid_to_unix_seconds]
            .into_iter()
            .flatten()
        {
            if seconds <= 0 {
                continue;
            }
            let transition = u64::try_from(seconds)
                .ok()
                .and_then(|value| value.checked_mul(1_000))
                .ok_or(CanonicalPromptError::InvalidTime)?;
            if transition > now_unix_ms {
                earliest = Some(earliest.map_or(transition, |value| value.min(transition)));
            }
        }
    }
    Ok(earliest)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_kg::KnowledgeEdgeIdentityV2;
    use codex_hepta_kg::KnowledgeEdgeV2;
    use codex_hepta_kg::KnowledgeNodeV2;
    use codex_hepta_kg::KnowledgeProjectionInputV2;
    use codex_hepta_kg::KnowledgeRelationKindV2;
    use codex_hepta_kg::KnowledgeRelationQueryV2;
    use codex_hepta_kg::build_complete_generation;
    use codex_hepta_kg::query_relations;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::ProbabilityQ32;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("fixture ID: {error}"))
    }

    fn support(from: Option<i64>, to: Option<i64>) -> KnowledgeSupportV2 {
        KnowledgeSupportV2 {
            source_id: id("support:temporal"),
            source_revision: Revision::new(1)
                .unwrap_or_else(|error| panic!("fixture revision: {error}")),
            source_fact_digest: Digest32::of_bytes(b"temporal-fact"),
            validity_digest: Digest32::of_bytes(b"temporal-validity"),
            valid_from_unix_seconds: from,
            valid_to_unix_seconds: to,
            tombstoned: false,
        }
    }

    fn graph(relation: KnowledgeRelationKindV2) -> KnowledgeGenerationV2 {
        build_complete_generation(
            Generation::new(1).unwrap_or_else(|error| panic!("fixture generation: {error}")),
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: Digest32::of_bytes(b"temporal-source"),
                generation_vector_digest: Digest32::of_bytes(b"temporal-vector"),
                graph_profile_digest: Digest32::of_bytes(b"temporal-profile"),
                complete_source_cut: true,
                nodes: ["factor:a", "factor:b"]
                    .into_iter()
                    .map(|name| KnowledgeNodeV2 {
                        node_id: id(name),
                        node_kind_id: id("kind:prompt-factor"),
                        payload_digest: Digest32::of_bytes(name.as_bytes()),
                        supports: vec![support(None, None)],
                    })
                    .collect(),
                edges: vec![KnowledgeEdgeV2 {
                    identity: KnowledgeEdgeIdentityV2 {
                        source_node_id: id("factor:a"),
                        relation,
                        target_node_id: id("factor:b"),
                    },
                    confidence: ProbabilityQ32::ONE,
                    validity_digest: Digest32::of_bytes(b"temporal-edge"),
                    supports: vec![support(Some(2), Some(5))],
                }],
            },
        )
        .unwrap_or_else(|error| panic!("fixture graph: {error}"))
    }

    #[test]
    fn future_conflict_caps_validity_without_generation_drift() {
        let graph = graph(KnowledgeRelationKindV2::PromptConflicts);
        let original_digest = graph.generation_digest;
        for (seconds, expected_edges) in [(1, 0), (2, 1), (5, 0)] {
            let result = query_relations(
                &graph,
                KnowledgeRelationQueryV2 {
                    query_id: id("query:temporal"),
                    generation_digest: graph.generation_digest,
                    seed_node_ids: vec![id("factor:a"), id("factor:b")],
                    valid_at_unix_seconds: Some(seconds),
                    relation_kinds: vec![KnowledgeRelationKindV2::PromptConflicts],
                    maximum_edges: 512,
                },
            )
            .unwrap_or_else(|error| panic!("fixture query: {error}"));
            assert_eq!(result.edges.len(), expected_edges);
            assert_eq!(graph.generation_digest, original_digest);
        }
        assert_eq!(next_graph_transition_unix_ms(&graph, 1_999), Ok(Some(2_000)));
        assert_eq!(next_graph_transition_unix_ms(&graph, 2_000), Ok(Some(5_000)));
        assert_eq!(next_graph_transition_unix_ms(&graph, 5_000), Ok(None));
    }

    #[test]
    fn future_prerequisite_has_the_same_exclusive_time_fence() {
        let graph = graph(KnowledgeRelationKindV2::PromptRequires);
        assert_eq!(next_graph_transition_unix_ms(&graph, 100), Ok(Some(2_000)));
    }

    #[test]
    fn node_visibility_and_multiple_supports_use_earliest_transition() {
        let supports = [support(None, Some(4)), support(Some(2), Some(8))];
        assert_eq!(next_support_transition_unix_ms(supports.iter(), 100), Ok(Some(2_000)));
        assert_eq!(next_support_transition_unix_ms(supports.iter(), 2_000), Ok(Some(4_000)));
        let mut graph = graph(KnowledgeRelationKindV2::PromptConflicts);
        graph.nodes[0].supports[0].valid_to_unix_seconds = Some(1);
        // The helper is a time calculator. Public selection separately validates
        // the immutable graph digest before it calls this helper.
        assert_eq!(next_graph_transition_unix_ms(&graph, 100), Ok(Some(1_000)));
    }

    #[test]
    fn tombstones_and_past_boundaries_do_not_create_future_visibility() {
        let mut tombstone = support(Some(1), Some(2));
        tombstone.tombstoned = true;
        let supports = [tombstone, support(Some(-2), Some(-1)), support(None, None)];
        assert_eq!(next_support_transition_unix_ms(supports.iter(), 100), Ok(None));
    }

    #[test]
    fn invalid_clock_and_unrepresentable_transition_fail_closed() {
        let supports = [support(None, Some(i64::MAX))];
        assert_eq!(
            next_support_transition_unix_ms(supports.iter(), 100),
            Err(CanonicalPromptError::InvalidTime)
        );
        assert_eq!(
            next_support_transition_unix_ms(std::iter::empty(), 0),
            Err(CanonicalPromptError::InvalidTime)
        );
    }
}
