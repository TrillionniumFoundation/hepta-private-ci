//! Bound a portfolio by the next known change in its temporal graph projection.
//!
//! A generation digest fixes supports, not their clock-dependent visibility.
//! The current query omits future edges and invisible endpoints, so its returned
//! edges alone cannot establish how long a selection remains valid. This scan
//! borrows the validated generation, visits support lists only for structurally
//! relevant prompt edges and their endpoints, and never clones graph rows.
//! Every support transition conservatively expires the cut, including an
//! overlapping support transition that leaves the relation itself visible.

use std::collections::BTreeSet;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_types::StableId;

pub(super) fn graph_valid_until_unix_ms(
    graph: &KnowledgeGenerationV2,
    candidate_factor_ids: &BTreeSet<StableId>,
    now_unix_ms: u64,
) -> u64 {
    let mut valid_until_unix_ms = u64::MAX;
    // Borrowed endpoints are bounded by the generation's validated node cap.
    let mut endpoints = BTreeSet::new();
    for edge in &graph.edges {
        let identity = &edge.identity;
        if !matches!(
            identity.relation,
            KnowledgeRelationKindV2::PromptComplements
                | KnowledgeRelationKindV2::PromptSubstitutes
                | KnowledgeRelationKindV2::PromptConflicts
                | KnowledgeRelationKindV2::PromptRequires
                | KnowledgeRelationKindV2::PromptDominates
                | KnowledgeRelationKindV2::PromptRedundant
                | KnowledgeRelationKindV2::PromptSupersedes
        ) {
            continue;
        }
        let source_known = candidate_factor_ids.contains(&identity.source_node_id);
        let target_known = candidate_factor_ids.contains(&identity.target_node_id);
        // Selection ignores relations to unavailable factors except a directed
        // prerequisite from a known source, which must fail once it appears.
        if !source_known
            || (!target_known && identity.relation != KnowledgeRelationKindV2::PromptRequires)
        {
            continue;
        }
        endpoints.insert(&identity.source_node_id);
        endpoints.insert(&identity.target_node_id);
        valid_until_unix_ms =
            valid_until_unix_ms.min(next_support_transition(&edge.supports, now_unix_ms));
    }
    for node in &graph.nodes {
        if endpoints.contains(&node.node_id) {
            valid_until_unix_ms =
                valid_until_unix_ms.min(next_support_transition(&node.supports, now_unix_ms));
        }
    }
    valid_until_unix_ms
}

fn next_support_transition(supports: &[KnowledgeSupportV2], now_unix_ms: u64) -> u64 {
    supports
        .iter()
        .filter(|support| !support.tombstoned)
        .flat_map(|support| {
            [
                support.valid_from_unix_seconds,
                support.valid_to_unix_seconds,
            ]
            .into_iter()
            .flatten()
        })
        .filter_map(|seconds| u64::try_from(seconds).ok())
        // Seconds beyond the representable millisecond clock conservatively
        // cap at MAX; multiplying directly could wrap into a spurious deadline.
        .map(|seconds| seconds.saturating_mul(1_000))
        .filter(|boundary| *boundary > now_unix_ms)
        .min()
        .unwrap_or(u64::MAX)
}
