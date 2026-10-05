use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::ops::Deref;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::query_relations;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::digest;
use super::raw;
use super::verified::CanonicalPromptError;
use super::verified::EnumeratedPromptCandidatesV1;
use super::verified::PricedPromptCandidatesV1;
use super::verified::PromptEnumerationRequestV1;
use super::verified::PromptPricingEvidenceV1;
use super::verified::PromptPricingUnavailableReasonV1;
use super::verified::PromptUnavailablePricingV1;
use super::verified::enumerate_factors_v1;
use super::verified::price_factors_v1;

const MAX_EXACT_ORACLE_FACTORS: usize = 20;
const MAX_LOCAL_IMPROVEMENT_ROUNDS: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairUtilityEvidenceV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub left_binding_digest: Digest32,
    pub right_binding_digest: Digest32,
    pub objective_digest: Digest32,
    pub evidence_scope_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub pricing_set_digest: Digest32,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
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
    let mut bytes = b"hepta.prompt-optimizer.pair-utility-evidence.bound.v1".to_vec();
    digest::push_id(&mut bytes, &evidence.left_factor_id);
    digest::push_id(&mut bytes, &evidence.right_factor_id);
    for value in [
        evidence.left_binding_digest,
        evidence.right_binding_digest,
        evidence.objective_digest,
        evidence.evidence_scope_digest,
        evidence.candidate_set_digest,
        evidence.pricing_set_digest,
        evidence.state_digest,
        evidence.model_tuple_digest,
        evidence.graph_generation_digest,
        evidence.edge_validity_digest,
        evidence.support_audit_digest,
    ] {
        digest::push_digest(&mut bytes, value);
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioRequestV1 {
    pub portfolio_id: StableId,
    pub graph_query_id: StableId,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub requested_valid_until_unix_ms: u64,
    pub expected_graph_source_snapshot_digest: Digest32,
    pub expected_graph_profile_digest: Digest32,
    pub exact_oracle_max_factors: usize,
    pub local_improvement_rounds: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptCandidateDispositionV1 {
    Selected,
    UnavailablePricing,
    NonPositivePackageUtility,
    TokenBudgetExcluded,
    SelectionLimitExcluded,
    HardConflict,
    Dominated,
    Superseded,
    HeuristicExcluded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateDecisionAuditV1 {
    pub factor_id: StableId,
    pub disposition: PromptCandidateDispositionV1,
    pub support_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSelectionTerminationV1 {
    ExactOracleComplete,
    NoPositiveMarginalPackage,
    SelectionLimitReached,
    LocalImprovementFixedPoint,
    LocalImprovementBudgetReached,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptOptimalityAuditV1 {
    ExactCertificate,
    HeuristicGapBound {
        upper_bound_q32: FixedQ32,
        gap_q32: FixedQ32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub decisions: Vec<PromptCandidateDecisionAuditV1>,
    pub unavailable_pricing: Vec<PromptUnavailablePricingV1>,
    pub solver_rounds: u32,
    pub local_improvement_rounds: u32,
    pub incumbent_utility_q32: FixedQ32,
    pub token_budget: u64,
    pub token_used: u64,
    pub termination: PromptSelectionTerminationV1,
    pub optimality: PromptOptimalityAuditV1,
    pub graph_source_snapshot_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority_epoch: u64,
    pub minimum_valid_until_unix_ms: u64,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedPromptPortfolioV1 {
    inner: raw::SelectedPromptPortfolioV1,
    audit: PromptPortfolioAuditV1,
    candidate_set_digest: Digest32,
    graph_source_snapshot_digest: Digest32,
    graph_profile_digest: Digest32,
    trust_digest: Digest32,
    evidence_scope_digest: Digest32,
    objective_digest: Digest32,
    authority_epoch: u64,
    minimum_valid_until_unix_ms: u64,
    verification_digest: Digest32,
}

impl SelectedPromptPortfolioV1 {
    #[must_use]
    pub fn as_raw(&self) -> &raw::SelectedPromptPortfolioV1 {
        &self.inner
    }

    #[must_use]
    pub fn into_raw(self) -> raw::SelectedPromptPortfolioV1 {
        self.inner
    }

    #[must_use]
    pub fn audit(&self) -> &PromptPortfolioAuditV1 {
        &self.audit
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(super) fn verify_internal(&self) -> Result<(), CanonicalPromptError> {
        if self.inner.receipt.authority.grants_any()
            || self.inner.receipt.candidate_set_digest != self.candidate_set_digest
            || self.inner.receipt.valid_until_unix_ms != self.minimum_valid_until_unix_ms
            || self.inner.objective_digest != self.objective_digest
            || self.inner.model_tuple_digest != self.inner.model_tuple.digest()
            || self.inner.graph_generation_digest != self.audit.graph_generation_digest
            || self.graph_source_snapshot_digest != self.audit.graph_source_snapshot_digest
            || self.graph_profile_digest != self.audit.graph_profile_digest
            || self.trust_digest != self.audit.trust_digest
            || self.authority_epoch != self.audit.authority_epoch
            || self.minimum_valid_until_unix_ms != self.audit.minimum_valid_until_unix_ms
        {
            return Err(CanonicalPromptError::PortfolioIntegrity("portfolio envelope"));
        }
        let mut selected_ids = Vec::with_capacity(self.inner.selected.len());
        let mut total_tokens = 0_u64;
        for (index, binding) in self.inner.selected.iter().enumerate() {
            if binding.factor_id != binding.realization.factor_id
                || binding.binding_digest != binding.realization.digest()
                || index > 0 && self.inner.selected[index - 1].factor_id >= binding.factor_id
            {
                return Err(CanonicalPromptError::PortfolioIntegrity("selected binding"));
            }
            selected_ids.push(binding.factor_id.clone());
            total_tokens = total_tokens
                .checked_add(u64::from(binding.realization.token_cost))
                .ok_or(CanonicalPromptError::Arithmetic)?;
        }
        let total_tokens_u32 =
            u32::try_from(total_tokens).map_err(|_| CanonicalPromptError::TokenBudgetLimit)?;
        if self.inner.receipt.factor_ids != selected_ids
            || self.inner.receipt.total_token_upper_bound != total_tokens_u32
            || self.inner.receipt.expected_utility_q32 != self.audit.incumbent_utility_q32
            || self.inner.receipt.receipt_digest
                != digest::digest_portfolio_receipt(
                    &self.inner.receipt.portfolio_id,
                    self.inner.receipt.candidate_set_digest,
                    &selected_ids,
                    self.inner.receipt.interaction_digest,
                    self.inner.receipt.expected_utility_q32,
                    total_tokens_u32,
                    self.inner.receipt.valid_until_unix_ms,
                    self.inner.pricing_set_digest,
                    self.inner.graph_generation_digest,
                )
            || self.audit.audit_digest != portfolio_audit_digest(&self.audit)
            || self.verification_digest != selected_verification_digest(self)
        {
            return Err(CanonicalPromptError::PortfolioIntegrity("portfolio digest"));
        }
        Ok(())
    }
}

impl Deref for SelectedPromptPortfolioV1 {
    type Target = raw::SelectedPromptPortfolioV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn select_portfolio_v1(
    priced: &PricedPromptCandidatesV1,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    priced.verify_internal()?;
    validate_portfolio_request(&request, now_unix_ms)?;
    if verifier.trust_digest() != priced.trust_digest
        || verifier.scope_digest() != priced.evidence_scope_digest
        || verifier.objective_digest() != priced.objective_digest
        || verifier.authority_epoch() != priced.authority_epoch
    {
        return Err(CanonicalPromptError::EvidenceContextMismatch);
    }
    graph
        .validate()
        .map_err(|error| CanonicalPromptError::KnowledgeGraph(format!("{error:?}")))?;
    if graph.generation_vector_digest != priced.inner.candidates.generation_vector_digest {
        return Err(CanonicalPromptError::GenerationVectorMismatch);
    }
    if graph.source_snapshot_digest != request.expected_graph_source_snapshot_digest
        || graph.graph_profile_digest != request.expected_graph_profile_digest
    {
        return Err(CanonicalPromptError::GraphSourceMismatch);
    }

    let all_factor_ids = priced
        .inner
        .candidates
        .candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let relation_result = query_relations(
        graph,
        KnowledgeRelationQueryV2 {
            query_id: request.graph_query_id.clone(),
            generation_digest: graph.generation_digest,
            seed_node_ids: all_factor_ids.clone(),
            valid_at_unix_seconds: Some(
                i64::try_from(now_unix_ms / 1000)
                    .map_err(|_| CanonicalPromptError::InvalidTime)?,
            ),
            relation_kinds: vec![
                KnowledgeRelationKindV2::PromptComplements,
                KnowledgeRelationKindV2::PromptSubstitutes,
                KnowledgeRelationKindV2::PromptConflicts,
                KnowledgeRelationKindV2::PromptRequires,
                KnowledgeRelationKindV2::PromptDominates,
                KnowledgeRelationKindV2::PromptRedundant,
                KnowledgeRelationKindV2::PromptSupersedes,
            ],
            maximum_edges: raw::MAX_CANONICAL_INTERACTION_EDGES,
        },
    )
    .map_err(|error| CanonicalPromptError::KnowledgeGraph(format!("{error:?}")))?;
    if relation_result.omitted_count != 0 {
        return Err(CanonicalPromptError::InteractionProjectionIncomplete(
            relation_result.omitted_count,
        ));
    }

    let known = all_factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let by_factor = priced
        .inner
        .rows
        .iter()
        .map(|row| (row.binding.factor_id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let unavailable = priced
        .unavailable
        .iter()
        .map(|row| (row.factor_id.clone(), row.reason))
        .collect::<BTreeMap<_, _>>();
    let mut requires = BTreeMap::<StableId, BTreeSet<StableId>>::new();
    let mut conflicts = BTreeSet::<(StableId, StableId)>::new();
    let mut dominated_by = BTreeMap::<StableId, StableId>::new();
    let mut superseded_by = BTreeMap::<StableId, StableId>::new();
    let mut numeric_edges =
        BTreeMap::<(StableId, StableId), (Digest32, KnowledgeRelationKindV2)>::new();
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
            | KnowledgeRelationKindV2::PromptRedundant => {
                conflicts.insert(pair_key(left, right));
            }
            KnowledgeRelationKindV2::PromptDominates => {
                if dominated_by.insert(right.clone(), left.clone()).is_some() {
                    return Err(CanonicalPromptError::DuplicateInteraction);
                }
            }
            KnowledgeRelationKindV2::PromptSupersedes => {
                if superseded_by.insert(right.clone(), left.clone()).is_some() {
                    return Err(CanonicalPromptError::DuplicateInteraction);
                }
            }
            KnowledgeRelationKindV2::PromptComplements
            | KnowledgeRelationKindV2::PromptSubstitutes => {
                let key = pair_key(left, right);
                if numeric_edges
                    .insert(
                        key,
                        (edge.validity_digest, edge.identity.relation.clone()),
                    )
                    .is_some()
                {
                    return Err(CanonicalPromptError::DuplicateInteraction);
                }
            }
            _ => {}
        }
    }
    validate_requires_acyclic(&known, &requires)?;
    for prerequisites in requires.values() {
        if let Some(missing) = prerequisites
            .iter()
            .find(|factor| unavailable.contains_key(*factor) || !by_factor.contains_key(*factor))
        {
            return Err(CanonicalPromptError::RequiredFactorUnavailable(
                missing.to_string(),
            ));
        }
    }

    let mut pair_rows = BTreeMap::<(StableId, StableId), FixedQ32>::new();
    let mut pair_payload_digests = Vec::new();
    let mut pair_evidence_by_key = BTreeMap::new();
    for evidence in pair_evidence {
        let key = pair_key(&evidence.left_factor_id, &evidence.right_factor_id);
        if pair_evidence_by_key.insert(key, evidence).is_some() {
            return Err(CanonicalPromptError::DuplicatePairEvidence);
        }
    }
    let mut minimum_valid_until = priced.minimum_evidence_valid_until_unix_ms;
    for (key, evidence) in pair_evidence_by_key {
        let Some((edge_validity_digest, _kind)) = numeric_edges.get(&key) else {
            return Err(CanonicalPromptError::UnexpectedPairEvidence);
        };
        let Some(left) = by_factor.get(&evidence.left_factor_id) else {
            return Err(CanonicalPromptError::InvalidPairEvidence);
        };
        let Some(right) = by_factor.get(&evidence.right_factor_id) else {
            return Err(CanonicalPromptError::InvalidPairEvidence);
        };
        if evidence.left_factor_id >= evidence.right_factor_id
            || evidence.left_binding_digest != left.binding.binding_digest
            || evidence.right_binding_digest != right.binding.binding_digest
            || evidence.objective_digest != priced.objective_digest
            || evidence.evidence_scope_digest != priced.evidence_scope_digest
            || evidence.candidate_set_digest != priced.inner.candidates.candidates_digest
            || evidence.pricing_set_digest != priced.inner.pricing_set_digest
            || evidence.state_digest != priced.inner.candidates.receipt.state_digest
            || evidence.model_tuple_digest != priced.inner.candidates.model_tuple.digest()
            || evidence.graph_generation_digest != graph.generation_digest
            || evidence.edge_validity_digest != *edge_validity_digest
            || evidence.support_audit_digest.is_zero()
            || evidence.confidence_lower_q32 > evidence.marginal_utility_q32
            || evidence.marginal_utility_q32 > evidence.confidence_upper_q32
        {
            return Err(CanonicalPromptError::InvalidPairEvidence);
        }
        let payload = pair_utility_evidence_signing_payload_v1(&evidence);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| CanonicalPromptError::Evidence(format!("{error:?}")))?;
        verify_signed_independent_roles_v1(
            &priced.generator_evidence,
            &evaluator,
            now_unix_ms,
        )
        .map_err(|_| CanonicalPromptError::EvidenceIndependence)?;
        minimum_valid_until = minimum_valid_until.min(evidence.evidence.expires_at);
        pair_payload_digests.push(evaluator.payload_digest());
        pair_rows.insert(key, evidence.marginal_utility_q32);
    }
    for key in numeric_edges.keys() {
        if !pair_rows.contains_key(key) {
            return Err(CanonicalPromptError::MissingPairEvidence(
                key.0.to_string(),
                key.1.to_string(),
            ));
        }
    }
    if let Some(graph_expiry) = minimum_graph_valid_until(&relation_result.edges)? {
        minimum_valid_until = minimum_valid_until.min(graph_expiry);
    }
    minimum_valid_until = minimum_valid_until.min(request.requested_valid_until_unix_ms);
    for row in by_factor.values() {
        if let Some(expires) = row.binding.realization.expires_unix_ms {
            minimum_valid_until = minimum_valid_until.min(expires);
        }
    }
    if minimum_valid_until <= now_unix_ms {
        return Err(CanonicalPromptError::EvidenceExpired);
    }

    let mut closures = BTreeMap::new();
    for factor in by_factor.keys() {
        let closure = prerequisite_closure(factor, &requires)?;
        if violates_conflict(&closure, &conflicts)
            || closure.iter().any(|value| dominated_by.contains_key(value))
            || closure.iter().any(|value| superseded_by.contains_key(value))
        {
            return Err(CanonicalPromptError::UnsatisfiableConstraintGraph(
                factor.to_string(),
            ));
        }
        closures.insert(factor.clone(), closure);
    }

    let exact_limit = request
        .exact_oracle_max_factors
        .min(MAX_EXACT_ORACLE_FACTORS);
    let (selected, solver_rounds, local_rounds, termination, optimality) =
        if !by_factor.is_empty() && by_factor.len() <= exact_limit {
            let exact = exact_portfolio(
                &by_factor,
                &requires,
                &closures,
                &conflicts,
                &dominated_by,
                &superseded_by,
                &pair_rows,
                &request,
            )?;
            (
                exact,
                1_u32,
                0_u32,
                PromptSelectionTerminationV1::ExactOracleComplete,
                PromptOptimalityAuditV1::ExactCertificate,
            )
        } else {
            let (greedy, rounds, greedy_termination) = greedy_portfolio(
                &by_factor,
                &closures,
                &conflicts,
                &dominated_by,
                &superseded_by,
                &pair_rows,
                &request,
            )?;
            let (improved, local_rounds, local_termination) = improve_portfolio(
                greedy,
                &by_factor,
                &requires,
                &closures,
                &conflicts,
                &dominated_by,
                &superseded_by,
                &pair_rows,
                &request,
            )?;
            let incumbent = portfolio_utility(&improved, &by_factor, &pair_rows)?;
            let upper = optimistic_upper_bound(&by_factor, &pair_rows)?;
            let gap = if upper > incumbent {
                upper
                    .checked_sub(incumbent)
                    .map_err(|_| CanonicalPromptError::Arithmetic)?
            } else {
                FixedQ32::ZERO
            };
            (
                improved,
                rounds,
                local_rounds,
                if local_rounds == 0 {
                    greedy_termination
                } else {
                    local_termination
                },
                PromptOptimalityAuditV1::HeuristicGapBound {
                    upper_bound_q32: upper,
                    gap_q32: gap,
                },
            )
        };

    let expected_utility = portfolio_utility(&selected, &by_factor, &pair_rows)?;
    let total_tokens = portfolio_token_cost(&selected, &by_factor)?;
    let total_token_upper_bound =
        u32::try_from(total_tokens).map_err(|_| CanonicalPromptError::TokenBudgetLimit)?;
    let mut selected_bindings = selected
        .iter()
        .filter_map(|factor| by_factor.get(factor).map(|row| row.binding.clone()))
        .collect::<Vec<_>>();
    selected_bindings.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let selected_ids = selected_bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    pair_payload_digests.sort();
    let interaction_digest = digest_interactions(
        relation_result.result_digest,
        &pair_payload_digests,
        &requires,
        &conflicts,
        &dominated_by,
        &superseded_by,
    );
    let receipt_digest = digest::digest_portfolio_receipt(
        &request.portfolio_id,
        priced.inner.candidates.candidates_digest,
        &selected_ids,
        interaction_digest,
        expected_utility,
        total_token_upper_bound,
        minimum_valid_until,
        priced.inner.pricing_set_digest,
        graph.generation_digest,
    );
    let decisions = candidate_decisions(
        priced,
        &selected,
        &by_factor,
        &closures,
        &conflicts,
        &dominated_by,
        &superseded_by,
        &pair_rows,
        &request,
    )?;
    let mut audit = PromptPortfolioAuditV1 {
        decisions,
        unavailable_pricing: priced.unavailable.clone(),
        solver_rounds,
        local_improvement_rounds: local_rounds,
        incumbent_utility_q32: expected_utility,
        token_budget: request.token_budget,
        token_used: total_tokens,
        termination,
        optimality,
        graph_source_snapshot_digest: graph.source_snapshot_digest,
        graph_generation_digest: graph.generation_digest,
        graph_profile_digest: graph.graph_profile_digest,
        trust_digest: priced.trust_digest,
        authority_epoch: priced.authority_epoch,
        minimum_valid_until_unix_ms: minimum_valid_until,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = portfolio_audit_digest(&audit);
    let inner = raw::SelectedPromptPortfolioV1 {
        receipt: raw::PromptPortfolioReceiptV1 {
            portfolio_id: request.portfolio_id,
            candidate_set_digest: priced.inner.candidates.candidates_digest,
            factor_ids: selected_ids,
            interaction_digest,
            expected_utility_q32: expected_utility,
            total_token_upper_bound,
            valid_until_unix_ms: minimum_valid_until,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: selected_bindings,
        objective_digest: priced.objective_digest,
        state_digest: priced.inner.candidates.receipt.state_digest,
        model_tuple: priced.inner.candidates.model_tuple.clone(),
        model_tuple_digest: priced.inner.candidates.model_tuple.digest(),
        generation_vector_digest: priced.inner.candidates.generation_vector_digest,
        pricing_set_digest: priced.inner.pricing_set_digest,
        graph_generation_digest: graph.generation_digest,
        selection_method: raw::PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: raw::PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    let mut result = SelectedPromptPortfolioV1 {
        inner,
        audit,
        candidate_set_digest: priced.inner.candidates.candidates_digest,
        graph_source_snapshot_digest: graph.source_snapshot_digest,
        graph_profile_digest: graph.graph_profile_digest,
        trust_digest: priced.trust_digest,
        evidence_scope_digest: priced.evidence_scope_digest,
        objective_digest: priced.objective_digest,
        authority_epoch: priced.authority_epoch,
        minimum_valid_until_unix_ms: minimum_valid_until,
        verification_digest: Digest32::ZERO,
    };
    result.verification_digest = selected_verification_digest(&result);
    result.verify_internal()?;
    Ok(result)
}

fn validate_portfolio_request(
    request: &PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<(), CanonicalPromptError> {
    if request.maximum_selected_factors == 0
        || request.maximum_selected_factors > raw::MAX_CANONICAL_SELECTED_FACTORS
    {
        return Err(CanonicalPromptError::SelectionLimit);
    }
    if request.token_budget > raw::MAX_CANONICAL_TOKEN_BUDGET {
        return Err(CanonicalPromptError::TokenBudgetLimit);
    }
    if now_unix_ms == 0 || request.requested_valid_until_unix_ms <= now_unix_ms {
        return Err(CanonicalPromptError::InvalidTime);
    }
    if request.expected_graph_source_snapshot_digest.is_zero()
        || request.expected_graph_profile_digest.is_zero()
        || request.exact_oracle_max_factors > MAX_EXACT_ORACLE_FACTORS
        || request.local_improvement_rounds > MAX_LOCAL_IMPROVEMENT_ROUNDS
    {
        return Err(CanonicalPromptError::KnowledgeGraph(
            "invalid portfolio policy bounds".to_owned(),
        ));
    }
    Ok(())
}

fn greedy_portfolio(
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
    closures: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    dominated_by: &BTreeMap<StableId, StableId>,
    superseded_by: &BTreeMap<StableId, StableId>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
    request: &PromptPortfolioRequestV1,
) -> Result<(BTreeSet<StableId>, u32, PromptSelectionTerminationV1), CanonicalPromptError> {
    let mut selected = BTreeSet::new();
    let mut rounds = 0_u32;
    loop {
        if selected.len() >= request.maximum_selected_factors {
            return Ok((
                selected,
                rounds,
                PromptSelectionTerminationV1::SelectionLimitReached,
            ));
        }
        let base = portfolio_utility(&selected, rows, pairs)?;
        let mut best: Option<(StableId, BTreeSet<StableId>, FixedQ32, u64)> = None;
        for factor in rows.keys() {
            if selected.contains(factor)
                || dominated_by.contains_key(factor)
                || superseded_by.contains_key(factor)
            {
                continue;
            }
            let closure = closures
                .get(factor)
                .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor.to_string()))?;
            let mut proposed = selected.clone();
            proposed.extend(closure.iter().cloned());
            if proposed.len() > request.maximum_selected_factors
                || violates_conflict(&proposed, conflicts)
                || proposed.iter().any(|value| dominated_by.contains_key(value))
                || proposed.iter().any(|value| superseded_by.contains_key(value))
                || portfolio_token_cost(&proposed, rows)? > request.token_budget
            {
                continue;
            }
            let next = portfolio_utility(&proposed, rows, pairs)?;
            let marginal = next
                .checked_sub(base)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let added = closure.difference(&selected).cloned().collect::<BTreeSet<_>>();
            let tokens = portfolio_token_cost(&added, rows)?;
            let better = best
                .as_ref()
                .is_none_or(|(best_id, _, best_gain, best_tokens)| {
                    marginal > *best_gain
                        || (marginal == *best_gain
                            && (tokens < *best_tokens
                                || (tokens == *best_tokens && factor < best_id)))
                });
            if better {
                best = Some((factor.clone(), proposed, marginal, tokens));
            }
        }
        let Some((_, proposed, _, _)) = best else {
            return Ok((
                selected,
                rounds,
                PromptSelectionTerminationV1::NoPositiveMarginalPackage,
            ));
        };
        selected = proposed;
        rounds = rounds.saturating_add(1);
        if rounds >= raw::MAX_CANONICAL_PROMPT_FACTORS as u32 {
            return Ok((
                selected,
                rounds,
                PromptSelectionTerminationV1::NoPositiveMarginalPackage,
            ));
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn improve_portfolio(
    mut selected: BTreeSet<StableId>,
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    closures: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    dominated_by: &BTreeMap<StableId, StableId>,
    superseded_by: &BTreeMap<StableId, StableId>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
    request: &PromptPortfolioRequestV1,
) -> Result<(BTreeSet<StableId>, u32, PromptSelectionTerminationV1), CanonicalPromptError> {
    let mut rounds = 0_u32;
    while usize::try_from(rounds).unwrap_or(usize::MAX) < request.local_improvement_rounds {
        let current_utility = portfolio_utility(&selected, rows, pairs)?;
        let mut best: Option<(BTreeSet<StableId>, FixedQ32, u64)> = None;
        let removals = selected.iter().cloned().collect::<Vec<_>>();
        for removed in removals {
            let mut base = selected.clone();
            base.remove(&removed);
            if !requirements_closed(&base, requires) {
                continue;
            }
            for root in rows.keys() {
                if base.contains(root)
                    || dominated_by.contains_key(root)
                    || superseded_by.contains_key(root)
                {
                    continue;
                }
                let mut proposed = base.clone();
                proposed.extend(
                    closures
                        .get(root)
                        .ok_or_else(|| CanonicalPromptError::UnknownFactor(root.to_string()))?
                        .iter()
                        .cloned(),
                );
                if proposed.len() > request.maximum_selected_factors
                    || violates_conflict(&proposed, conflicts)
                    || proposed.iter().any(|value| dominated_by.contains_key(value))
                    || proposed.iter().any(|value| superseded_by.contains_key(value))
                {
                    continue;
                }
                let tokens = portfolio_token_cost(&proposed, rows)?;
                if tokens > request.token_budget {
                    continue;
                }
                let utility = portfolio_utility(&proposed, rows, pairs)?;
                if utility <= current_utility {
                    continue;
                }
                let better = best.as_ref().is_none_or(|(best_set, best_utility, best_tokens)| {
                    utility > *best_utility
                        || (utility == *best_utility
                            && (tokens < *best_tokens
                                || (tokens == *best_tokens
                                    && proposed.iter().cmp(best_set.iter()).is_lt())))
                });
                if better {
                    best = Some((proposed, utility, tokens));
                }
            }
        }
        let Some((next, _, _)) = best else {
            return Ok((
                selected,
                rounds,
                PromptSelectionTerminationV1::LocalImprovementFixedPoint,
            ));
        };
        selected = next;
        rounds = rounds.saturating_add(1);
    }
    Ok((
        selected,
        rounds,
        PromptSelectionTerminationV1::LocalImprovementBudgetReached,
    ))
}

#[allow(clippy::too_many_arguments)]
fn exact_portfolio(
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    _closures: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    dominated_by: &BTreeMap<StableId, StableId>,
    superseded_by: &BTreeMap<StableId, StableId>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
    request: &PromptPortfolioRequestV1,
) -> Result<BTreeSet<StableId>, CanonicalPromptError> {
    let ids = rows.keys().cloned().collect::<Vec<_>>();
    if ids.len() > MAX_EXACT_ORACLE_FACTORS {
        return Err(CanonicalPromptError::CandidateLimit);
    }
    let mut best = BTreeSet::new();
    let mut best_utility = FixedQ32::ZERO;
    let mut best_tokens = 0_u64;
    let limit = 1_u64
        .checked_shl(u32::try_from(ids.len()).map_err(|_| CanonicalPromptError::CandidateLimit)?)
        .ok_or(CanonicalPromptError::CandidateLimit)?;
    for mask in 0..limit {
        if usize::try_from(mask.count_ones()).unwrap_or(usize::MAX)
            > request.maximum_selected_factors
        {
            continue;
        }
        let mut candidate = BTreeSet::new();
        for (index, id) in ids.iter().enumerate() {
            if mask & (1_u64 << index) != 0 {
                candidate.insert(id.clone());
            }
        }
        if !requirements_closed(&candidate, requires)
            || violates_conflict(&candidate, conflicts)
            || candidate.iter().any(|value| dominated_by.contains_key(value))
            || candidate.iter().any(|value| superseded_by.contains_key(value))
        {
            continue;
        }
        let tokens = portfolio_token_cost(&candidate, rows)?;
        if tokens > request.token_budget {
            continue;
        }
        let utility = portfolio_utility(&candidate, rows, pairs)?;
        if utility < FixedQ32::ZERO {
            continue;
        }
        if utility > best_utility
            || (utility == best_utility
                && (tokens < best_tokens
                    || (tokens == best_tokens && candidate.iter().cmp(best.iter()).is_lt())))
        {
            best = candidate;
            best_utility = utility;
            best_tokens = tokens;
        }
    }
    Ok(best)
}

fn candidate_decisions(
    priced: &PricedPromptCandidatesV1,
    selected: &BTreeSet<StableId>,
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
    closures: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    dominated_by: &BTreeMap<StableId, StableId>,
    superseded_by: &BTreeMap<StableId, StableId>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
    request: &PromptPortfolioRequestV1,
) -> Result<Vec<PromptCandidateDecisionAuditV1>, CanonicalPromptError> {
    let unavailable = priced
        .unavailable
        .iter()
        .map(|row| (row.factor_id.clone(), row.reason))
        .collect::<BTreeMap<_, _>>();
    let mut result = Vec::new();
    for factor in &priced.inner.candidates.receipt.candidate_factor_ids {
        let disposition = if selected.contains(factor) {
            PromptCandidateDispositionV1::Selected
        } else if unavailable.contains_key(factor) || !rows.contains_key(factor) {
            PromptCandidateDispositionV1::UnavailablePricing
        } else if dominated_by.contains_key(factor) {
            PromptCandidateDispositionV1::Dominated
        } else if superseded_by.contains_key(factor) {
            PromptCandidateDispositionV1::Superseded
        } else {
            let closure = closures
                .get(factor)
                .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor.to_string()))?;
            let utility = portfolio_utility(closure, rows, pairs)?;
            if utility <= FixedQ32::ZERO {
                PromptCandidateDispositionV1::NonPositivePackageUtility
            } else if closure.len() > request.maximum_selected_factors {
                PromptCandidateDispositionV1::SelectionLimitExcluded
            } else if portfolio_token_cost(closure, rows)? > request.token_budget {
                PromptCandidateDispositionV1::TokenBudgetExcluded
            } else {
                let mut combined = selected.clone();
                combined.extend(closure.iter().cloned());
                if violates_conflict(&combined, conflicts) {
                    PromptCandidateDispositionV1::HardConflict
                } else if combined.len() > request.maximum_selected_factors {
                    PromptCandidateDispositionV1::SelectionLimitExcluded
                } else if portfolio_token_cost(&combined, rows)? > request.token_budget {
                    PromptCandidateDispositionV1::TokenBudgetExcluded
                } else {
                    PromptCandidateDispositionV1::HeuristicExcluded
                }
            }
        };
        let mut support = b"hepta.prompt-optimizer.candidate-disposition.v1".to_vec();
        digest::push_id(&mut support, factor);
        support.push(disposition_code(disposition));
        result.push(PromptCandidateDecisionAuditV1 {
            factor_id: factor.clone(),
            disposition,
            support_digest: Digest32::of_bytes(&support),
        });
    }
    Ok(result)
}

fn disposition_code(value: PromptCandidateDispositionV1) -> u8 {
    match value {
        PromptCandidateDispositionV1::Selected => 0,
        PromptCandidateDispositionV1::UnavailablePricing => 1,
        PromptCandidateDispositionV1::NonPositivePackageUtility => 2,
        PromptCandidateDispositionV1::TokenBudgetExcluded => 3,
        PromptCandidateDispositionV1::SelectionLimitExcluded => 4,
        PromptCandidateDispositionV1::HardConflict => 5,
        PromptCandidateDispositionV1::Dominated => 6,
        PromptCandidateDispositionV1::Superseded => 7,
        PromptCandidateDispositionV1::HeuristicExcluded => 8,
    }
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

fn requirements_closed(
    selected: &BTreeSet<StableId>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
) -> bool {
    selected.iter().all(|factor| {
        requires
            .get(factor)
            .is_none_or(|required| required.iter().all(|value| selected.contains(value)))
    })
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
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
) -> Result<u64, CanonicalPromptError> {
    selected.iter().try_fold(0_u64, |total, id| {
        let row = rows
            .get(id)
            .ok_or_else(|| CanonicalPromptError::UnknownFactor(id.to_string()))?;
        total
            .checked_add(u64::from(row.pricing.token_cost))
            .ok_or(CanonicalPromptError::Arithmetic)
    })
}

fn portfolio_utility(
    selected: &BTreeSet<StableId>,
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
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

fn optimistic_upper_bound(
    rows: &BTreeMap<StableId, &raw::PricedPromptCandidateV1>,
    pairs: &BTreeMap<(StableId, StableId), FixedQ32>,
) -> Result<FixedQ32, CanonicalPromptError> {
    let mut total = FixedQ32::ZERO;
    for row in rows.values() {
        if row.net_utility_q32 > FixedQ32::ZERO {
            total = total
                .checked_add(row.net_utility_q32)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
        }
    }
    for marginal in pairs.values() {
        if *marginal > FixedQ32::ZERO {
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

fn minimum_graph_valid_until(
    edges: &[codex_hepta_kg::KnowledgeEdgeV2],
) -> Result<Option<u64>, CanonicalPromptError> {
    let mut minimum: Option<u64> = None;
    for edge in edges {
        for support in &edge.supports {
            if let Some(seconds) = support.valid_to_unix_seconds {
                if seconds <= 0 {
                    return Err(CanonicalPromptError::KnowledgeGraph(
                        "invalid relation validity".to_owned(),
                    ));
                }
                let millis = u64::try_from(seconds)
                    .map_err(|_| CanonicalPromptError::InvalidTime)?
                    .checked_mul(1000)
                    .ok_or(CanonicalPromptError::InvalidTime)?;
                minimum = Some(minimum.map_or(millis, |value| value.min(millis)));
            }
        }
    }
    Ok(minimum)
}

fn digest_interactions(
    result_digest: Digest32,
    evidence_digests: &[Digest32],
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    dominated_by: &BTreeMap<StableId, StableId>,
    superseded_by: &BTreeMap<StableId, StableId>,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.interactions.bound.v1".to_vec();
    digest::push_digest(&mut bytes, result_digest);
    for value in evidence_digests {
        digest::push_digest(&mut bytes, *value);
    }
    for (factor, prerequisites) in requires {
        digest::push_id(&mut bytes, factor);
        for prerequisite in prerequisites {
            digest::push_id(&mut bytes, prerequisite);
        }
    }
    for (left, right) in conflicts {
        digest::push_id(&mut bytes, left);
        digest::push_id(&mut bytes, right);
    }
    for (target, source) in dominated_by {
        digest::push_id(&mut bytes, target);
        digest::push_id(&mut bytes, source);
    }
    for (target, source) in superseded_by {
        digest::push_id(&mut bytes, target);
        digest::push_id(&mut bytes, source);
    }
    Digest32::of_bytes(&bytes)
}

fn portfolio_audit_digest(value: &PromptPortfolioAuditV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-audit.v1".to_vec();
    digest::push_len(&mut bytes, value.decisions.len());
    for row in &value.decisions {
        digest::push_id(&mut bytes, &row.factor_id);
        bytes.push(disposition_code(row.disposition));
        digest::push_digest(&mut bytes, row.support_digest);
    }
    digest::push_len(&mut bytes, value.unavailable_pricing.len());
    for row in &value.unavailable_pricing {
        digest::push_id(&mut bytes, &row.factor_id);
        bytes.push(match row.reason {
            PromptPricingUnavailableReasonV1::MissingEvidence => 0,
            PromptPricingUnavailableReasonV1::EvidenceExpired => 1,
            PromptPricingUnavailableReasonV1::EvidenceRevoked => 2,
        });
    }
    bytes.extend_from_slice(&value.solver_rounds.to_be_bytes());
    bytes.extend_from_slice(&value.local_improvement_rounds.to_be_bytes());
    bytes.extend_from_slice(&value.incumbent_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.token_budget.to_be_bytes());
    bytes.extend_from_slice(&value.token_used.to_be_bytes());
    bytes.push(match value.termination {
        PromptSelectionTerminationV1::ExactOracleComplete => 0,
        PromptSelectionTerminationV1::NoPositiveMarginalPackage => 1,
        PromptSelectionTerminationV1::SelectionLimitReached => 2,
        PromptSelectionTerminationV1::LocalImprovementFixedPoint => 3,
        PromptSelectionTerminationV1::LocalImprovementBudgetReached => 4,
    });
    match value.optimality {
        PromptOptimalityAuditV1::ExactCertificate => bytes.push(0),
        PromptOptimalityAuditV1::HeuristicGapBound {
            upper_bound_q32,
            gap_q32,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(&upper_bound_q32.raw().to_be_bytes());
            bytes.extend_from_slice(&gap_q32.raw().to_be_bytes());
        }
    }
    for item in [
        value.graph_source_snapshot_digest,
        value.graph_generation_digest,
        value.graph_profile_digest,
        value.trust_digest,
    ] {
        digest::push_digest(&mut bytes, item);
    }
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.minimum_valid_until_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn selected_verification_digest(value: &SelectedPromptPortfolioV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-portfolio.v1".to_vec();
    for item in [
        value.inner.receipt.receipt_digest,
        value.audit.audit_digest,
        value.candidate_set_digest,
        value.graph_source_snapshot_digest,
        value.graph_profile_digest,
        value.trust_digest,
        value.evidence_scope_digest,
        value.objective_digest,
    ] {
        digest::push_digest(&mut bytes, item);
    }
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.minimum_valid_until_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExercisePolicyV1 {
    policy_id: StableId,
    objective_digest: Digest32,
    evidence_scope_digest: Digest32,
    allowed_boundaries: Vec<raw::PromptDecisionBoundaryV1>,
    valid_from_unix_ms: u64,
    valid_until_unix_ms: u64,
    digest: Digest32,
}

impl PromptExercisePolicyV1 {
    pub fn new(
        policy_id: StableId,
        objective_digest: Digest32,
        evidence_scope_digest: Digest32,
        allowed_boundaries: Vec<raw::PromptDecisionBoundaryV1>,
        valid_from_unix_ms: u64,
        valid_until_unix_ms: u64,
    ) -> Result<Self, CanonicalPromptError> {
        if objective_digest.is_zero()
            || evidence_scope_digest.is_zero()
            || allowed_boundaries.is_empty()
            || valid_from_unix_ms == 0
            || valid_until_unix_ms <= valid_from_unix_ms
        {
            return Err(CanonicalPromptError::PolicyMismatch);
        }
        let mut codes = BTreeSet::new();
        for boundary in &allowed_boundaries {
            if !codes.insert(digest::boundary_code(*boundary)) {
                return Err(CanonicalPromptError::PolicyMismatch);
            }
        }
        let mut result = Self {
            policy_id,
            objective_digest,
            evidence_scope_digest,
            allowed_boundaries,
            valid_from_unix_ms,
            valid_until_unix_ms,
            digest: Digest32::ZERO,
        };
        result.digest = exercise_policy_digest(&result);
        Ok(result)
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    fn validate(&self) -> Result<(), CanonicalPromptError> {
        if self.digest.is_zero() || self.digest != exercise_policy_digest(self) {
            return Err(CanonicalPromptError::PolicyMismatch);
        }
        Ok(())
    }
}

fn exercise_policy_digest(value: &PromptExercisePolicyV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-policy.v1".to_vec();
    digest::push_id(&mut bytes, &value.policy_id);
    digest::push_digest(&mut bytes, value.objective_digest);
    digest::push_digest(&mut bytes, value.evidence_scope_digest);
    digest::push_len(&mut bytes, value.allowed_boundaries.len());
    for boundary in &value.allowed_boundaries {
        bytes.push(digest::boundary_code(*boundary));
    }
    bytes.extend_from_slice(&value.valid_from_unix_ms.to_be_bytes());
    bytes.extend_from_slice(&value.valid_until_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseRequestV1 {
    pub decision_boundary: raw::PromptDecisionBoundaryV1,
    pub current_state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub policy: PromptExercisePolicyV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseRejectionReasonV1 {
    StateDrift,
    GenerationDrift,
    ModelDrift,
    RegistryStale,
    RealizationRevokedOrUnavailable,
    EvidenceExpired,
    TrustDrift,
    GraphDrift,
    PolicyExpired,
    PolicyBoundaryDenied,
    DependencyUnavailable,
    DependencyCorrupt,
    DependencyIndeterminate,
    DependencyQuarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseAuditV1 {
    pub rejection_reason: Option<PromptExerciseRejectionReasonV1>,
    pub portfolio_verification_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority_epoch: u64,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPromptExerciseDecisionV1 {
    inner: raw::PromptExerciseDecisionV1,
    audit: PromptExerciseAuditV1,
    verification_digest: Digest32,
}

impl VerifiedPromptExerciseDecisionV1 {
    #[must_use]
    pub fn receipt(&self) -> &raw::PromptExerciseDecisionV1 {
        &self.inner
    }

    #[must_use]
    pub fn audit(&self) -> &PromptExerciseAuditV1 {
        &self.audit
    }

    #[must_use]
    pub fn into_receipt(self) -> raw::PromptExerciseDecisionV1 {
        self.inner
    }
}

impl Deref for VerifiedPromptExerciseDecisionV1 {
    type Target = raw::PromptExerciseDecisionV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    graph: &KnowledgeGenerationV2,
    verifier: &LearningEvidenceVerifierV1,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptExerciseRequestV1,
) -> Result<VerifiedPromptExerciseDecisionV1, CanonicalPromptError> {
    portfolio.verify_internal()?;
    request.policy.validate()?;
    if request.current_state_digest.is_zero()
        || request.generation_vector_digest.is_zero()
        || request.now_unix_ms == 0
    {
        return Err(CanonicalPromptError::InvalidTime);
    }
    let reason = if request.policy.objective_digest != portfolio.objective_digest
        || request.policy.evidence_scope_digest != portfolio.evidence_scope_digest
    {
        Some(PromptExerciseRejectionReasonV1::TrustDrift)
    } else if !request
        .policy
        .allowed_boundaries
        .contains(&request.decision_boundary)
    {
        Some(PromptExerciseRejectionReasonV1::PolicyBoundaryDenied)
    } else if request.now_unix_ms < request.policy.valid_from_unix_ms
        || request.now_unix_ms >= request.policy.valid_until_unix_ms
    {
        Some(PromptExerciseRejectionReasonV1::PolicyExpired)
    } else if verifier.trust_digest() != portfolio.trust_digest
        || verifier.scope_digest() != portfolio.evidence_scope_digest
        || verifier.objective_digest() != portfolio.objective_digest
        || verifier.authority_epoch() != portfolio.authority_epoch
    {
        Some(PromptExerciseRejectionReasonV1::TrustDrift)
    } else if graph.validate().is_err()
        || graph.generation_digest != portfolio.inner.graph_generation_digest
        || graph.source_snapshot_digest != portfolio.graph_source_snapshot_digest
        || graph.graph_profile_digest != portfolio.graph_profile_digest
    {
        Some(PromptExerciseRejectionReasonV1::GraphDrift)
    } else if request.now_unix_ms >= portfolio.minimum_valid_until_unix_ms {
        Some(PromptExerciseRejectionReasonV1::EvidenceExpired)
    } else if request.current_state_digest != portfolio.inner.state_digest {
        Some(PromptExerciseRejectionReasonV1::StateDrift)
    } else if request.generation_vector_digest != portfolio.inner.generation_vector_digest {
        Some(PromptExerciseRejectionReasonV1::GenerationDrift)
    } else if request.model_tuple != portfolio.inner.model_tuple
        || request.model_tuple.digest() != portfolio.inner.model_tuple_digest
    {
        Some(PromptExerciseRejectionReasonV1::ModelDrift)
    } else {
        current_registry_rejection_reason(registry, portfolio, &request)?
    };

    let action = if portfolio.inner.selected.is_empty() {
        raw::PromptExerciseActionV1::NoIntervention
    } else if reason.is_some() {
        raw::PromptExerciseActionV1::RejectStale
    } else if portfolio.inner.receipt.expected_utility_q32 > request.wait_value_q32 {
        raw::PromptExerciseActionV1::Exercise
    } else {
        raw::PromptExerciseActionV1::Wait
    };
    let receipt_digest = digest::digest_exercise_receipt(
        &portfolio.inner.receipt.portfolio_id,
        request.decision_boundary,
        portfolio.inner.receipt.expected_utility_q32,
        request.wait_value_q32,
        action,
        request.policy.digest,
        portfolio.inner.receipt.receipt_digest,
    );
    let inner = raw::PromptExerciseDecisionV1 {
        factor_or_portfolio_id: portfolio.inner.receipt.portfolio_id.clone(),
        decision_boundary: request.decision_boundary,
        exercise_now_value_q32: portfolio.inner.receipt.expected_utility_q32,
        wait_value_q32: request.wait_value_q32,
        decision: action,
        policy_digest: request.policy.digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    let mut audit = PromptExerciseAuditV1 {
        rejection_reason: reason,
        portfolio_verification_digest: portfolio.verification_digest,
        graph_generation_digest: graph.generation_digest,
        trust_digest: verifier.trust_digest(),
        authority_epoch: verifier.authority_epoch(),
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = exercise_audit_digest(&audit);
    let mut result = VerifiedPromptExerciseDecisionV1 {
        inner,
        audit,
        verification_digest: Digest32::ZERO,
    };
    result.verification_digest = exercise_verification_digest(&result);
    if result.inner.authority.grants_any()
        || result.inner.receipt_digest.is_zero()
        || result.audit.audit_digest != exercise_audit_digest(&result.audit)
        || result.verification_digest != exercise_verification_digest(&result)
    {
        return Err(CanonicalPromptError::Corrupt("exercise receipt"));
    }
    Ok(result)
}

fn current_registry_rejection_reason(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: &PromptExerciseRequestV1,
) -> Result<Option<PromptExerciseRejectionReasonV1>, CanonicalPromptError> {
    let snapshot = match registry.snapshot_v2(
        request.generation_vector_digest,
        &request.model_tuple,
    ) {
        Ok(value) => value,
        Err(PromptRegistryV2Error::SnapshotStale) => {
            return Ok(Some(PromptExerciseRejectionReasonV1::RegistryStale));
        }
        Err(PromptRegistryV2Error::DigestMismatch(_)
        | PromptRegistryV2Error::InvalidFrontier
        | PromptRegistryV2Error::AuthorityGranted) => {
            return Ok(Some(PromptExerciseRejectionReasonV1::DependencyCorrupt));
        }
        Err(_) => {
            return Ok(Some(
                PromptExerciseRejectionReasonV1::DependencyUnavailable,
            ));
        }
    };
    let selected_ids = portfolio
        .inner
        .selected
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    let current = match registry.read_compatible_v2(
        &snapshot,
        request.generation_vector_digest,
        &request.model_tuple,
        request.now_unix_ms,
        selected_ids,
        raw::MAX_CANONICAL_PROMPT_FACTORS as u32,
    ) {
        Ok(value) => value,
        Err(PromptRegistryV2Error::SnapshotStale) => {
            return Ok(Some(PromptExerciseRejectionReasonV1::RegistryStale));
        }
        Err(PromptRegistryV2Error::RequiredFactorUnavailable) => {
            return Ok(Some(
                PromptExerciseRejectionReasonV1::RealizationRevokedOrUnavailable,
            ));
        }
        Err(PromptRegistryV2Error::DigestMismatch(_)
        | PromptRegistryV2Error::PayloadDigestMismatch
        | PromptRegistryV2Error::InvalidFrontier
        | PromptRegistryV2Error::AuthorityGranted) => {
            return Ok(Some(PromptExerciseRejectionReasonV1::DependencyCorrupt));
        }
        Err(_) => {
            return Ok(Some(
                PromptExerciseRejectionReasonV1::DependencyUnavailable,
            ));
        }
    };
    let current_by_realization = current
        .bindings
        .into_iter()
        .map(|binding| (binding.realization_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();
    let exact = portfolio.inner.selected.iter().all(|selected| {
        current_by_realization
            .get(&selected.realization.realization_id)
            .is_some_and(|current| {
                current.realization_id == selected.realization.realization_id
                    && current.digest() == selected.binding_digest
            })
    });
    Ok((!exact).then_some(
        PromptExerciseRejectionReasonV1::RealizationRevokedOrUnavailable,
    ))
}

fn exercise_audit_digest(value: &PromptExerciseAuditV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-audit.v1".to_vec();
    bytes.push(value.rejection_reason.map_or(255, exercise_reason_code));
    for item in [
        value.portfolio_verification_digest,
        value.graph_generation_digest,
        value.trust_digest,
    ] {
        digest::push_digest(&mut bytes, item);
    }
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn exercise_reason_code(value: PromptExerciseRejectionReasonV1) -> u8 {
    match value {
        PromptExerciseRejectionReasonV1::StateDrift => 0,
        PromptExerciseRejectionReasonV1::GenerationDrift => 1,
        PromptExerciseRejectionReasonV1::ModelDrift => 2,
        PromptExerciseRejectionReasonV1::RegistryStale => 3,
        PromptExerciseRejectionReasonV1::RealizationRevokedOrUnavailable => 4,
        PromptExerciseRejectionReasonV1::EvidenceExpired => 5,
        PromptExerciseRejectionReasonV1::TrustDrift => 6,
        PromptExerciseRejectionReasonV1::GraphDrift => 7,
        PromptExerciseRejectionReasonV1::PolicyExpired => 8,
        PromptExerciseRejectionReasonV1::PolicyBoundaryDenied => 9,
        PromptExerciseRejectionReasonV1::DependencyUnavailable => 10,
        PromptExerciseRejectionReasonV1::DependencyCorrupt => 11,
        PromptExerciseRejectionReasonV1::DependencyIndeterminate => 12,
        PromptExerciseRejectionReasonV1::DependencyQuarantined => 13,
    }
}

fn exercise_verification_digest(value: &VerifiedPromptExerciseDecisionV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-exercise.v1".to_vec();
    digest::push_digest(&mut bytes, value.inner.receipt_digest);
    digest::push_digest(&mut bytes, value.audit.audit_digest);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug)]
pub struct CanonicalPromptPlanInputsV1 {
    pub enumeration: PromptEnumerationRequestV1,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_evidence: SignedLearningEvidenceV1,
    pub pricing_evidence: Vec<PromptPricingEvidenceV1>,
    pub pricing_policy: raw::PromptPricingPolicyV1,
    pub pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    pub portfolio: PromptPortfolioRequestV1,
    pub exercise: PromptExerciseRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptPlanV1 {
    pub enumerated: EnumeratedPromptCandidatesV1,
    pub priced: PricedPromptCandidatesV1,
    pub portfolio: SelectedPromptPortfolioV1,
    pub exercise: VerifiedPromptExerciseDecisionV1,
}

pub fn build_canonical_prompt_plan_v1(
    registry: &PromptRegistry,
    graph: &KnowledgeGenerationV2,
    verifier: &LearningEvidenceVerifierV1,
    inputs: CanonicalPromptPlanInputsV1,
) -> Result<CanonicalPromptPlanV1, CanonicalPromptError> {
    let enumerated = enumerate_factors_v1(registry, inputs.enumeration)?;
    let priced = price_factors_v1(
        enumerated.clone(),
        &inputs.completeness,
        &inputs.completeness_evidence,
        inputs.pricing_evidence,
        verifier,
        &inputs.pricing_policy,
        inputs.exercise.now_unix_ms,
    )?;
    let portfolio = select_portfolio_v1(
        &priced,
        graph,
        inputs.pair_evidence,
        verifier,
        inputs.portfolio,
        inputs.exercise.now_unix_ms,
    )?;
    let exercise = exercise_v1(registry, graph, verifier, &portfolio, inputs.exercise)?;
    Ok(CanonicalPromptPlanV1 {
        enumerated,
        priced,
        portfolio,
        exercise,
    })
}
