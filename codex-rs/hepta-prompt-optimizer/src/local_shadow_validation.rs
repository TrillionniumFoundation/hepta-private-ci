use std::collections::BTreeSet;

use codex_hepta_types::StableId;

use super::ArithmeticInvariant;
use super::InsufficientEvidence;
use super::IntegrityMismatch;
use super::InvalidInput;
use super::LOCAL_MAX_TOKEN_BUDGET;
use super::LOCAL_NO_INTERVENTION_ID;
use super::LocalHardConstraint;
use super::LocalShadowError;
use super::LocalShadowInput;
use super::MAX_HARD_CONSTRAINT_EDGES;
use super::MAX_INTERACTION_EDGES;
use super::MAX_SELECTED_FACTORS;
use super::MAX_TOTAL_CANDIDATES;
use super::arithmetic;
use super::insufficient;
use super::integrity;
use super::invalid;

pub(super) fn validate_input_structure(input: &LocalShadowInput) -> Result<u32, LocalShadowError> {
    let total_candidate_count = input
        .factor_candidates
        .len()
        .checked_add(1)
        .ok_or(arithmetic(ArithmeticInvariant::CandidateCount))?;
    if total_candidate_count > MAX_TOTAL_CANDIDATES {
        return Err(invalid(InvalidInput::TotalCandidateLimitExceeded));
    }
    let total_candidate_count = u32::try_from(total_candidate_count)
        .map_err(|_| arithmetic(ArithmeticInvariant::CandidateCount))?;
    if input.maximum_selected_factors > MAX_SELECTED_FACTORS {
        return Err(invalid(InvalidInput::SelectedFactorLimitExceeded));
    }
    if input.interaction_edges.len() > MAX_INTERACTION_EDGES {
        return Err(invalid(InvalidInput::InteractionEdgeLimitExceeded));
    }
    if input.hard_constraints.len() > MAX_HARD_CONSTRAINT_EDGES {
        return Err(invalid(InvalidInput::HardConstraintLimitExceeded));
    }
    if input.token_budget > LOCAL_MAX_TOKEN_BUDGET {
        return Err(invalid(InvalidInput::TokenBudgetLimitExceeded));
    }
    if input.decision_id.as_str().is_empty() {
        return Err(invalid(InvalidInput::EmptyIdentifier("decision")));
    }
    for (digest, label) in [
        (input.objective_digest, "objective"),
        (input.state_digest, "state"),
        (input.registry_snapshot_digest, "registry snapshot"),
        (input.no_intervention.registry_digest, "no-intervention registry"),
    ] {
        if digest.is_zero() {
            return Err(invalid(InvalidInput::EmptyDigest(label)));
        }
    }
    if input.no_intervention.arm_id.as_str() != LOCAL_NO_INTERVENTION_ID {
        return Err(invalid(InvalidInput::InvalidNoInterventionIdentity(
            input.no_intervention.arm_id.to_string(),
        )));
    }
    if input.no_intervention.support_reference_digest.is_zero() {
        return Err(insufficient(InsufficientEvidence::EmptySupportReference(
            "no-intervention baseline",
        )));
    }
    if input.no_intervention.registry_digest != input.registry_snapshot_digest {
        return Err(integrity(IntegrityMismatch::RegistrySnapshot(
            input.no_intervention.arm_id.to_string(),
        )));
    }

    let mut candidate_ids = BTreeSet::new();
    let mut factor_ids = BTreeSet::new();
    let mut realization_ids = BTreeSet::new();
    candidate_ids.insert(input.no_intervention.arm_id.clone());
    for candidate in &input.factor_candidates {
        for (identifier, label) in [
            (&candidate.candidate_id, "factor candidate"),
            (&candidate.factor_id, "factor"),
            (&candidate.realization_id, "realization"),
        ] {
            if identifier.as_str().is_empty() {
                return Err(invalid(InvalidInput::EmptyIdentifier(label)));
            }
        }
        if !candidate_ids.insert(candidate.candidate_id.clone()) {
            return Err(invalid(InvalidInput::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            )));
        }
        if !factor_ids.insert(candidate.factor_id.clone()) {
            return Err(invalid(InvalidInput::DuplicateFactor(
                candidate.factor_id.to_string(),
            )));
        }
        if !realization_ids.insert(candidate.realization_id.clone()) {
            return Err(invalid(InvalidInput::DuplicateRealization(
                candidate.realization_id.to_string(),
            )));
        }
        if candidate.registry_digest != input.registry_snapshot_digest {
            return Err(integrity(IntegrityMismatch::RegistrySnapshot(
                candidate.candidate_id.to_string(),
            )));
        }
        if candidate.support_digest.is_zero() {
            return Err(insufficient(InsufficientEvidence::EmptySupportReference(
                "factor candidate",
            )));
        }
        if !candidate.admitted {
            return Err(invalid(InvalidInput::UnadmittedFactor(
                candidate.candidate_id.to_string(),
            )));
        }
        if !candidate.legal {
            return Err(invalid(InvalidInput::IllegalFactor(
                candidate.candidate_id.to_string(),
            )));
        }
        if candidate.cost == 0 {
            return Err(invalid(InvalidInput::InvalidFactorCost(
                candidate.candidate_id.to_string(),
            )));
        }
    }
    if input
        .factor_candidates
        .windows(2)
        .any(|pair| pair[0].candidate_id >= pair[1].candidate_id)
    {
        return Err(invalid(InvalidInput::NonCanonicalCandidateOrder));
    }

    let interaction_pairs = validate_interactions(input, &candidate_ids)?;
    validate_hard_constraints(input, &candidate_ids)?;
    require_complete_pair_interactions(input, &interaction_pairs)?;
    Ok(total_candidate_count)
}

fn validate_interactions<'a>(
    input: &'a LocalShadowInput,
    candidate_ids: &BTreeSet<StableId>,
) -> Result<BTreeSet<(&'a StableId, &'a StableId)>, LocalShadowError> {
    let mut interaction_pairs = BTreeSet::new();
    for edge in &input.interaction_edges {
        if edge.left_candidate_id >= edge.right_candidate_id {
            return Err(invalid(InvalidInput::InvalidInteractionEndpoints));
        }
        for endpoint in [&edge.left_candidate_id, &edge.right_candidate_id] {
            if endpoint.as_str() == input.no_intervention.arm_id.as_str()
                || !candidate_ids.contains(endpoint)
            {
                return Err(invalid(InvalidInput::UnknownInteractionEndpoint(
                    endpoint.to_string(),
                )));
            }
        }
        if edge.support_reference_digest.is_zero() {
            return Err(insufficient(InsufficientEvidence::EmptySupportReference(
                "pair interaction",
            )));
        }
        if !interaction_pairs.insert((&edge.left_candidate_id, &edge.right_candidate_id)) {
            return Err(invalid(InvalidInput::DuplicateInteractionEdge(
                edge.left_candidate_id.to_string(),
                edge.right_candidate_id.to_string(),
            )));
        }
    }
    if input.interaction_edges.windows(2).any(|pair| {
        (&pair[0].left_candidate_id, &pair[0].right_candidate_id)
            >= (&pair[1].left_candidate_id, &pair[1].right_candidate_id)
    }) {
        return Err(invalid(InvalidInput::NonCanonicalInteractionOrder));
    }
    Ok(interaction_pairs)
}

fn validate_hard_constraints(
    input: &LocalShadowInput,
    candidate_ids: &BTreeSet<StableId>,
) -> Result<(), LocalShadowError> {
    let mut constraint_keys = BTreeSet::new();
    for constraint in &input.hard_constraints {
        let (kind, left, right) = hard_constraint_key(constraint);
        if left == right
            || (matches!(constraint, LocalHardConstraint::Conflict { .. }) && left > right)
        {
            return Err(invalid(InvalidInput::InvalidHardConstraintEndpoints));
        }
        for endpoint in [left, right] {
            if endpoint.as_str() == input.no_intervention.arm_id.as_str()
                || !candidate_ids.contains(endpoint)
            {
                return Err(invalid(InvalidInput::UnknownHardConstraintEndpoint(
                    endpoint.to_string(),
                )));
            }
        }
        let (constraint_name, support_reference_digest) = match constraint {
            LocalHardConstraint::Conflict {
                support_reference_digest,
                ..
            } => ("conflict", support_reference_digest),
            LocalHardConstraint::Requires {
                support_reference_digest,
                ..
            } => ("requires", support_reference_digest),
        };
        if support_reference_digest.is_zero() {
            return Err(insufficient(InsufficientEvidence::EmptySupportReference(
                "hard constraint",
            )));
        }
        if !constraint_keys.insert((kind, left, right)) {
            return Err(invalid(InvalidInput::DuplicateHardConstraint(
                constraint_name,
                left.to_string(),
                right.to_string(),
            )));
        }
    }
    if input
        .hard_constraints
        .windows(2)
        .any(|pair| hard_constraint_key(&pair[0]) >= hard_constraint_key(&pair[1]))
    {
        return Err(invalid(InvalidInput::NonCanonicalHardConstraintOrder));
    }
    Ok(())
}

fn require_complete_pair_interactions(
    input: &LocalShadowInput,
    interaction_pairs: &BTreeSet<(&StableId, &StableId)>,
) -> Result<(), LocalShadowError> {
    if input.maximum_selected_factors <= 1 {
        return Ok(());
    }
    for (left_index, left) in input.factor_candidates.iter().enumerate() {
        for right in input.factor_candidates.iter().skip(left_index + 1) {
            if !interaction_pairs.contains(&(&left.candidate_id, &right.candidate_id)) {
                return Err(insufficient(InsufficientEvidence::MissingPairInteraction(
                    left.candidate_id.to_string(),
                    right.candidate_id.to_string(),
                )));
            }
        }
    }
    Ok(())
}

fn hard_constraint_key(constraint: &LocalHardConstraint) -> (u8, &StableId, &StableId) {
    match constraint {
        LocalHardConstraint::Conflict {
            left_candidate_id,
            right_candidate_id,
            ..
        } => (0, left_candidate_id, right_candidate_id),
        LocalHardConstraint::Requires {
            candidate_id,
            prerequisite_candidate_id,
            ..
        } => (1, candidate_id, prerequisite_candidate_id),
    }
}
