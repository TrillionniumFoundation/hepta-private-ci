use super::*;
use crate::{OptimizationRequest, optimize};

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("valid id")
    };
    value
}
fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn factor(index: usize, gain: i64, cost: u64) -> PromptCandidate {
    let name = format!("candidate:{index:03}");
    PromptCandidate {
        candidate_id: id(&name),
        factor_id: id(&format!("factor:{index:03}")),
        realization_id: id(&format!("realization:{index:03}")),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost,
        registry_digest: d("registry"),
        support_digest: d(&format!("support:{index}")),
    }
}
fn input(factors: Vec<PromptCandidate>) -> LocalShadowInput {
    LocalShadowInput {
        decision_id: id("decision:shadow"),
        objective_digest: d("objective"),
        state_digest: d("state"),
        registry_snapshot_digest: d("registry"),
        token_budget: 10_000,
        maximum_selected_factors: 1,
        no_intervention: LocalNoInterventionBaseline {
            arm_id: id(LOCAL_NO_INTERVENTION_ID),
            registry_digest: d("registry"),
            support_reference_digest: d("baseline"),
        },
        factor_candidates: factors,
        interaction_edges: Vec::new(),
        hard_constraints: Vec::new(),
    }
}
fn edge(left: &str, right: &str, gain: i64) -> LocalPairInteraction {
    LocalPairInteraction {
        left_candidate_id: id(left),
        right_candidate_id: id(right),
        caller_supplied_marginal_gain: FixedQ32::from_raw(gain),
        support_reference_digest: d(&format!("edge:{left}:{right}")),
    }
}

#[test]
fn legacy_v1_surface_keeps_its_original_selection_limit() {
    let candidates = (0..17).map(|i| factor(i, 1, 1)).collect();
    let request = OptimizationRequest {
        decision_id: id("decision:legacy"),
        objective_digest: d("objective"),
        registry_snapshot_digest: d("registry"),
        budget: 17,
        maximum_selected: 17,
        candidates,
    };
    let Ok(result) = optimize(request) else {
        panic!("legacy")
    };
    assert_eq!(result.selected.len(), 17);
}

#[test]
fn total_candidate_limit_includes_baseline() {
    let factors = (0..MAX_FACTOR_CANDIDATES)
        .map(|i| factor(i, 1, 1))
        .collect();
    let Ok(proposal) = calculate_local_shadow(input(factors)) else {
        panic!("shadow")
    };
    assert_eq!(proposal.total_candidate_count, 128);
    let factors = (0..MAX_TOTAL_CANDIDATES).map(|i| factor(i, 1, 1)).collect();
    assert_eq!(
        calculate_local_shadow(input(factors)),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::TotalCandidateLimitExceeded
        ))
    );
}

#[test]
fn baseline_cannot_impersonate_canonical_abstain() {
    let mut value = input(vec![factor(0, 1, 1)]);
    value.no_intervention.arm_id = id("abstain");
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::InvalidNoInterventionIdentity("abstain".to_string())
        ))
    );
}

#[test]
fn result_discloses_shadow_audit_gaps_and_sparse_policy() {
    let Ok(proposal) = calculate_local_shadow(input(vec![factor(0, 7, 2)])) else {
        panic!("shadow")
    };
    assert_eq!(
        proposal.candidate_completeness,
        LocalCandidateCompleteness::UnknownCallerSupplied
    );
    assert_eq!(
        proposal.pricing_provenance,
        LocalPricingProvenance::CallerSuppliedOpaque
    );
    assert_eq!(
        proposal.model_compatibility,
        LocalModelCompatibility::Unverified
    );
    assert_eq!(proposal.exercise_boundary, LocalExerciseBoundary::Unbound);
    assert_eq!(
        proposal.interaction_policy,
        LocalUnknownInteractionPolicy::MissingAsZero
    );
    assert_eq!(
        proposal.selection_method,
        LocalSelectionMethod::PrerequisiteClosureGreedyDensityV2
    );
    assert_eq!(proposal.decisions.len(), 1);
    assert!(!proposal.authority().grants_any());
}

#[test]
fn sparse_graph_supports_full_factor_capacity_in_multi_select_mode() {
    let factors = (0..MAX_FACTOR_CANDIDATES)
        .map(|i| factor(i, 1, 1))
        .collect();
    let mut value = input(factors);
    value.maximum_selected_factors = MAX_SELECTED_FACTORS;
    value.token_budget = MAX_SELECTED_FACTORS as u64;
    let Ok(proposal) = calculate_local_shadow(value) else {
        panic!("sparse shadow")
    };
    assert_eq!(proposal.selections.len(), MAX_SELECTED_FACTORS);
    assert!(proposal.interaction_graph_digest != Digest32::ZERO);
}

#[test]
fn negative_prerequisite_can_be_selected_as_part_of_positive_package() {
    let mut value = input(vec![factor(0, 100, 1), factor(1, -1, 1)]);
    value.maximum_selected_factors = 2;
    value.token_budget = 2;
    value.hard_constraints.push(LocalHardConstraint::Requires {
        candidate_id: id("candidate:000"),
        prerequisite_candidate_id: id("candidate:001"),
        support_reference_digest: d("requires"),
    });
    let Ok(proposal) = calculate_local_shadow(value) else {
        panic!("package selection")
    };
    assert_eq!(
        proposal.selections,
        vec![
            LocalShadowSelection {
                candidate_id: id("candidate:001"),
                factor_id: id("factor:001")
            },
            LocalShadowSelection {
                candidate_id: id("candidate:000"),
                factor_id: id("factor:000")
            }
        ]
    );
    assert_eq!(proposal.total_caller_supplied_gain, FixedQ32::from_raw(99));
}

#[test]
fn requires_cycle_is_rejected_explicitly() {
    let mut value = input(vec![factor(0, 10, 1), factor(1, 9, 1)]);
    value.hard_constraints = vec![
        LocalHardConstraint::Requires {
            candidate_id: id("candidate:000"),
            prerequisite_candidate_id: id("candidate:001"),
            support_reference_digest: d("a"),
        },
        LocalHardConstraint::Requires {
            candidate_id: id("candidate:001"),
            prerequisite_candidate_id: id("candidate:000"),
            support_reference_digest: d("b"),
        },
    ];
    assert!(matches!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(InvalidInput::RequiresCycle(
            _
        )))
    ));
}

#[test]
fn requires_conflict_contradiction_is_rejected_explicitly() {
    let mut value = input(vec![factor(0, 10, 1), factor(1, 9, 1)]);
    value.hard_constraints = vec![
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: d("conflict"),
        },
        LocalHardConstraint::Requires {
            candidate_id: id("candidate:000"),
            prerequisite_candidate_id: id("candidate:001"),
            support_reference_digest: d("requires"),
        },
    ];
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::UnsatisfiableConstraintGraph("candidate:000".to_string())
        ))
    );
}

#[test]
fn hard_conflict_cannot_be_outweighed_by_interaction_gain() {
    let mut value = input(vec![factor(0, 100, 1), factor(1, 90, 1)]);
    value.maximum_selected_factors = 2;
    value
        .interaction_edges
        .push(edge("candidate:000", "candidate:001", 10_000));
    value.hard_constraints.push(LocalHardConstraint::Conflict {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        support_reference_digest: d("conflict"),
    });
    let Ok(proposal) = calculate_local_shadow(value) else {
        panic!("shadow")
    };
    assert_eq!(proposal.selections.len(), 1);
    assert_eq!(proposal.selections[0].candidate_id, id("candidate:000"));
}

#[test]
fn interaction_ceiling_is_independent_of_token_budget() {
    let mut value = input(vec![factor(0, 1, 513)]);
    value.token_budget = 513;
    let Ok(proposal) = calculate_local_shadow(value) else {
        panic!("shadow")
    };
    assert_eq!(proposal.total_token_cost, 513);
    let factors = (0..33).map(|i| factor(i, 1, 1)).collect::<Vec<_>>();
    let mut value = input(factors);
    value.interaction_edges = (0..(MAX_INTERACTION_EDGES + 1))
        .map(|index| LocalPairInteraction {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            caller_supplied_marginal_gain: FixedQ32::ZERO,
            support_reference_digest: d(&format!("edge:{index}")),
        })
        .collect();
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::InteractionEdgeLimitExceeded
        ))
    );
}

#[test]
fn fixed_point_overflow_is_reported() {
    let mut value = input(vec![factor(0, i64::MAX, 1), factor(1, 1, 1)]);
    value.maximum_selected_factors = 2;
    value
        .interaction_edges
        .push(edge("candidate:000", "candidate:001", i64::MAX));
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::ArithmeticInvariant(
            ArithmeticInvariant::FixedPointOverflow
        ))
    );
}

#[test]
fn noncanonical_inputs_are_rejected() {
    let value = input(vec![factor(1, 1, 1), factor(0, 1, 1)]);
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::NonCanonicalCandidateOrder
        ))
    );
    let mut value = input(vec![factor(0, 1, 1), factor(1, 1, 1)]);
    value
        .interaction_edges
        .push(edge("candidate:001", "candidate:000", 0));
    assert_eq!(
        calculate_local_shadow(value),
        Err(LocalShadowError::InvalidInput(
            InvalidInput::InvalidInteractionEndpoints
        ))
    );
}

#[test]
fn support_and_registry_integrity_fail_closed() {
    let mut candidate = factor(0, 1, 1);
    candidate.support_digest = Digest32::ZERO;
    assert_eq!(
        calculate_local_shadow(input(vec![candidate])),
        Err(LocalShadowError::InsufficientEvidence(
            InsufficientEvidence::EmptySupportReference("factor candidate")
        ))
    );
    let mut candidate = factor(0, 1, 1);
    candidate.registry_digest = d("other");
    assert_eq!(
        calculate_local_shadow(input(vec![candidate])),
        Err(LocalShadowError::IntegrityMismatch(
            IntegrityMismatch::RegistrySnapshot("candidate:000".to_string())
        ))
    );
}
