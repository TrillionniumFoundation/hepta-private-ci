use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_prompt_optimizer::local_shadow::{
    InsufficientEvidence, InvalidInput, LOCAL_NO_INTERVENTION_ID, LocalHardConstraint,
    LocalNoInterventionBaseline, LocalPairInteraction, LocalShadowError, LocalShadowInput,
    MAX_HARD_CONSTRAINT_EDGES, MAX_SELECTED_FACTORS, calculate_local_shadow,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(index: usize, gain: i64, cost: u64) -> PromptCandidate {
    let candidate_id = format!("candidate:{index:03}");
    PromptCandidate {
        candidate_id: id(&candidate_id),
        factor_id: id(&format!("factor:{index:03}")),
        realization_id: id(&format!("realization:{index:03}")),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost,
        registry_digest: digest("registry"),
        support_digest: digest(&format!("support:{index}")),
    }
}

fn input(factors: Vec<PromptCandidate>) -> LocalShadowInput {
    LocalShadowInput {
        decision_id: id("decision:shadow-regression"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        registry_snapshot_digest: digest("registry"),
        token_budget: 10_000,
        maximum_selected_factors: 1,
        no_intervention: LocalNoInterventionBaseline {
            arm_id: id(LOCAL_NO_INTERVENTION_ID),
            registry_digest: digest("registry"),
            support_reference_digest: digest("baseline"),
        },
        factor_candidates: factors,
        interaction_edges: Vec::new(),
        hard_constraints: Vec::new(),
    }
}

#[test]
fn local_baseline_cannot_alias_a_factor_candidate() {
    let mut duplicate = factor(0, 1, 1);
    duplicate.candidate_id = id(LOCAL_NO_INTERVENTION_ID);
    assert_eq!(
        calculate_local_shadow(input(vec![duplicate])),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::DuplicateCandidate(LOCAL_NO_INTERVENTION_ID.to_string()),
        ))
    );
}

#[test]
fn selected_and_constraint_limits_keep_distinct_error_classes() {
    let mut selected = input(vec![factor(0, 1, 1)]);
    selected.maximum_selected_factors = MAX_SELECTED_FACTORS + 1;
    assert_eq!(
        calculate_local_shadow(selected),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::SelectedFactorLimitExceeded,
        ))
    );

    let mut constrained = input(vec![factor(0, 2, 1), factor(1, 1, 1)]);
    constrained.hard_constraints = (0..(MAX_HARD_CONSTRAINT_EDGES + 1))
        .map(|index| LocalHardConstraint::Requires {
            candidate_id: id("candidate:000"),
            prerequisite_candidate_id: id("candidate:001"),
            support_reference_digest: digest(&format!("constraint:{index}")),
        })
        .collect();
    assert_eq!(
        calculate_local_shadow(constrained),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::HardConstraintLimitExceeded,
        ))
    );
}

#[test]
fn unknown_prerequisite_is_rejected_instead_of_ignored() {
    let mut value = input(vec![factor(0, 100, 1)]);
    value.hard_constraints.push(LocalHardConstraint::Requires {
        candidate_id: id("candidate:000"),
        prerequisite_candidate_id: id("candidate:missing"),
        support_reference_digest: digest("requires"),
    });
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::UnknownHardConstraintEndpoint("candidate:missing".to_string()),
        ))
    );
}

#[test]
fn factor_and_realization_aliases_are_rejected() {
    let first = factor(0, 1, 1);
    let mut duplicate_factor = factor(1, 1, 1);
    duplicate_factor.factor_id = first.factor_id.clone();
    assert_eq!(
        calculate_local_shadow(input(vec![first, duplicate_factor])),
        Err(LocalShadowError::InvalidInput(InvalidInput::DuplicateFactor(
            "factor:000".to_string(),
        )))
    );

    let first = factor(0, 1, 1);
    let mut duplicate_realization = factor(1, 1, 1);
    duplicate_realization.realization_id = first.realization_id.clone();
    assert_eq!(
        calculate_local_shadow(input(vec![first, duplicate_realization])),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::DuplicateRealization("realization:000".to_string()),
        ))
    );
}

#[test]
fn unadmitted_illegal_and_zero_cost_factors_fail_closed() {
    let mut unadmitted = factor(0, 1, 1);
    unadmitted.admitted = false;
    assert_eq!(
        calculate_local_shadow(input(vec![unadmitted])),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::UnadmittedFactor("candidate:000".to_string()),
        ))
    );

    let mut illegal = factor(0, 1, 1);
    illegal.legal = false;
    assert_eq!(
        calculate_local_shadow(input(vec![illegal])),
        Err(LocalShadowError::InvalidInput(InvalidInput::IllegalFactor(
            "candidate:000".to_string(),
        )))
    );

    assert_eq!(
        calculate_local_shadow(input(vec![factor(0, 1, 0)])),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::InvalidFactorCost("candidate:000".to_string()),
        ))
    );
}

#[test]
fn empty_candidate_and_interaction_support_fail_as_insufficient_evidence() {
    let mut candidate = factor(0, 1, 1);
    candidate.support_digest = Digest32::ZERO;
    assert_eq!(
        calculate_local_shadow(input(vec![candidate])),
        Err(LocalShadowError::InsufficientEvidence(
            InsufficientEvidence::EmptySupportReference("factor candidate"),
        ))
    );

    let mut value = input(vec![factor(0, 2, 1), factor(1, 1, 1)]);
    value.maximum_selected_factors = 2;
    value.interaction_edges.push(LocalPairInteraction {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        caller_supplied_marginal_gain: FixedQ32::ZERO,
        support_reference_digest: Digest32::ZERO,
    });
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InsufficientEvidence(
            InsufficientEvidence::EmptySupportReference("pair interaction"),
        ))
    );
}

#[test]
fn hard_constraint_support_is_digest_bound_and_duplicate_constraints_fail_closed() {
    let mut first = input(vec![factor(0, 2, 1), factor(1, 1, 1)]);
    first.maximum_selected_factors = 2;
    first.hard_constraints.push(LocalHardConstraint::Conflict {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        support_reference_digest: digest("first-conflict-support"),
    });
    let mut second = first.clone();
    let LocalHardConstraint::Conflict {
        support_reference_digest,
        ..
    } = &mut second.hard_constraints[0]
    else {
        panic!("test constraint must be conflict");
    };
    *support_reference_digest = digest("second-conflict-support");

    let Ok(first_proposal) = calculate_local_shadow(first) else {
        panic!("first proposal must be valid");
    };
    let Ok(second_proposal) = calculate_local_shadow(second) else {
        panic!("second proposal must be valid");
    };
    assert_eq!(first_proposal.selections, second_proposal.selections);
    assert_ne!(
        first_proposal.hard_constraint_digest,
        second_proposal.hard_constraint_digest
    );
    assert_ne!(first_proposal.proposal_digest, second_proposal.proposal_digest);

    let mut duplicate = input(vec![factor(0, 2, 1), factor(1, 1, 1)]);
    duplicate.hard_constraints = vec![
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: digest("one"),
        },
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: digest("two"),
        },
    ];
    assert_eq!(
        calculate_local_shadow(duplicate),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::DuplicateHardConstraint(
                "conflict",
                "candidate:000".to_string(),
                "candidate:001".to_string(),
            ),
        ))
    );
}

#[test]
fn duplicate_interaction_edges_fail_closed() {
    let mut value = input(vec![factor(0, 2, 1), factor(1, 1, 1)]);
    value.interaction_edges = vec![
        LocalPairInteraction {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            caller_supplied_marginal_gain: FixedQ32::ZERO,
            support_reference_digest: digest("one"),
        },
        LocalPairInteraction {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            caller_supplied_marginal_gain: FixedQ32::ZERO,
            support_reference_digest: digest("two"),
        },
    ];
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::DuplicateInteractionEdge(
                "candidate:000".to_string(),
                "candidate:001".to_string(),
            ),
        ))
    );
}
