use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::ops::Deref;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::query_relations;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::error::CanonicalPromptError;
use super::error::PromptStaleReasonV1;
use super::error::push_id;
use super::pricing::EvidenceProvenanceV1;
use super::pricing::VerifiedPricedPromptCandidatesV1;
use super::raw;
use super::selection_support::build_candidate_decisions;
use super::selection_support::digest_portfolio_receipt;
use super::selection_support::pair_key;
use super::selection_support::portfolio_audit_digest;
use super::selection_support::selected_verification_digest;
use super::selection_support::validate_constraint_graph;
use super::selection_support::validate_selected_raw;
use super::solver::SolverModel;
use super::solver::apply_solver_outcome;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairUtilityEvidenceV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub pricing_set_digest: Digest32,
    pub state_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub edge_validity_digest: Digest32,
    pub marginal_utility_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub source_support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

impl PromptPairUtilityEvidenceV1 {
    fn bound_support_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.pair-context.v2".to_vec();
        push_id(&mut bytes, &self.left_factor_id);
        push_id(&mut bytes, &self.right_factor_id);
        for digest in [
            self.candidate_set_digest,
            self.registry_snapshot_digest,
            self.objective_digest,
            self.scope_digest,
            self.pricing_set_digest,
            self.graph_generation_digest,
            self.edge_validity_digest,
            self.source_support_audit_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    fn to_raw(&self) -> raw::PromptPairUtilityEvidenceV1 {
        raw::PromptPairUtilityEvidenceV1 {
            left_factor_id: self.left_factor_id.clone(),
            right_factor_id: self.right_factor_id.clone(),
            state_digest: self.state_digest,
            graph_generation_digest: self.graph_generation_digest,
            edge_validity_digest: self.edge_validity_digest,
            marginal_utility_q32: self.marginal_utility_q32,
            confidence_lower_q32: self.confidence_lower_q32,
            confidence_upper_q32: self.confidence_upper_q32,
            support_audit_digest: self.bound_support_digest(),
            evidence: self.evidence.clone(),
        }
    }
}

pub fn pair_utility_evidence_signing_payload_v1(
    evidence: &PromptPairUtilityEvidenceV1,
) -> Vec<u8> {
    raw::pair_utility_evidence_signing_payload_v1(&evidence.to_raw())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPortfolioKindV1 {
    Intervention,
    NoIntervention,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptCandidateDispositionV1 {
    Selected,
    Dominated,
    Superseded,
    UnavailablePricing,
    NonPositiveMarginal,
    OverTokenBudget,
    SelectionLimit,
    HardConflict,
    PrerequisiteUnavailable,
    HeuristicExcluded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateDecisionV1 {
    pub factor_id: StableId,
    pub disposition: PromptCandidateDispositionV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSolverMethodV2 {
    ExactOracleEnumerationV1,
    GreedyWithOneTwoSwapV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSolverTerminationV1 {
    ExactSearchComplete,
    NoImprovingMove,
    EvaluationBudgetExhausted,
    SelectionLimit,
    NoPositivePortfolio,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV2 {
    pub portfolio_kind: PromptPortfolioKindV1,
    pub candidate_decisions: Vec<PromptCandidateDecisionV1>,
    pub graph_generation: u64,
    pub graph_generation_digest: Digest32,
    pub graph_source_snapshot_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub evidence_age_millis: u64,
    pub evidence_valid_until_unix_ms: u64,
    pub graph_valid_until_unix_ms: u64,
    pub solver_method: PromptSolverMethodV2,
    pub solver_rounds: u32,
    pub solver_evaluations: u32,
    pub incumbent_utility_q32: FixedQ32,
    pub upper_bound_utility_q32: FixedQ32,
    pub optimality_gap_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub token_budget: u64,
    pub termination: PromptSolverTerminationV1,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSelectedPromptPortfolioV1 {
    raw: raw::SelectedPromptPortfolioV1,
    pricing_verification_digest: Digest32,
    provenance: EvidenceProvenanceV1,
    graph_source_snapshot_digest: Digest32,
    graph_profile_digest: Digest32,
    graph_valid_until_unix_ms: u64,
    audit: PromptPortfolioAuditV2,
    verification_digest: Digest32,
}

impl Deref for VerifiedSelectedPromptPortfolioV1 {
    type Target = raw::SelectedPromptPortfolioV1;

    fn deref(&self) -> &Self::Target {
        &self.raw
    }
}

impl VerifiedSelectedPromptPortfolioV1 {
    pub fn audit(&self) -> &PromptPortfolioAuditV2 {
        &self.audit
    }

    pub fn provenance(&self) -> &EvidenceProvenanceV1 {
        &self.provenance
    }

    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub fn pricing_verification_digest(&self) -> Digest32 {
        self.pricing_verification_digest
    }

    pub fn graph_source_snapshot_digest(&self) -> Digest32 {
        self.graph_source_snapshot_digest
    }

    pub fn graph_profile_digest(&self) -> Digest32 {
        self.graph_profile_digest
    }

    pub fn graph_valid_until_unix_ms(&self) -> u64 {
        self.graph_valid_until_unix_ms
    }

    pub(crate) fn as_raw(&self) -> &raw::SelectedPromptPortfolioV1 {
        &self.raw
    }

    pub(crate) fn validate_seal(&self) -> Result<(), CanonicalPromptError> {
        validate_selected_raw(&self.raw)?;
        if self.audit.audit_digest
            != portfolio_audit_digest(&self.audit, self.raw.receipt.receipt_digest)
            || self.verification_digest
                != selected_verification_digest(
                    self.raw.receipt.receipt_digest,
                    self.pricing_verification_digest,
                    self.audit.audit_digest,
                    self.provenance.provenance_digest,
                    self.raw.graph_generation_digest,
                )
        {
            return Err(CanonicalPromptError::Corrupt(
                "selected portfolio seal".to_owned(),
            ));
        }
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
pub fn select_portfolio_v1(
    priced: &VerifiedPricedPromptCandidatesV1,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    request: raw::PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelectedPromptPortfolioV1, CanonicalPromptError> {
    if now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    if verifier.trust_digest() != priced.provenance().trust_digest
        || verifier.scope_digest() != priced.provenance().scope_digest
        || verifier.objective_digest() != priced.provenance().objective_digest
        || verifier.authority_epoch() != priced.provenance().authority_epoch
    {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::TrustSnapshot,
        ));
    }
    if now_unix_ms > priced.provenance().valid_until_unix_ms {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::EvidenceExpired,
        ));
    }
    graph
        .validate()
        .map_err(|error| CanonicalPromptError::Corrupt(error.to_string()))?;
    if graph.generation_vector_digest != priced.candidates.generation_vector_digest {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::GenerationVector,
        ));
    }

    let factor_ids = priced
        .rows
        .iter()
        .map(|row| row.binding.factor_id.clone())
        .collect::<Vec<_>>();
    let relation_result = query_relations(
        graph,
        KnowledgeRelationQueryV2 {
            query_id: request.graph_query_id.clone(),
            generation_digest: graph.generation_digest,
            seed_node_ids: factor_ids.clone(),
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
            maximum_edges: super::MAX_CANONICAL_INTERACTION_EDGES,
        },
    )
    .map_err(|error| CanonicalPromptError::Unavailable(error.to_string()))?;
    if relation_result.omitted_count != 0 {
        return Err(CanonicalPromptError::Incomplete(format!(
            "knowledge relation projection omitted {} rows",
            relation_result.omitted_count
        )));
    }

    let known = factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let mut requires = BTreeMap::<StableId, BTreeSet<StableId>>::new();
    let mut conflicts = BTreeSet::<(StableId, StableId)>::new();
    let mut dominated = BTreeSet::<StableId>::new();
    let mut superseded = BTreeSet::<StableId>::new();
    let mut numeric_edges = BTreeMap::<
        (StableId, StableId),
        (Digest32, KnowledgeRelationKindV2),
    >::new();
    let mut graph_valid_until = u64::MAX;
    for edge in &relation_result.edges {
        for support in &edge.supports {
            if let Some(valid_to) = support.valid_to_unix_seconds {
                let millis = u64::try_from(valid_to)
                    .ok()
                    .and_then(|value| value.checked_mul(1_000))
                    .ok_or(CanonicalPromptError::InvalidTime)?;
                graph_valid_until = graph_valid_until.min(millis);
            }
        }
        let left = &edge.identity.source_node_id;
        let right = &edge.identity.target_node_id;
        if !known.contains(left) || !known.contains(right) {
            if edge.identity.relation == KnowledgeRelationKindV2::PromptRequires
                && known.contains(left)
            {
                return Err(CanonicalPromptError::UnsatisfiableConstraintGraph(
                    format!("required factor unavailable: {right}"),
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
                dominated.insert(right.clone());
            }
            KnowledgeRelationKindV2::PromptSupersedes => {
                superseded.insert(right.clone());
            }
            KnowledgeRelationKindV2::PromptComplements
            | KnowledgeRelationKindV2::PromptSubstitutes => {
                let key = pair_key(left, right);
                if numeric_edges
                    .insert(key, (edge.validity_digest, edge.identity.relation.clone()))
                    .is_some()
                {
                    return Err(CanonicalPromptError::Corrupt(
                        "duplicate numeric prompt relation".to_owned(),
                    ));
                }
            }
            _ => {}
        }
    }
    let pruned = dominated
        .union(&superseded)
        .cloned()
        .collect::<BTreeSet<_>>();
    validate_constraint_graph(&known, &requires, &conflicts, &pruned)?;

    let mut raw_pair_evidence = Vec::new();
    let mut pair_values = BTreeMap::<(StableId, StableId), i64>::new();
    let mut seen_pairs = BTreeSet::new();
    let mut evidence_valid_until = priced.provenance().valid_until_unix_ms;
    for evidence in &pair_evidence {
        let key = pair_key(&evidence.left_factor_id, &evidence.right_factor_id);
        let Some((validity_digest, relation_kind)) = numeric_edges.get(&key) else {
            return Err(CanonicalPromptError::EvidenceBinding(
                "pair evidence does not name a current numeric relation".to_owned(),
            ));
        };
        if pruned.contains(&key.0) || pruned.contains(&key.1) {
            continue;
        }
        if !seen_pairs.insert(key.clone())
            || evidence.left_factor_id >= evidence.right_factor_id
            || evidence.candidate_set_digest != priced.candidates.candidates_digest
            || evidence.registry_snapshot_digest
                != priced.candidates.registry_snapshot.snapshot_digest
            || evidence.objective_digest != priced.provenance().objective_digest
            || evidence.scope_digest != priced.provenance().scope_digest
            || evidence.pricing_set_digest != priced.pricing_set_digest
            || evidence.state_digest != priced.candidates.receipt.state_digest
            || evidence.graph_generation_digest != graph.generation_digest
            || evidence.edge_validity_digest != *validity_digest
            || evidence.source_support_audit_digest.is_zero()
            || (relation_kind == &KnowledgeRelationKindV2::PromptComplements
                && evidence.marginal_utility_q32 < FixedQ32::ZERO)
            || (relation_kind == &KnowledgeRelationKindV2::PromptSubstitutes
                && evidence.marginal_utility_q32 > FixedQ32::ZERO)
        {
            return Err(CanonicalPromptError::EvidenceBinding(format!(
                "invalid pair evidence for {}/{}",
                evidence.left_factor_id, evidence.right_factor_id
            )));
        }
        let raw = evidence.to_raw();
        let payload = raw::pair_utility_evidence_signing_payload_v1(&raw);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| CanonicalPromptError::Unavailable(error.to_string()))?;
        if evaluator.controller_id() == &priced.provenance().generator_controller_id
            || evaluator.principal().principal_id
                == priced.provenance().generator_principal_id
        {
            return Err(CanonicalPromptError::EvidenceIndependence(
                "pair evaluator collides with candidate generator".to_owned(),
            ));
        }
        evidence_valid_until = evidence_valid_until.min(evidence.evidence.expires_at);
        pair_values.insert(key, evidence.marginal_utility_q32.raw());
        raw_pair_evidence.push(raw);
    }
    for key in numeric_edges.keys() {
        if pruned.contains(&key.0) || pruned.contains(&key.1) {
            continue;
        }
        if !seen_pairs.contains(key) {
            return Err(CanonicalPromptError::Incomplete(format!(
                "missing pair evidence for {}/{}",
                key.0, key.1
            )));
        }
    }

    let mut filtered = priced.as_raw().clone();
    filtered
        .rows
        .retain(|row| !pruned.contains(&row.binding.factor_id));
    if filtered.rows.is_empty() {
        raw_pair_evidence.clear();
    }
    let mut selected = raw::select_portfolio_v1(
        &filtered,
        graph,
        raw_pair_evidence,
        verifier,
        request.clone(),
        now_unix_ms,
    )
    .map_err(CanonicalPromptError::from)?;

    let model = SolverModel::build(
        &filtered,
        &requires,
        &conflicts,
        &pair_values,
        request.maximum_selected_factors,
        request.token_budget,
    )?;
    let seed = model.mask_for_ids(&selected.receipt.factor_ids)?;
    let outcome = model.solve(seed)?;
    apply_solver_outcome(&mut selected, &filtered, &outcome, graph.generation_digest)?;

    let valid_until = selected
        .receipt
        .valid_until_unix_ms
        .min(evidence_valid_until)
        .min(graph_valid_until);
    if valid_until <= now_unix_ms {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::EvidenceExpired,
        ));
    }
    selected.receipt.valid_until_unix_ms = valid_until;
    selected.receipt.receipt_digest = digest_portfolio_receipt(
        &selected.receipt.portfolio_id,
        selected.receipt.candidate_set_digest,
        &selected.receipt.factor_ids,
        selected.receipt.interaction_digest,
        selected.receipt.expected_utility_q32,
        selected.receipt.total_token_upper_bound,
        selected.receipt.valid_until_unix_ms,
        selected.pricing_set_digest,
        selected.graph_generation_digest,
    );

    let decisions = build_candidate_decisions(
        priced,
        &selected.receipt.factor_ids,
        &dominated,
        &superseded,
        &conflicts,
        &requires,
        request.maximum_selected_factors,
        request.token_budget,
    );
    let upper = FixedQ32::from_raw(outcome.upper_bound_raw);
    let incumbent = FixedQ32::from_raw(outcome.utility_raw);
    let gap = FixedQ32::from_raw(outcome.upper_bound_raw.saturating_sub(outcome.utility_raw));
    let mut audit = PromptPortfolioAuditV2 {
        portfolio_kind: if selected.receipt.factor_ids.is_empty() {
            PromptPortfolioKindV1::NoIntervention
        } else {
            PromptPortfolioKindV1::Intervention
        },
        candidate_decisions: decisions,
        graph_generation: graph.generation.get(),
        graph_generation_digest: graph.generation_digest,
        graph_source_snapshot_digest: graph.source_snapshot_digest,
        graph_profile_digest: graph.graph_profile_digest,
        evidence_age_millis: now_unix_ms.saturating_sub(priced.provenance().issued_at_unix_ms),
        evidence_valid_until_unix_ms: evidence_valid_until,
        graph_valid_until_unix_ms: graph_valid_until,
        solver_method: outcome.method,
        solver_rounds: outcome.rounds,
        solver_evaluations: outcome.evaluations,
        incumbent_utility_q32: incumbent,
        upper_bound_utility_q32: upper,
        optimality_gap_q32: gap,
        total_token_upper_bound: selected.receipt.total_token_upper_bound,
        token_budget: request.token_budget,
        termination: outcome.termination,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = portfolio_audit_digest(&audit, selected.receipt.receipt_digest);
    validate_selected_raw(&selected)?;
    let verification_digest = selected_verification_digest(
        selected.receipt.receipt_digest,
        priced.verification_digest(),
        audit.audit_digest,
        priced.provenance().provenance_digest,
        graph.generation_digest,
    );
    let result = VerifiedSelectedPromptPortfolioV1 {
        raw: selected,
        pricing_verification_digest: priced.verification_digest(),
        provenance: priced.provenance().clone(),
        graph_source_snapshot_digest: graph.source_snapshot_digest,
        graph_profile_digest: graph.graph_profile_digest,
        graph_valid_until_unix_ms: graph_valid_until,
        audit,
        verification_digest,
    };
    result.validate_seal()?;
    Ok(result)
}
