//! Keep the registered owner projection distinct from caller supplements.
//!
//! Registered relations and their endpoints must survive unchanged. Additional
//! relations may constrain selection, but their independent source provenance
//! is a caller composition obligation, not a proof supplied by a KG checksum.

use super::*;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_prompt_registry::PromptFactorGraphSourceV1;
use codex_hepta_prompt_registry::PromptFactorRelationKind;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct EnumeratedSourceV1 {
    factor_graph: PromptFactorGraphSourceV1,
    snapshot_digest: Digest32,
}

impl EnumeratedSourceV1 {
    pub(super) fn capture(registry: &PromptRegistry, snapshot: &PromptRegistrySnapshotV2) -> Self {
        Self {
            factor_graph: registry.factor_graph_source_v1(),
            snapshot_digest: snapshot.snapshot_digest,
        }
    }
}

pub(super) fn validate_enumerated_source(
    candidates: &EnumeratedPromptCandidatesV1,
) -> Result<(), CanonicalPromptError> {
    let source = &candidates.factor_graph_source.factor_graph;
    source
        .validate()
        .map_err(|error| CanonicalPromptError::Registry(format!("{error:?}")))?;
    let snapshot = &candidates.registry_snapshot;
    snapshot
        .validate()
        .map_err(|error| CanonicalPromptError::Registry(format!("{error:?}")))?;
    candidates
        .model_tuple
        .validate()
        .map_err(|error| CanonicalPromptError::Registry(format!("{error:?}")))?;
    if candidates.factor_graph_source.snapshot_digest != snapshot.snapshot_digest
        || source.registry_snapshot_digest() != snapshot.registry_digest
        || source.registry_revision() != snapshot.revision
        || snapshot.generation_vector_digest != candidates.generation_vector_digest
        || snapshot.model_tuple_digest != candidates.model_tuple.digest()
        || candidates.receipt.registry_digest != snapshot.registry_digest
        || candidates.receipt.authority.grants_any()
    {
        return Err(CanonicalPromptError::Registry(
            "candidate snapshot diverged from sealed factor source".to_owned(),
        ));
    }
    if candidates.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS {
        return Err(CanonicalPromptError::CandidateLimit);
    }
    for (name, digest) in [
        ("objective", candidates.receipt.objective_digest),
        ("state", candidates.receipt.state_digest),
        (
            "selection_grammar",
            candidates.receipt.selection_grammar_digest,
        ),
    ] {
        ensure_digest(name, digest)?;
    }
    if candidates
        .candidates
        .windows(2)
        .any(|pair| pair[0].factor_id >= pair[1].factor_id)
    {
        return Err(CanonicalPromptError::CandidateCompletenessBinding);
    }
    for candidate in &candidates.candidates {
        candidate
            .realization
            .validate()
            .map_err(|error| CanonicalPromptError::Registry(format!("{error:?}")))?;
        if candidate.factor_id != candidate.realization.factor_id
            || candidate.binding_digest != candidate.realization.digest()
            || !matches_model(&candidate.realization, &candidates.model_tuple)
            || source
                .factors()
                .binary_search_by(|factor| factor.factor_id.cmp(&candidate.factor_id))
                .is_err()
        {
            return Err(CanonicalPromptError::CandidateCompletenessBinding);
        }
    }
    let factor_ids = candidates
        .candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    if candidates.receipt.candidate_factor_ids != factor_ids
        || candidates.candidates_digest != digest_candidates(&candidates.candidates)
        || candidates.canonical_order_digest != digest_candidate_order(&candidates.candidates)
        || candidates.receipt.receipt_digest
            != digest_candidate_receipt(
                &candidates.receipt.set_id,
                candidates.receipt.objective_digest,
                candidates.receipt.state_digest,
                snapshot.registry_digest,
                snapshot.snapshot_digest,
                candidates.model_tuple.digest(),
                candidates.receipt.selection_grammar_digest,
                &factor_ids,
                candidates.candidates_digest,
                candidates.canonical_order_digest,
                candidates.omitted_count,
            )
    {
        return Err(CanonicalPromptError::CandidateCompletenessBinding);
    }
    Ok(())
}

pub(super) fn validate_priced_source(
    priced: &PricedPromptCandidatesV1,
) -> Result<(), CanonicalPromptError> {
    validate_enumerated_source(&priced.candidates)?;
    ensure_digest("completeness", priced.completeness_digest)?;
    ensure_digest("pricing_policy", priced.pricing_policy_digest)?;
    if priced.authority.grants_any()
        || priced.rows.len() != priced.candidates.candidates.len()
        || priced.pricing_set_digest
            != digest_pricing_set(&priced.rows, priced.pricing_policy_digest)
    {
        return Err(CanonicalPromptError::CandidateCompletenessBinding);
    }
    for (row, candidate) in priced.rows.iter().zip(&priced.candidates.candidates) {
        let pricing = &row.pricing;
        let confidence = &pricing.confidence_interval;
        if row.binding != *candidate
            || pricing.factor_id != candidate.factor_id
            || pricing.state_digest != priced.candidates.receipt.state_digest
            || pricing.token_cost != candidate.realization.token_cost
            || row.net_utility_q32 != pricing.expected_utility_q32
            || pricing.authority.grants_any()
            || pricing.downside_q32 < FixedQ32::ZERO
            || confidence.lower_q32 > confidence.upper_q32
            || confidence.support_audit_digest.is_zero()
            || pricing.receipt_digest
                != digest_pricing_receipt(
                    &pricing.factor_id,
                    pricing.state_digest,
                    pricing.expected_utility_q32,
                    pricing.downside_q32,
                    pricing.token_cost,
                    pricing.latency_cost_micros,
                    pricing.interference_ppm,
                    confidence,
                    priced.pricing_policy_digest,
                    candidate.binding_digest,
                )
        {
            return Err(CanonicalPromptError::CandidateCompletenessBinding);
        }
    }
    Ok(())
}

pub(super) fn validate_graph_source(
    candidates: &EnumeratedPromptCandidatesV1,
    graph: &KnowledgeGenerationV2,
) -> Result<Digest32, CanonicalPromptError> {
    let source = &candidates.factor_graph_source.factor_graph;
    let projection = build_prompt_factor_projection_v1(
        graph.generation,
        candidates.generation_vector_digest,
        source,
    )
    .map_err(|error| CanonicalPromptError::KnowledgeGraph(format!("{error:?}")))?;
    let baseline = projection.generation();
    if (graph.source_snapshot_digest == source.source_digest()
        || graph.source_snapshot_digest == source.registry_snapshot_digest()
        || graph.graph_profile_digest == baseline.graph_profile_digest)
        && graph != baseline
    {
        return Err(CanonicalPromptError::KnowledgeGraph(
            "claimed registry projection diverged from sealed owner source".to_owned(),
        ));
    }
    for edge in &baseline.edges {
        if graph
            .edges
            .binary_search_by(|candidate| candidate.identity.cmp(&edge.identity))
            .ok()
            .is_none_or(|index| graph.edges[index] != *edge)
        {
            return Err(CanonicalPromptError::KnowledgeGraph(
                "registered owner relation missing or changed".to_owned(),
            ));
        }
        for endpoint in [&edge.identity.source_node_id, &edge.identity.target_node_id] {
            let expected = baseline
                .nodes
                .binary_search_by(|node| node.node_id.cmp(endpoint))
                .map_err(|_| {
                    CanonicalPromptError::KnowledgeGraph("invalid owner endpoint".to_owned())
                })?;
            if graph
                .nodes
                .binary_search_by(|node| node.node_id.cmp(endpoint))
                .ok()
                .is_none_or(|index| graph.nodes[index] != baseline.nodes[expected])
            {
                return Err(CanonicalPromptError::KnowledgeGraph(
                    "registered owner relation endpoint missing or changed".to_owned(),
                ));
            }
        }
    }
    Ok(source.source_digest())
}

pub(super) fn has_registered_conflict(registry: &PromptRegistry, factor_ids: &[StableId]) -> bool {
    registry
        .factor_graph_source_v1()
        .relations()
        .iter()
        .any(|relation| {
            relation.kind == PromptFactorRelationKind::Conflicts
                && factor_ids.binary_search(&relation.left_factor_id).is_ok()
                && factor_ids.binary_search(&relation.right_factor_id).is_ok()
        })
}

fn matches_model(binding: &PromptRealizationBindingV2, tuple: &PromptModelTupleV2) -> bool {
    binding.model_id == tuple.model_id
        && binding.model_version == tuple.model_version
        && binding.model_digest == tuple.model_digest
        && binding.tokenizer_digest == tuple.tokenizer_digest
        && binding.template_digest == tuple.template_digest
        && binding.tool_schema_digest == tuple.tool_schema_digest
        && binding.context_profile_digest == tuple.context_profile_digest
        && binding.locale_id == tuple.locale_id
}
