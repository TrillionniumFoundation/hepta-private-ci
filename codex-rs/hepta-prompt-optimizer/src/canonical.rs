//! Canonical prompt selection and optimization pipeline.
//!
//! This module is deliberately authority-free. It authenticates and binds
//! registry, causal-evidence and knowledge-projection inputs, emits deterministic
//! proposal receipts, and revalidates the exact prompt realization immediately
//! before an intervention boundary. It never invokes a model/provider or mutates
//! prompt, knowledge or learning stores.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_kg::{
    query_relations, KnowledgeGenerationV2, KnowledgeRelationKindV2, KnowledgeRelationQueryV2,
};
use codex_hepta_learning_ledger::{
    validate_candidate_set_completeness, CandidateSetCompletenessReceiptV1,
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedLearningEvidenceV1,
};
use codex_hepta_prompt_registry::{
    PromptModelTupleV2, PromptRealizationBindingV2, PromptRegistry, PromptRegistrySnapshotV2,
};
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

pub const MAX_CANONICAL_PROMPT_FACTORS: usize = 128;
pub const MAX_CANONICAL_SELECTED_FACTORS: usize = 16;
pub const MAX_CANONICAL_INTERACTION_EDGES: u32 = 512;
pub const MAX_CANONICAL_TOKEN_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateBindingV1 {
    pub factor_id: StableId,
    pub realization: PromptRealizationBindingV2,
    pub binding_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumeratedPromptCandidatesV1 {
    pub registry_snapshot: PromptRegistrySnapshotV2,
    pub model_tuple: PromptModelTupleV2,
    pub generation_vector_digest: Digest32,
    pub candidates_digest: Digest32,
    pub canonical_order_digest: Digest32,
    pub omitted_count: u32,
    pub candidates: Vec<PromptCandidateBindingV1>,
    pub receipt: PromptCandidateSetReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationRequestV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub required_factor_ids: Vec<StableId>,
    pub maximum_candidates: u32,
    pub selection_grammar_digest: Digest32,
}

pub fn enumerate_factors_v1(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<EnumeratedPromptCandidatesV1, CanonicalPromptError> {
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("state", request.state_digest),
        ("generation_vector", request.generation_vector_digest),
        ("selection_grammar", request.selection_grammar_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    let maximum_candidates =
        usize::try_from(request.maximum_candidates).map_err(|_| CanonicalPromptError::CandidateLimit)?;
    if maximum_candidates == 0 || maximum_candidates > MAX_CANONICAL_PROMPT_FACTORS {
        return Err(CanonicalPromptError::CandidateLimit);
    }

    let snapshot = registry
        .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
        .map_err(|e| CanonicalPromptError::Registry(format!("{e:?}")))?;
    let compatible = registry
        .read_compatible_v2(
            &snapshot,
            request.generation_vector_digest,
            &request.model_tuple,
            request.now_unix_ms,
            request.required_factor_ids,
            MAX_CANONICAL_PROMPT_FACTORS as u32,
        )
        .map_err(|e| CanonicalPromptError::Registry(format!("{e:?}")))?;
    if compatible.omitted_count != 0 {
        return Err(CanonicalPromptError::RegistryReadIncomplete(
            compatible.omitted_count,
        ));
    }

    let mut per_factor = BTreeMap::<StableId, PromptRealizationBindingV2>::new();
    for binding in compatible.bindings {
        match per_factor.get(&binding.factor_id) {
            None => {
                per_factor.insert(binding.factor_id.clone(), binding);
            }
            Some(current)
                if binding.token_cost < current.token_cost
                    || (binding.token_cost == current.token_cost
                        && binding.realization_id < current.realization_id) =>
            {
                per_factor.insert(binding.factor_id.clone(), binding);
            }
            Some(_) => {}
        }
    }

    let total = per_factor.len();
    let omitted = total.saturating_sub(maximum_candidates);
    let mut candidates = per_factor
        .into_values()
        .take(maximum_candidates)
        .map(|realization| PromptCandidateBindingV1 {
            factor_id: realization.factor_id.clone(),
            binding_digest: realization.digest(),
            realization,
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));

    let candidates_digest = digest_candidates(&candidates);
    let canonical_order_digest = digest_candidate_order(&candidates);
    let factor_ids = candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let receipt_digest = digest_candidate_receipt(
        &request.set_id,
        request.objective_digest,
        request.state_digest,
        snapshot.registry_digest,
        snapshot.snapshot_digest,
        request.model_tuple.digest(),
        request.selection_grammar_digest,
        &factor_ids,
        candidates_digest,
        canonical_order_digest,
        u32::try_from(omitted).unwrap_or(u32::MAX),
    );
    let receipt = PromptCandidateSetReceiptV1 {
        set_id: request.set_id,
        objective_digest: request.objective_digest,
        state_digest: request.state_digest,
        registry_digest: snapshot.registry_digest,
        candidate_factor_ids: factor_ids,
        selection_grammar_digest: request.selection_grammar_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(EnumeratedPromptCandidatesV1 {
        registry_snapshot: snapshot,
        model_tuple: request.model_tuple,
        generation_vector_digest: request.generation_vector_digest,
        candidates_digest,
        canonical_order_digest,
        omitted_count: u32::try_from(omitted).unwrap_or(u32::MAX),
        candidates,
        receipt,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub support_count: u32,
    pub support_audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub expected_incremental_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub support_count: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub context_crowding_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_cost_q32: FixedQ32,
    pub support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingPolicyV1 {
    pub policy_id: StableId,
    pub token_cost_per_token_q32: FixedQ32,
    pub latency_cost_per_micro_q32: FixedQ32,
    pub interference_cost_per_ppm_q32: FixedQ32,
    pub downside_weight_q32: FixedQ32,
    pub minimum_support_count: u32,
    pub maximum_interference_ppm: u32,
}

impl PromptPricingPolicyV1 {
    pub fn digest(&self) -> Result<Digest32, CanonicalPromptError> {
        if self.minimum_support_count == 0 || self.maximum_interference_ppm > 1_000_000 {
            return Err(CanonicalPromptError::InvalidPricingPolicy);
        }
        for value in [
            self.token_cost_per_token_q32,
            self.latency_cost_per_micro_q32,
            self.interference_cost_per_ppm_q32,
            self.downside_weight_q32,
        ] {
            if value < FixedQ32::ZERO {
                return Err(CanonicalPromptError::InvalidPricingPolicy);
            }
        }
        let mut bytes = b"hepta.prompt-optimizer.pricing-policy.v1".to_vec();
        push_id(&mut bytes, &self.policy_id);
        for value in [
            self.token_cost_per_token_q32,
            self.latency_cost_per_micro_q32,
            self.interference_cost_per_ppm_q32,
            self.downside_weight_q32,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        bytes.extend_from_slice(&self.minimum_support_count.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_interference_ppm.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PricedPromptCandidateV1 {
    pub binding: PromptCandidateBindingV1,
    pub pricing: PromptPricingReceiptV1,
    pub net_utility_q32: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PricedPromptCandidatesV1 {
    pub candidates: EnumeratedPromptCandidatesV1,
    pub completeness_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub rows: Vec<PricedPromptCandidateV1>,
    pub pricing_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn candidate_completeness_signing_payload_v1(
    receipt: &CandidateSetCompletenessReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    let digest = validate_candidate_set_completeness(receipt)
        .map_err(|e| CanonicalPromptError::CandidateCompleteness(format!("{e:?}")))?;
    let mut bytes = b"hepta.prompt-optimizer.candidate-completeness-auth.v1".to_vec();
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

pub fn pricing_evidence_signing_payload_v1(evidence: &PromptPricingEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v1".to_vec();
    push_id(&mut bytes, &evidence.factor_id);
    for digest in [
        evidence.state_digest,
        evidence.model_tuple_digest,
        evidence.support_audit_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        evidence.expected_incremental_utility_q32,
        evidence.downside_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
        evidence.context_crowding_cost_q32,
        evidence.privacy_cost_q32,
        evidence.instability_cost_q32,
        evidence.future_context_option_cost_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&evidence.support_count.to_be_bytes());
    bytes.extend_from_slice(&evidence.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&evidence.interference_ppm.to_be_bytes());
    bytes
}

pub fn price_factors_v1(
    candidates: EnumeratedPromptCandidatesV1,
    completeness: &CandidateSetCompletenessReceiptV1,
    completeness_evidence: &SignedLearningEvidenceV1,
    pricing_evidence: Vec<PromptPricingEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    policy: &PromptPricingPolicyV1,
    now_unix_ms: u64,
) -> Result<PricedPromptCandidatesV1, CanonicalPromptError> {
    if now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    validate_candidate_binding(&candidates, completeness)?;
    let completeness_payload = candidate_completeness_signing_payload_v1(completeness)?;
    verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            completeness_evidence,
            &completeness_payload,
            now_unix_ms,
        )
        .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;

    let pricing_policy_digest = policy.digest()?;
    let by_factor = candidates
        .candidates
        .iter()
        .map(|candidate| (candidate.factor_id.clone(), candidate))
        .collect::<BTreeMap<_, _>>();
    let mut evidence_rows = BTreeMap::<StableId, PromptPricingEvidenceV1>::new();
    for evidence in pricing_evidence {
        if !by_factor.contains_key(&evidence.factor_id) {
            return Err(CanonicalPromptError::UnknownFactor(
                evidence.factor_id.to_string(),
            ));
        }
        if evidence_rows
            .insert(evidence.factor_id.clone(), evidence)
            .is_some()
        {
            return Err(CanonicalPromptError::DuplicatePricingEvidence);
        }
    }

    let mut rows = Vec::with_capacity(candidates.candidates.len());
    for candidate in &candidates.candidates {
        let evidence = evidence_rows
            .remove(&candidate.factor_id)
            .ok_or_else(|| CanonicalPromptError::MissingPricingEvidence(candidate.factor_id.to_string()))?;
        validate_pricing_evidence(&candidates, &evidence, policy)?;
        let payload = pricing_evidence_signing_payload_v1(&evidence);
        verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;

        let token_cost = candidate.realization.token_cost;
        let mut net = evidence.expected_incremental_utility_q32;
        let downside_penalty = policy
            .downside_weight_q32
            .checked_mul(evidence.downside_q32)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        for cost in [
            downside_penalty,
            scale_rate(policy.token_cost_per_token_q32, u64::from(token_cost))?,
            scale_rate(
                policy.latency_cost_per_micro_q32,
                evidence.latency_cost_micros,
            )?,
            scale_rate(
                policy.interference_cost_per_ppm_q32,
                u64::from(evidence.interference_ppm),
            )?,
            evidence.context_crowding_cost_q32,
            evidence.privacy_cost_q32,
            evidence.instability_cost_q32,
            evidence.future_context_option_cost_q32,
        ] {
            net = net
                .checked_sub(cost)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
        }
        let confidence_interval = PromptConfidenceIntervalV1 {
            lower_q32: evidence.confidence_lower_q32,
            upper_q32: evidence.confidence_upper_q32,
            support_count: evidence.support_count,
            support_audit_digest: evidence.support_audit_digest,
        };
        let receipt_digest = digest_pricing_receipt(
            &candidate.factor_id,
            candidates.receipt.state_digest,
            net,
            evidence.downside_q32,
            token_cost,
            evidence.latency_cost_micros,
            evidence.interference_ppm,
            &confidence_interval,
            pricing_policy_digest,
            candidate.binding_digest,
        );
        rows.push(PricedPromptCandidateV1 {
            binding: candidate.clone(),
            pricing: PromptPricingReceiptV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                expected_utility_q32: net,
                downside_q32: evidence.downside_q32,
                token_cost,
                latency_cost_micros: evidence.latency_cost_micros,
                interference_ppm: evidence.interference_ppm,
                confidence_interval,
                receipt_digest,
                authority: AuthorityPosture::DENY_ALL,
            },
            net_utility_q32: net,
        });
    }
    if !evidence_rows.is_empty() {
        return Err(CanonicalPromptError::UnknownFactor(
            evidence_rows.keys().next().expect("nonempty").to_string(),
        ));
    }
    let pricing_set_digest = digest_pricing_set(&rows, pricing_policy_digest);
    let completeness_digest = validate_candidate_set_completeness(completeness)
        .map_err(|e| CanonicalPromptError::CandidateCompleteness(format!("{e:?}")))?;
    Ok(PricedPromptCandidatesV1 {
        candidates,
        completeness_digest,
        pricing_policy_digest,
        rows,
        pricing_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairUtilityEvidenceV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub state_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub edge_validity_digest: Digest32,
    pub marginal_utility_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

pub fn pair_utility_evidence_signing_payload_v1(
    evidence: &PromptPairUtilityEvidenceV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pair-utility-evidence.v1".to_vec();
    push_id(&mut bytes, &evidence.left_factor_id);
    push_id(&mut bytes, &evidence.right_factor_id);
    for digest in [
        evidence.state_digest,
        evidence.graph_generation_digest,
        evidence.edge_validity_digest,
        evidence.support_audit_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        evidence.marginal_utility_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSelectionMethodV1 {
    GreedyPrerequisiteBundleV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityDisclosureV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedPromptPortfolioV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub selected: Vec<PromptCandidateBindingV1>,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub pricing_set_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub selection_method: PromptSelectionMethodV1,
    pub optimality: PromptOptimalityDisclosureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioRequestV1 {
    pub portfolio_id: StableId,
    pub graph_query_id: StableId,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub requested_valid_until_unix_ms: u64,
}

pub fn select_portfolio_v1(
    priced: &PricedPromptCandidatesV1,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    if request.maximum_selected_factors == 0
        || request.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS
    {
        return Err(CanonicalPromptError::SelectionLimit);
    }
    if request.token_budget > MAX_CANONICAL_TOKEN_BUDGET {
        return Err(CanonicalPromptError::TokenBudgetLimit);
    }
    if now_unix_ms == 0 || request.requested_valid_until_unix_ms <= now_unix_ms {
        return Err(CanonicalPromptError::InvalidTime);
    }
    graph
        .validate()
        .map_err(|e| CanonicalPromptError::KnowledgeGraph(format!("{e:?}")))?;
    if graph.generation_vector_digest != priced.candidates.generation_vector_digest {
        return Err(CanonicalPromptError::GenerationVectorMismatch);
    }

    let factor_ids = priced
        .rows
        .iter()
        .map(|row| row.binding.factor_id.clone())
        .collect::<Vec<_>>();
    let relation_result = query_relations(
        graph,
        KnowledgeRelationQueryV2 {
            query_id: request.graph_query_id,
            generation_digest: graph.generation_digest,
            seed_node_ids: factor_ids.clone(),
            relation_kinds: vec![
                KnowledgeRelationKindV2::PromptComplements,
                KnowledgeRelationKindV2::PromptSubstitutes,
                KnowledgeRelationKindV2::PromptConflicts,
                KnowledgeRelationKindV2::PromptRequires,
                KnowledgeRelationKindV2::PromptDominates,
                KnowledgeRelationKindV2::PromptRedundant,
                KnowledgeRelationKindV2::PromptSupersedes,
            ],
            maximum_edges: MAX_CANONICAL_INTERACTION_EDGES,
        },
    )
    .map_err(|e| CanonicalPromptError::KnowledgeGraph(format!("{e:?}")))?;
    if relation_result.omitted_count != 0 {
        return Err(CanonicalPromptError::InteractionProjectionIncomplete(
            relation_result.omitted_count,
        ));
    }

    let known = factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let mut requires = BTreeMap::<StableId, BTreeSet<StableId>>::new();
    let mut conflicts = BTreeSet::<(StableId, StableId)>::new();
    let mut numeric_edges = BTreeMap::<(StableId, StableId), (Digest32, KnowledgeRelationKindV2)>::new();
    for edge in &relation_result.edges {
        let left = &edge.identity.source_node_id;
        let right = &edge.identity.target_node_id;
        if !known.contains(left) || !known.contains(right) {
            if edge.identity.relation == KnowledgeRelationKindV2::PromptRequires
                && known.contains(left)
            {
                return Err(CanonicalPromptError::RequiredFactorUnavailable(
                    right.to_string(),
                ));
            }
            continue;
        }
        match edge.identity.relation {
            KnowledgeRelationKindV2::PromptRequires => {
                requires.entry(left.clone()).or_default().insert(right.clone());
            }
            KnowledgeRelationKindV2::PromptConflicts
            | KnowledgeRelationKindV2::PromptDominates
            | KnowledgeRelationKindV2::PromptRedundant
            | KnowledgeRelationKindV2::PromptSupersedes => {
                conflicts.insert(pair_key(left, right));
            }
            KnowledgeRelationKindV2::PromptComplements
            | KnowledgeRelationKindV2::PromptSubstitutes => {
                let key = pair_key(left, right);
                if numeric_edges
                    .insert(key.clone(), (edge.validity_digest, edge.identity.relation))
                    .is_some()
                {
                    return Err(CanonicalPromptError::DuplicateInteraction);
                }
            }
            _ => {}
        }
    }
    validate_requires_acyclic(&known, &requires)?;

    let mut pair_rows = BTreeMap::<(StableId, StableId), FixedQ32>::new();
    let mut pair_evidence_digests = Vec::new();
    for evidence in pair_evidence {
        let key = pair_key(&evidence.left_factor_id, &evidence.right_factor_id);
        let Some((validity_digest, _)) = numeric_edges.get(&key) else {
            return Err(CanonicalPromptError::UnexpectedPairEvidence);
        };
        if evidence.left_factor_id >= evidence.right_factor_id
            || evidence.state_digest != priced.candidates.receipt.state_digest
            || evidence.graph_generation_digest != graph.generation_digest
            || evidence.edge_validity_digest != *validity_digest
            || evidence.support_audit_digest.is_zero()
            || evidence.confidence_lower_q32 > evidence.marginal_utility_q32
            || evidence.marginal_utility_q32 > evidence.confidence_upper_q32
        {
            return Err(CanonicalPromptError::InvalidPairEvidence);
        }
        let payload = pair_utility_evidence_signing_payload_v1(&evidence);
        let verified = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;
        pair_evidence_digests.push(verified.payload_digest());
        if pair_rows
            .insert(key, evidence.marginal_utility_q32)
            .is_some()
        {
            return Err(CanonicalPromptError::DuplicatePairEvidence);
        }
    }
    for key in numeric_edges.keys() {
        if !pair_rows.contains_key(key) {
            return Err(CanonicalPromptError::MissingPairEvidence(
                key.0.to_string(),
                key.1.to_string(),
            ));
        }
    }

    let by_factor = priced
        .rows
        .iter()
        .map(|row| (row.binding.factor_id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let mut selected = BTreeSet::<StableId>::new();
    loop {
        if selected.len() >= request.maximum_selected_factors {
            break;
        }
        let base_utility = portfolio_utility(&selected, &by_factor, &pair_rows)?;
        let mut best: Option<(StableId, BTreeSet<StableId>, FixedQ32, u64)> = None;
        for factor_id in by_factor.keys() {
            if selected.contains(factor_id) {
                continue;
            }
            let closure = prerequisite_closure(factor_id, &requires)?;
            let added = closure
                .difference(&selected)
                .cloned()
                .collect::<BTreeSet<_>>();
            if added.is_empty()
                || selected.len().saturating_add(added.len()) > request.maximum_selected_factors
            {
                continue;
            }
            let mut proposed = selected.clone();
            proposed.extend(added.iter().cloned());
            if violates_conflict(&proposed, &conflicts) {
                continue;
            }
            let token_cost = portfolio_token_cost(&proposed, &by_factor)?;
            if token_cost > request.token_budget {
                continue;
            }
            let next_utility = portfolio_utility(&proposed, &by_factor, &pair_rows)?;
            let marginal = next_utility
                .checked_sub(base_utility)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let added_tokens = portfolio_token_cost(&added, &by_factor)?;
            let better = best.as_ref().is_none_or(|(best_id, _, best_gain, best_tokens)| {
                marginal > *best_gain
                    || (marginal == *best_gain
                        && (added_tokens < *best_tokens
                            || (added_tokens == *best_tokens && factor_id < best_id)))
            });
            if better {
                best = Some((factor_id.clone(), proposed, marginal, added_tokens));
            }
        }
        let Some((_, proposed, _, _)) = best else {
            break;
        };
        selected = proposed;
    }

    let expected_utility = portfolio_utility(&selected, &by_factor, &pair_rows)?;
    let total_tokens = portfolio_token_cost(&selected, &by_factor)?;
    let total_token_upper_bound =
        u32::try_from(total_tokens).map_err(|_| CanonicalPromptError::TokenBudgetLimit)?;
    let mut selected_bindings = selected
        .iter()
        .filter_map(|id| by_factor.get(id).map(|row| row.binding.clone()))
        .collect::<Vec<_>>();
    selected_bindings.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let selected_ids = selected_bindings
        .iter()
        .map(|row| row.factor_id.clone())
        .collect::<Vec<_>>();
    let mut valid_until = request.requested_valid_until_unix_ms;
    for binding in &selected_bindings {
        if let Some(expires) = binding.realization.expires_unix_ms {
            valid_until = valid_until.min(expires);
        }
    }
    if valid_until <= now_unix_ms {
        return Err(CanonicalPromptError::PortfolioExpired);
    }
    pair_evidence_digests.sort();
    let interaction_digest = digest_interactions(
        relation_result.result_digest,
        &pair_evidence_digests,
        &requires,
        &conflicts,
    );
    let receipt_digest = digest_portfolio_receipt(
        &request.portfolio_id,
        priced.candidates.candidates_digest,
        &selected_ids,
        interaction_digest,
        expected_utility,
        total_token_upper_bound,
        valid_until,
        priced.pricing_set_digest,
        graph.generation_digest,
    );
    Ok(SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: request.portfolio_id,
            candidate_set_digest: priced.candidates.candidates_digest,
            factor_ids: selected_ids,
            interaction_digest,
            expected_utility_q32: expected_utility,
            total_token_upper_bound,
            valid_until_unix_ms: valid_until,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: selected_bindings,
        state_digest: priced.candidates.receipt.state_digest,
        model_tuple_digest: priced.candidates.model_tuple.digest(),
        generation_vector_digest: priced.candidates.generation_vector_digest,
        pricing_set_digest: priced.pricing_set_digest,
        graph_generation_digest: graph.generation_digest,
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDecisionBoundaryV1 {
    RequestAccepted,
    ObjectiveCompiled,
    BeforePlanning,
    BeforeCandidateGeneration,
    BeforeModelOrToolDispatch,
    AfterObservation,
    AfterFailureOrUncertaintySpike,
    BeforeIrreversibleMutation,
    BeforeVerification,
    BeforeFinalResponse,
    BeforeCompactOrHandoff,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseActionV1 {
    Exercise,
    Wait,
    RejectStale,
    NoIntervention,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: PromptExerciseActionV1,
    pub policy_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseRequestV1 {
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub current_state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub policy_digest: Digest32,
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptExerciseRequestV1,
) -> Result<PromptExerciseDecisionV1, CanonicalPromptError> {
    for (name, digest) in [
        ("current_state", request.current_state_digest),
        ("generation_vector", request.generation_vector_digest),
        ("exercise_policy", request.policy_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }

    let mut decision = if portfolio.selected.is_empty() {
        PromptExerciseActionV1::NoIntervention
    } else if request.now_unix_ms >= portfolio.receipt.valid_until_unix_ms
        || request.current_state_digest != portfolio.state_digest
        || request.generation_vector_digest != portfolio.generation_vector_digest
        || request.model_tuple.digest() != portfolio.model_tuple_digest
    {
        PromptExerciseActionV1::RejectStale
    } else {
        let current_snapshot = registry
            .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
            .map_err(|e| CanonicalPromptError::Registry(format!("{e:?}")))?;
        let selected_factor_ids = portfolio
            .selected
            .iter()
            .map(|binding| binding.factor_id.clone())
            .collect::<Vec<_>>();
        let current = registry.read_compatible_v2(
            &current_snapshot,
            request.generation_vector_digest,
            &request.model_tuple,
            request.now_unix_ms,
            selected_factor_ids,
            MAX_CANONICAL_PROMPT_FACTORS as u32,
        );
        match current {
            Err(_) => PromptExerciseActionV1::RejectStale,
            Ok(set) => {
                let current_by_factor = set
                    .bindings
                    .into_iter()
                    .map(|binding| (binding.factor_id.clone(), binding))
                    .collect::<BTreeMap<_, _>>();
                let exact = portfolio.selected.iter().all(|selected| {
                    current_by_factor
                        .get(&selected.factor_id)
                        .is_some_and(|current| {
                            current.realization_id == selected.realization.realization_id
                                && current.digest() == selected.binding_digest
                        })
                });
                if !exact {
                    PromptExerciseActionV1::RejectStale
                } else if portfolio.receipt.expected_utility_q32 > request.wait_value_q32 {
                    PromptExerciseActionV1::Exercise
                } else {
                    PromptExerciseActionV1::Wait
                }
            }
        }
    };
    if portfolio.selected.is_empty() {
        decision = PromptExerciseActionV1::NoIntervention;
    }
    let receipt_digest = digest_exercise_receipt(
        &portfolio.receipt.portfolio_id,
        request.decision_boundary,
        portfolio.receipt.expected_utility_q32,
        request.wait_value_q32,
        decision,
        request.policy_digest,
        portfolio.receipt.receipt_digest,
    );
    Ok(PromptExerciseDecisionV1 {
        factor_or_portfolio_id: portfolio.receipt.portfolio_id.clone(),
        decision_boundary: request.decision_boundary,
        exercise_now_value_q32: portfolio.receipt.expected_utility_q32,
        wait_value_q32: request.wait_value_q32,
        decision,
        policy_digest: request.policy_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_candidate_binding(
    candidates: &EnumeratedPromptCandidatesV1,
    completeness: &CandidateSetCompletenessReceiptV1,
) -> Result<(), CanonicalPromptError> {
    let factor_count =
        u32::try_from(candidates.candidates.len()).map_err(|_| CanonicalPromptError::CandidateLimit)?;
    if completeness.set_id != candidates.receipt.set_id
        || completeness.state_digest != candidates.receipt.state_digest
        || completeness.generator_id.as_str() != "prompt.optimizer"
        || completeness.grammar_digest != candidates.receipt.selection_grammar_digest
        || completeness.candidates_digest != candidates.candidates_digest
        || completeness.canonical_order_digest != candidates.canonical_order_digest
        || completeness.candidate_count != factor_count
        || completeness.omitted_count_bound < candidates.omitted_count
    {
        return Err(CanonicalPromptError::CandidateCompletenessBinding);
    }
    Ok(())
}

fn validate_pricing_evidence(
    candidates: &EnumeratedPromptCandidatesV1,
    evidence: &PromptPricingEvidenceV1,
    policy: &PromptPricingPolicyV1,
) -> Result<(), CanonicalPromptError> {
    if evidence.state_digest != candidates.receipt.state_digest
        || evidence.model_tuple_digest != candidates.model_tuple.digest()
        || evidence.support_audit_digest.is_zero()
        || evidence.support_count < policy.minimum_support_count
        || evidence.interference_ppm > policy.maximum_interference_ppm
        || evidence.downside_q32 < FixedQ32::ZERO
        || evidence.context_crowding_cost_q32 < FixedQ32::ZERO
        || evidence.privacy_cost_q32 < FixedQ32::ZERO
        || evidence.instability_cost_q32 < FixedQ32::ZERO
        || evidence.future_context_option_cost_q32 < FixedQ32::ZERO
        || evidence.confidence_lower_q32 > evidence.expected_incremental_utility_q32
        || evidence.expected_incremental_utility_q32 > evidence.confidence_upper_q32
    {
        return Err(CanonicalPromptError::InvalidPricingEvidence(
            evidence.factor_id.to_string(),
        ));
    }
    Ok(())
}

fn prerequisite_closure(
    root: &StableId,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
) -> Result<BTreeSet<StableId>, CanonicalPromptError> {
    fn visit(
        node: &StableId,
        requires: &BTreeMap<StableId, BTreeSet<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        done: &mut BTreeSet<StableId>,
    ) -> Result<(), CanonicalPromptError> {
        if done.contains(node) {
            return Ok(());
        }
        if !visiting.insert(node.clone()) {
            return Err(CanonicalPromptError::PrerequisiteCycle(node.to_string()));
        }
        if let Some(prerequisites) = requires.get(node) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, visiting, done)?;
            }
        }
        visiting.remove(node);
        done.insert(node.clone());
        Ok(())
    }
    let mut visiting = BTreeSet::new();
    let mut done = BTreeSet::new();
    visit(root, requires, &mut visiting, &mut done)?;
    Ok(done)
}

fn validate_requires_acyclic(
    known: &BTreeSet<StableId>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
) -> Result<(), CanonicalPromptError> {
    for (factor, prerequisites) in requires {
        if !known.contains(factor) {
            continue;
        }
        for prerequisite in prerequisites {
            if !known.contains(prerequisite) {
                return Err(CanonicalPromptError::RequiredFactorUnavailable(
                    prerequisite.to_string(),
                ));
            }
        }
        prerequisite_closure(factor, requires)?;
    }
    Ok(())
}

fn violates_conflict(
    selected: &BTreeSet<StableId>,
    conflicts: &BTreeSet<(StableId, StableId)>,
) -> bool {
    conflicts
        .iter()
        .any(|(left, right)| selected.contains(left) && selected.contains(right))
}

fn portfolio_token_cost(
    selected: &BTreeSet<StableId>,
    rows: &BTreeMap<StableId, &PricedPromptCandidateV1>,
) -> Result<u64, CanonicalPromptError> {
    selected.iter().try_fold(0_u64, |sum, id| {
        let row = rows
            .get(id)
            .ok_or_else(|| CanonicalPromptError::UnknownFactor(id.to_string()))?;
        sum.checked_add(u64::from(row.pricing.token_cost))
            .ok_or(CanonicalPromptError::Arithmetic)
    })
}

fn portfolio_utility(
    selected: &BTreeSet<StableId>,
    rows: &BTreeMap<StableId, &PricedPromptCandidateV1>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
) -> Result<FixedQ32, CanonicalPromptError> {
    let mut total = FixedQ32::ZERO;
    for id in selected {
        let row = rows
            .get(id)
            .ok_or_else(|| CanonicalPromptError::UnknownFactor(id.to_string()))?;
        total = total
            .checked_add(row.net_utility_q32)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
    }
    for ((left, right), marginal) in pairs {
        if selected.contains(left) && selected.contains(right) {
            total = total
                .checked_add(*marginal)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
        }
    }
    Ok(total)
}

fn pair_key(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn scale_rate(rate: FixedQ32, units: u64) -> Result<FixedQ32, CanonicalPromptError> {
    if rate < FixedQ32::ZERO {
        return Err(CanonicalPromptError::InvalidPricingPolicy);
    }
    let product = i128::from(rate.raw())
        .checked_mul(i128::from(units))
        .ok_or(CanonicalPromptError::Arithmetic)?;
    let raw = i64::try_from(product).map_err(|_| CanonicalPromptError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn digest_candidates(candidates: &[PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_order(candidates: &[PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_candidate_receipt(
    set_id: &StableId,
    objective_digest: Digest32,
    state_digest: Digest32,
    registry_digest: Digest32,
    registry_snapshot_digest: Digest32,
    model_tuple_digest: Digest32,
    grammar_digest: Digest32,
    factor_ids: &[StableId],
    candidates_digest: Digest32,
    order_digest: Digest32,
    omitted_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, set_id);
    for digest in [
        objective_digest,
        state_digest,
        registry_digest,
        registry_snapshot_digest,
        model_tuple_digest,
        grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_pricing_receipt(
    factor_id: &StableId,
    state_digest: Digest32,
    expected_utility: FixedQ32,
    downside: FixedQ32,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence: &PromptConfidenceIntervalV1,
    policy_digest: Digest32,
    binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    push_id(&mut bytes, factor_id);
    bytes.extend_from_slice(state_digest.as_array());
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&downside.raw().to_be_bytes());
    bytes.extend_from_slice(&token_cost.to_be_bytes());
    bytes.extend_from_slice(&latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&confidence.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.support_count.to_be_bytes());
    bytes.extend_from_slice(confidence.support_audit_digest.as_array());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_set(rows: &[PricedPromptCandidateV1], policy_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    bytes.extend_from_slice(policy_digest.as_array());
    push_len(&mut bytes, rows.len());
    for row in rows {
        push_id(&mut bytes, &row.binding.factor_id);
        bytes.extend_from_slice(row.pricing.receipt_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_interactions(
    graph_result_digest: Digest32,
    evidence_digests: &[Digest32],
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.interactions.v1".to_vec();
    bytes.extend_from_slice(graph_result_digest.as_array());
    for digest in evidence_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    for (factor, prerequisites) in requires {
        push_id(&mut bytes, factor);
        for prerequisite in prerequisites {
            push_id(&mut bytes, prerequisite);
        }
    }
    for (left, right) in conflicts {
        push_id(&mut bytes, left);
        push_id(&mut bytes, right);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_portfolio_receipt(
    portfolio_id: &StableId,
    candidate_set_digest: Digest32,
    factor_ids: &[StableId],
    interaction_digest: Digest32,
    expected_utility: FixedQ32,
    total_tokens: u32,
    valid_until: u64,
    pricing_set_digest: Digest32,
    graph_generation_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    push_id(&mut bytes, portfolio_id);
    for digest in [
        candidate_set_digest,
        interaction_digest,
        pricing_set_digest,
        graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&total_tokens.to_be_bytes());
    bytes.extend_from_slice(&valid_until.to_be_bytes());
    bytes.push(0);
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

fn digest_exercise_receipt(
    portfolio_id: &StableId,
    boundary: PromptDecisionBoundaryV1,
    exercise_now: FixedQ32,
    wait: FixedQ32,
    decision: PromptExerciseActionV1,
    policy_digest: Digest32,
    portfolio_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-receipt.v1".to_vec();
    push_id(&mut bytes, portfolio_id);
    bytes.push(boundary_code(boundary));
    bytes.extend_from_slice(&exercise_now.raw().to_be_bytes());
    bytes.extend_from_slice(&wait.raw().to_be_bytes());
    bytes.push(exercise_action_code(decision));
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(portfolio_digest.as_array());
    Digest32::of_bytes(&bytes)
}

const fn boundary_code(value: PromptDecisionBoundaryV1) -> u8 {
    match value {
        PromptDecisionBoundaryV1::RequestAccepted => 0,
        PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        PromptDecisionBoundaryV1::BeforePlanning => 2,
        PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        PromptDecisionBoundaryV1::AfterObservation => 5,
        PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        PromptDecisionBoundaryV1::BeforeVerification => 8,
        PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

const fn exercise_action_code(value: PromptExerciseActionV1) -> u8 {
    match value {
        PromptExerciseActionV1::Exercise => 0,
        PromptExerciseActionV1::Wait => 1,
        PromptExerciseActionV1::RejectStale => 2,
        PromptExerciseActionV1::NoIntervention => 3,
    }
}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), CanonicalPromptError> {
    if digest.is_zero() {
        return Err(CanonicalPromptError::EmptyDigest(name));
    }
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptError {
    EmptyDigest(&'static str),
    InvalidTime,
    CandidateLimit,
    SelectionLimit,
    TokenBudgetLimit,
    Registry(String),
    RegistryReadIncomplete(u32),
    CandidateCompleteness(String),
    CandidateCompletenessBinding,
    LearningEvidence(String),
    InvalidPricingPolicy,
    MissingPricingEvidence(String),
    DuplicatePricingEvidence,
    InvalidPricingEvidence(String),
    UnknownFactor(String),
    KnowledgeGraph(String),
    GenerationVectorMismatch,
    InteractionProjectionIncomplete(u32),
    RequiredFactorUnavailable(String),
    DuplicateInteraction,
    UnexpectedPairEvidence,
    InvalidPairEvidence,
    MissingPairEvidence(String, String),
    DuplicatePairEvidence,
    PrerequisiteCycle(String),
    PortfolioExpired,
    Arithmetic,
}

impl fmt::Display for CanonicalPromptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalPromptError {}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
