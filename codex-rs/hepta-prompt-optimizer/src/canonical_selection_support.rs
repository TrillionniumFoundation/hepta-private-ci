use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::error::CanonicalPromptError;
use super::error::push_id;
use super::error::push_ids;
use super::pricing::VerifiedPricedPromptCandidatesV1;
use super::raw;
use super::selection::PromptCandidateDecisionV1;
use super::selection::PromptCandidateDispositionV1;
use super::selection::PromptPortfolioAuditV2;
use super::selection::PromptPortfolioKindV1;
use super::selection::PromptSolverMethodV2;
use super::selection::PromptSolverTerminationV1;

pub(super) fn validate_constraint_graph(
    known: &BTreeSet<StableId>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    pruned: &BTreeSet<StableId>,
) -> Result<(), CanonicalPromptError> {
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
            return Err(CanonicalPromptError::UnsatisfiableConstraintGraph(
                format!("requires cycle at {node}"),
            ));
        }
        if let Some(children) = requires.get(node) {
            for child in children {
                visit(child, requires, visiting, done)?;
            }
        }
        visiting.remove(node);
        done.insert(node.clone());
        Ok(())
    }

    for factor in known {
        if pruned.contains(factor) {
            continue;
        }
        let mut visiting = BTreeSet::new();
        let mut closure = BTreeSet::new();
        visit(factor, requires, &mut visiting, &mut closure)?;
        if let Some(missing) = closure
            .iter()
            .find(|id| !known.contains(*id) || pruned.contains(*id))
        {
            return Err(CanonicalPromptError::UnsatisfiableConstraintGraph(
                format!("{factor} requires unavailable {missing}"),
            ));
        }
        if conflicts
            .iter()
            .any(|(left, right)| closure.contains(left) && closure.contains(right))
        {
            return Err(CanonicalPromptError::UnsatisfiableConstraintGraph(
                format!("conflict inside prerequisite closure for {factor}"),
            ));
        }
    }
    Ok(())
}

pub(super) fn validate_selected_raw(
    selected: &raw::SelectedPromptPortfolioV1,
) -> Result<(), CanonicalPromptError> {
    if selected.receipt.authority.grants_any()
        || selected.receipt.factor_ids.len() != selected.selected.len()
        || selected.receipt.factor_ids.len() > super::MAX_CANONICAL_SELECTED_FACTORS
        || selected.model_tuple.digest() != selected.model_tuple_digest
        || selected.receipt.valid_until_unix_ms == 0
        || selected.receipt.receipt_digest
            != digest_portfolio_receipt(
                &selected.receipt.portfolio_id,
                selected.receipt.candidate_set_digest,
                &selected.receipt.factor_ids,
                selected.receipt.interaction_digest,
                selected.receipt.expected_utility_q32,
                selected.receipt.total_token_upper_bound,
                selected.receipt.valid_until_unix_ms,
                selected.pricing_set_digest,
                selected.graph_generation_digest,
            )
    {
        return Err(CanonicalPromptError::Corrupt(
            "selected portfolio receipt".to_owned(),
        ));
    }
    let mut previous: Option<&StableId> = None;
    let mut token_total = 0_u64;
    for (factor_id, binding) in selected.receipt.factor_ids.iter().zip(&selected.selected) {
        if factor_id != &binding.factor_id
            || binding.factor_id != binding.realization.factor_id
            || binding.binding_digest != binding.realization.digest()
            || previous.is_some_and(|value| value >= factor_id)
        {
            return Err(CanonicalPromptError::Corrupt(
                "selected portfolio identity/order/binding".to_owned(),
            ));
        }
        token_total = token_total
            .checked_add(u64::from(binding.realization.token_cost))
            .ok_or(CanonicalPromptError::Arithmetic)?;
        previous = Some(factor_id);
    }
    if u32::try_from(token_total).map_err(|_| CanonicalPromptError::TokenBudgetLimit)?
        != selected.receipt.total_token_upper_bound
    {
        return Err(CanonicalPromptError::Corrupt(
            "selected portfolio token accounting".to_owned(),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) fn build_candidate_decisions(
    priced: &VerifiedPricedPromptCandidatesV1,
    selected: &[StableId],
    dominated: &BTreeSet<StableId>,
    superseded: &BTreeSet<StableId>,
    conflicts: &BTreeSet<(StableId, StableId)>,
    requires: &BTreeMap<StableId, BTreeSet<StableId>>,
    maximum_selected: usize,
    token_budget: u64,
) -> Vec<PromptCandidateDecisionV1> {
    let selected_set = selected.iter().cloned().collect::<BTreeSet<_>>();
    priced
        .rows
        .iter()
        .map(|row| {
            let disposition = if selected_set.contains(&row.binding.factor_id) {
                PromptCandidateDispositionV1::Selected
            } else if dominated.contains(&row.binding.factor_id) {
                PromptCandidateDispositionV1::Dominated
            } else if superseded.contains(&row.binding.factor_id) {
                PromptCandidateDispositionV1::Superseded
            } else if requires
                .get(&row.binding.factor_id)
                .is_some_and(|required| required.iter().any(|id| !selected_set.contains(id)))
            {
                PromptCandidateDispositionV1::PrerequisiteUnavailable
            } else if conflicts.iter().any(|(left, right)| {
                (&row.binding.factor_id == left && selected_set.contains(right))
                    || (&row.binding.factor_id == right && selected_set.contains(left))
            }) {
                PromptCandidateDispositionV1::HardConflict
            } else if row.net_utility_q32 <= FixedQ32::ZERO {
                PromptCandidateDispositionV1::NonPositiveMarginal
            } else if u64::from(row.pricing.token_cost) > token_budget {
                PromptCandidateDispositionV1::OverTokenBudget
            } else if selected.len() >= maximum_selected {
                PromptCandidateDispositionV1::SelectionLimit
            } else {
                PromptCandidateDispositionV1::HeuristicExcluded
            };
            PromptCandidateDecisionV1 {
                factor_id: row.binding.factor_id.clone(),
                disposition,
            }
        })
        .collect()
}

pub(super) fn pair_key(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn digest_portfolio_receipt(
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

pub(super) fn portfolio_audit_digest(
    audit: &PromptPortfolioAuditV2,
    portfolio_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-audit.v2".to_vec();
    bytes.extend_from_slice(portfolio_receipt_digest.as_array());
    bytes.push(match audit.portfolio_kind {
        PromptPortfolioKindV1::Intervention => 0,
        PromptPortfolioKindV1::NoIntervention => 1,
    });
    for decision in &audit.candidate_decisions {
        push_id(&mut bytes, &decision.factor_id);
        bytes.push(match decision.disposition {
            PromptCandidateDispositionV1::Selected => 0,
            PromptCandidateDispositionV1::Dominated => 1,
            PromptCandidateDispositionV1::Superseded => 2,
            PromptCandidateDispositionV1::UnavailablePricing => 3,
            PromptCandidateDispositionV1::NonPositiveMarginal => 4,
            PromptCandidateDispositionV1::OverTokenBudget => 5,
            PromptCandidateDispositionV1::SelectionLimit => 6,
            PromptCandidateDispositionV1::HardConflict => 7,
            PromptCandidateDispositionV1::PrerequisiteUnavailable => 8,
            PromptCandidateDispositionV1::HeuristicExcluded => 9,
        });
    }
    bytes.extend_from_slice(&audit.graph_generation.to_be_bytes());
    for digest in [
        audit.graph_generation_digest,
        audit.graph_source_snapshot_digest,
        audit.graph_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        audit.evidence_age_millis,
        audit.evidence_valid_until_unix_ms,
        audit.graph_valid_until_unix_ms,
        u64::from(audit.solver_rounds),
        u64::from(audit.solver_evaluations),
        u64::from(audit.total_token_upper_bound),
        audit.token_budget,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    for value in [
        audit.incumbent_utility_q32,
        audit.upper_bound_utility_q32,
        audit.optimality_gap_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.push(match audit.solver_method {
        PromptSolverMethodV2::ExactOracleEnumerationV1 => 0,
        PromptSolverMethodV2::GreedyWithOneTwoSwapV1 => 1,
    });
    bytes.push(match audit.termination {
        PromptSolverTerminationV1::ExactSearchComplete => 0,
        PromptSolverTerminationV1::NoImprovingMove => 1,
        PromptSolverTerminationV1::EvaluationBudgetExhausted => 2,
        PromptSolverTerminationV1::SelectionLimit => 3,
        PromptSolverTerminationV1::NoPositivePortfolio => 4,
    });
    Digest32::of_bytes(&bytes)
}

pub(super) fn selected_verification_digest(
    portfolio_digest: Digest32,
    pricing_verification_digest: Digest32,
    audit_digest: Digest32,
    provenance_digest: Digest32,
    graph_generation_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-portfolio.v2".to_vec();
    for digest in [
        portfolio_digest,
        pricing_verification_digest,
        audit_digest,
        provenance_digest,
        graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}
