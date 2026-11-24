//! Expiry of a portfolio's query-time interaction view.
//!
//! The graph source can remain unchanged while clock-scoped support visibility
//! changes. Reselection is required at the next relevant support boundary.

use std::collections::BTreeSet;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_types::StableId;

pub(super) fn cap_temporal_valid_until(
    graph: &KnowledgeGenerationV2,
    factor_ids: &BTreeSet<StableId>,
    now_unix_ms: u64,
    mut valid_until_unix_ms: u64,
) -> u64 {
    let mut relevant_nodes = factor_ids.iter().collect::<BTreeSet<_>>();
    for edge in &graph.edges {
        if !(factor_ids.contains(&edge.identity.source_node_id)
            || factor_ids.contains(&edge.identity.target_node_id))
            || !matches!(
                &edge.identity.relation,
                KnowledgeRelationKindV2::PromptComplements
                    | KnowledgeRelationKindV2::PromptSubstitutes
                    | KnowledgeRelationKindV2::PromptConflicts
                    | KnowledgeRelationKindV2::PromptRequires
                    | KnowledgeRelationKindV2::PromptDominates
                    | KnowledgeRelationKindV2::PromptRedundant
                    | KnowledgeRelationKindV2::PromptSupersedes
            )
        {
            continue;
        }
        // Currently invisible edges and endpoints can become constraints later.
        relevant_nodes.insert(&edge.identity.source_node_id);
        relevant_nodes.insert(&edge.identity.target_node_id);
        valid_until_unix_ms =
            cap_at_support_boundary(&edge.supports, now_unix_ms, valid_until_unix_ms);
    }
    for node in &graph.nodes {
        if relevant_nodes.contains(&node.node_id) {
            valid_until_unix_ms =
                cap_at_support_boundary(&node.supports, now_unix_ms, valid_until_unix_ms);
        }
    }
    valid_until_unix_ms
}

fn cap_at_support_boundary(
    supports: &[KnowledgeSupportV2],
    now_unix_ms: u64,
    valid_until_unix_ms: u64,
) -> u64 {
    supports
        .iter()
        .flat_map(|support| {
            [
                support.valid_from_unix_seconds,
                support.valid_to_unix_seconds,
            ]
        })
        .flatten()
        // Negative boundaries are past. Unrepresentable future milliseconds
        // lie beyond every representable request deadline and cannot shorten it.
        .filter_map(|boundary| {
            u64::try_from(boundary)
                .ok()
                .and_then(|seconds| seconds.checked_mul(1_000))
        })
        .filter(|boundary| *boundary > now_unix_ms)
        .fold(valid_until_unix_ms, u64::min)
}
