use super::*;
use codex_hepta_types::StableId;
use std::collections::{BTreeMap, BTreeSet};

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
        (
            input.no_intervention.registry_digest,
            "no-intervention registry",
        ),
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
    validate_interactions(input, &candidate_ids)?;
    validate_hard_constraints(input, &candidate_ids)?;
    validate_constraint_satisfiability(input)?;
    Ok(total_candidate_count)
}

fn validate_interactions(
    input: &LocalShadowInput,
    candidate_ids: &BTreeSet<StableId>,
) -> Result<(), LocalShadowError> {
    let mut pairs = BTreeSet::new();
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
        if !pairs.insert((&edge.left_candidate_id, &edge.right_candidate_id)) {
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
    Ok(())
}

fn validate_hard_constraints(
    input: &LocalShadowInput,
    candidate_ids: &BTreeSet<StableId>,
) -> Result<(), LocalShadowError> {
    let mut keys = BTreeSet::new();
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
        let (name, support) = match constraint {
            LocalHardConstraint::Conflict {
                support_reference_digest,
                ..
            } => ("conflict", support_reference_digest),
            LocalHardConstraint::Requires {
                support_reference_digest,
                ..
            } => ("requires", support_reference_digest),
        };
        if support.is_zero() {
            return Err(insufficient(InsufficientEvidence::EmptySupportReference(
                "hard constraint",
            )));
        }
        if !keys.insert((kind, left, right)) {
            return Err(invalid(InvalidInput::DuplicateHardConstraint(
                name,
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

fn validate_constraint_satisfiability(input: &LocalShadowInput) -> Result<(), LocalShadowError> {
    let mut requires: BTreeMap<StableId, Vec<StableId>> = BTreeMap::new();
    let mut conflicts = BTreeSet::new();
    for constraint in &input.hard_constraints {
        match constraint {
            LocalHardConstraint::Requires {
                candidate_id,
                prerequisite_candidate_id,
                ..
            } => requires
                .entry(candidate_id.clone())
                .or_default()
                .push(prerequisite_candidate_id.clone()),
            LocalHardConstraint::Conflict {
                left_candidate_id,
                right_candidate_id,
                ..
            } => {
                conflicts.insert((left_candidate_id.clone(), right_candidate_id.clone()));
            }
        }
    }
    for prerequisites in requires.values_mut() {
        prerequisites.sort();
    }
    for candidate in &input.factor_candidates {
        let mut visiting = BTreeSet::new();
        let mut closure = BTreeSet::new();
        collect_requires(
            &candidate.candidate_id,
            &requires,
            &mut visiting,
            &mut closure,
        )?;
        closure.insert(candidate.candidate_id.clone());
        for (left, right) in &conflicts {
            if closure.contains(left) && closure.contains(right) {
                return Err(invalid(InvalidInput::UnsatisfiableConstraintGraph(
                    candidate.candidate_id.to_string(),
                )));
            }
        }
    }
    Ok(())
}
fn collect_requires(
    node: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
    visiting: &mut BTreeSet<StableId>,
    closure: &mut BTreeSet<StableId>,
) -> Result<(), LocalShadowError> {
    if closure.contains(node) {
        return Ok(());
    }
    if !visiting.insert(node.clone()) {
        return Err(invalid(InvalidInput::RequiresCycle(node.to_string())));
    }
    if let Some(prereqs) = requires.get(node) {
        for prereq in prereqs {
            collect_requires(prereq, requires, visiting, closure)?;
            closure.insert(prereq.clone());
        }
    }
    visiting.remove(node);
    closure.insert(node.clone());
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
