use pretty_assertions::assert_eq;

use super::*;
use crate::OptimizationRequest;
use crate::optimize;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn test_digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
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
        registry_digest: test_digest(b"registry"),
        support_digest: test_digest(name.as_bytes()),
    }
}

fn local_input(factors: Vec<PromptCandidate>) -> LocalShadowInput {
    LocalShadowInput {
        decision_id: id("decision:local-shadow"),
        objective_digest: test_digest(b"objective"),
        state_digest: test_digest(b"state"),
        registry_snapshot_digest: test_digest(b"registry"),
        token_budget: 10_000,
        maximum_selected_factors: 1,
        no_intervention: LocalNoInterventionBaseline {
            arm_id: id(LOCAL_NO_INTERVENTION_ID),
            registry_digest: test_digest(b"registry"),
            support_reference_digest: test_digest(b"baseline-reference"),
        },
        factor_candidates: factors,
        interaction_edges: Vec::new(),
        hard_constraints: Vec::new(),
    }
}

fn interaction_edges(factors: &[PromptCandidate], limit: usize) -> Vec<LocalPairInteraction> {
    let mut edges = Vec::with_capacity(limit.min(MAX_INTERACTION_EDGES + 1));
    for (left_index, left) in factors.iter().enumerate() {
        for right in factors.iter().skip(left_index + 1) {
            if edges.len() == limit {
                return edges;
            }
            edges.push(LocalPairInteraction {
                left_candidate_id: left.candidate_id.clone(),
                right_candidate_id: right.candidate_id.clone(),
                caller_supplied_marginal_gain: FixedQ32::ZERO,
                support_reference_digest: test_digest(
                    format!("edge:{}:{}", left.candidate_id, right.candidate_id).as_bytes(),
                ),
            });
        }
    }
    edges
}

fn complete_interactions(factors: &[PromptCandidate]) -> Vec<LocalPairInteraction> {
    interaction_edges(factors, usize::MAX)
}

fn calculate(input: LocalShadowInput) -> LocalShadowProposal {
    let Ok(proposal) = calculate_local_shadow(input) else {
        panic!("test input must produce a local shadow proposal");
    };
    proposal
}

fn assert_error(input: LocalShadowInput, expected: LocalShadowError) {
    assert_eq!(calculate_local_shadow(input), Err(expected));
}

#[test]
fn legacy_v1_surface_keeps_its_original_selection_limit() {
    let candidates = (0..17)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    let legacy = OptimizationRequest {
        decision_id: id("decision:legacy"),
        objective_digest: test_digest(b"objective"),
        registry_snapshot_digest: test_digest(b"registry"),
        budget: 17,
        maximum_selected: 17,
        candidates,
    };
    let Ok(result) = optimize(legacy) else {
        panic!("the unchanged V1 path must retain its original limit");
    };
    assert_eq!(result.selected.len(), 17);
}

#[test]
fn total_candidate_limit_includes_the_local_baseline() {
    let factors = (0..MAX_FACTOR_CANDIDATES)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    let proposal = calculate(local_input(factors));
    assert_eq!(proposal.total_candidate_count, 128);
    assert_eq!(proposal.selections.len(), 1);

    let factors = (0..MAX_TOTAL_CANDIDATES)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    assert_error(
        local_input(factors),
        LocalShadowError::InvalidInput(InvalidInput::TotalCandidateLimitExceeded),
    );
}

#[test]
fn local_baseline_cannot_impersonate_canonical_abstain() {
    let mut input = local_input(vec![factor(
        /*index*/ 0, /*gain*/ 1, /*cost*/ 1,
    )]);
    input.no_intervention.arm_id = id("abstain");
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::InvalidNoInterventionIdentity(
            "abstain".to_string(),
        )),
    );
}

#[test]
fn local_baseline_is_singular_and_cannot_alias_a_factor_candidate() {
    let mut duplicate = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    duplicate.candidate_id = id(LOCAL_NO_INTERVENTION_ID);
    assert_error(
        local_input(vec![duplicate]),
        LocalShadowError::InvalidInput(InvalidInput::DuplicateCandidate(
            LOCAL_NO_INTERVENTION_ID.to_string(),
        )),
    );
}

#[test]
fn result_discloses_local_scope_heuristic_status_and_no_authority() {
    let mut candidate = factor(/*index*/ 0, /*gain*/ 7, /*cost*/ 2);
    candidate.factor_id = id("factor:actual-binding");
    let proposal = calculate(local_input(vec![candidate]));

    assert_eq!(
        proposal.no_intervention_arm_id,
        id(LOCAL_NO_INTERVENTION_ID)
    );
    assert_eq!(
        proposal.candidate_scope,
        LocalCandidateScope::SuppliedCandidatesOnly
    );
    assert_eq!(
        proposal.selection_method,
        LocalSelectionMethod::GreedyMarginalV1
    );
    assert_eq!(
        proposal.optimality,
        LocalOptimalityDisclosure::HeuristicNoCertificate
    );
    assert_eq!(
        proposal.selections,
        vec![LocalShadowSelection {
            candidate_id: id("candidate:000"),
            factor_id: id("factor:actual-binding"),
        }]
    );
    assert_eq!(
        proposal.total_caller_supplied_gain,
        FixedQ32::from_raw(/*raw*/ 7)
    );
    assert!(!proposal.authority().grants_any());
}

#[test]
fn invalid_input_has_its_own_error_class() {
    let mut input = local_input(vec![factor(
        /*index*/ 0, /*gain*/ 1, /*cost*/ 1,
    )]);
    input.maximum_selected_factors = MAX_SELECTED_FACTORS + 1;
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::SelectedFactorLimitExceeded),
    );
}

#[test]
fn insufficient_pair_support_has_its_own_error_class() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    assert_error(
        input,
        LocalShadowError::InsufficientEvidence(InsufficientEvidence::MissingPairInteraction(
            "candidate:000".to_string(),
            "candidate:001".to_string(),
        )),
    );
}

#[test]
fn registry_mismatch_has_its_own_integrity_error_class() {
    let mut candidate = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    candidate.registry_digest = test_digest(b"different-registry");
    assert_error(
        local_input(vec![candidate]),
        LocalShadowError::IntegrityMismatch(IntegrityMismatch::RegistrySnapshot(
            "candidate:000".to_string(),
        )),
    );
}

#[test]
fn fixed_point_overflow_has_its_own_arithmetic_error_class() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ i64::MAX, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);
    input.interaction_edges[0].caller_supplied_marginal_gain =
        FixedQ32::from_raw(/*raw*/ i64::MAX);
    assert_error(
        input,
        LocalShadowError::ArithmeticInvariant(ArithmeticInvariant::FixedPointOverflow),
    );
}

#[test]
fn explicit_zero_edges_make_a_multi_factor_pair_complete() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);

    let proposal = calculate(input);
    assert_eq!(
        proposal.selections,
        vec![
            LocalShadowSelection {
                candidate_id: id("candidate:000"),
                factor_id: id("factor:000"),
            },
            LocalShadowSelection {
                candidate_id: id("candidate:001"),
                factor_id: id("factor:001"),
            },
        ]
    );
}

#[test]
fn pair_completeness_fails_closed_before_sparse_graph_is_treated_as_zero() {
    let factors = (0..33)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    let mut input = local_input(factors);
    input.maximum_selected_factors = 2;
    input.interaction_edges = interaction_edges(
        &input.factor_candidates,
        /*limit*/ MAX_INTERACTION_EDGES,
    );
    let result = calculate_local_shadow(input);
    assert!(matches!(
        result,
        Err(LocalShadowError::InsufficientEvidence(
            InsufficientEvidence::MissingPairInteraction(_, _)
        ))
    ));
}

#[test]
fn interaction_ceiling_is_not_a_token_budget() {
    let mut input = local_input(vec![factor(
        /*index*/ 0, /*gain*/ 1, /*cost*/ 513,
    )]);
    input.token_budget = 513;
    let proposal = calculate(input);
    assert_eq!(proposal.total_token_cost, 513);

    let factors = (0..33)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    let mut input = local_input(factors);
    input.maximum_selected_factors = 0;
    input.interaction_edges = interaction_edges(
        &input.factor_candidates,
        /*limit*/ MAX_INTERACTION_EDGES,
    );
    assert!(calculate_local_shadow(input).is_ok());

    let factors = (0..33)
        .map(|index| factor(index, /*gain*/ 1, /*cost*/ 1))
        .collect();
    let mut input = local_input(factors);
    input.interaction_edges = interaction_edges(
        &input.factor_candidates,
        /*limit*/ MAX_INTERACTION_EDGES + 1,
    );
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::InteractionEdgeLimitExceeded),
    );
}

#[test]
fn hard_constraint_edges_have_an_independent_resource_ceiling() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.hard_constraints = (0..(MAX_HARD_CONSTRAINT_EDGES + 1))
        .map(|index| LocalHardConstraint::Requires {
            candidate_id: id("candidate:000"),
            prerequisite_candidate_id: id("candidate:001"),
            support_reference_digest: test_digest(format!("constraint:{index}").as_bytes()),
        })
        .collect();
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::HardConstraintLimitExceeded),
    );
}

#[test]
fn hard_conflict_cannot_be_outweighed_by_numeric_gain() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 100, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 90, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);
    input.interaction_edges[0].caller_supplied_marginal_gain =
        FixedQ32::from_raw(/*raw*/ 10_000);
    input.hard_constraints.push(LocalHardConstraint::Conflict {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        support_reference_digest: test_digest(b"conflict-reference"),
    });

    let proposal = calculate(input);
    assert_eq!(
        proposal.selections,
        vec![LocalShadowSelection {
            candidate_id: id("candidate:000"),
            factor_id: id("factor:000"),
        }]
    );
    assert_eq!(
        proposal.total_caller_supplied_gain,
        FixedQ32::from_raw(/*raw*/ 100)
    );
}

#[test]
fn prerequisite_must_be_selected_before_dependent_factor() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 100, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);
    input.hard_constraints.push(LocalHardConstraint::Requires {
        candidate_id: id("candidate:000"),
        prerequisite_candidate_id: id("candidate:001"),
        support_reference_digest: test_digest(b"requires-reference"),
    });

    let proposal = calculate(input);
    assert_eq!(
        proposal.selections,
        vec![
            LocalShadowSelection {
                candidate_id: id("candidate:001"),
                factor_id: id("factor:001"),
            },
            LocalShadowSelection {
                candidate_id: id("candidate:000"),
                factor_id: id("factor:000"),
            },
        ]
    );
}

#[test]
fn unavailable_prerequisite_blocks_high_gain_dependent_factor() {
    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 100, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ -1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);
    input.hard_constraints.push(LocalHardConstraint::Requires {
        candidate_id: id("candidate:000"),
        prerequisite_candidate_id: id("candidate:001"),
        support_reference_digest: test_digest(b"requires-reference"),
    });

    let proposal = calculate(input);
    assert!(proposal.selections.is_empty());
    assert_eq!(proposal.total_caller_supplied_gain, FixedQ32::ZERO);
}

#[test]
fn unknown_prerequisite_is_rejected_instead_of_ignored() {
    let mut input = local_input(vec![factor(
        /*index*/ 0, /*gain*/ 100, /*cost*/ 1,
    )]);
    input.hard_constraints.push(LocalHardConstraint::Requires {
        candidate_id: id("candidate:000"),
        prerequisite_candidate_id: id("candidate:missing"),
        support_reference_digest: test_digest(b"requires-reference"),
    });
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::UnknownHardConstraintEndpoint(
            "candidate:missing".to_string(),
        )),
    );
}

#[test]
fn hard_constraints_are_canonical_unique_and_digest_bound() {
    let mut first_input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    first_input.maximum_selected_factors = 2;
    first_input.interaction_edges = complete_interactions(&first_input.factor_candidates);
    first_input
        .hard_constraints
        .push(LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: test_digest(b"first-conflict-reference"),
        });
    let mut second_input = first_input.clone();
    let LocalHardConstraint::Conflict {
        support_reference_digest,
        ..
    } = &mut second_input.hard_constraints[0]
    else {
        panic!("test constraint must be a conflict");
    };
    *support_reference_digest = test_digest(b"second-conflict-reference");

    let first = calculate(first_input);
    let second = calculate(second_input);
    assert_eq!(first.selections, second.selections);
    assert_ne!(first.hard_constraint_digest, second.hard_constraint_digest);
    assert_ne!(first.proposal_digest, second.proposal_digest);

    let mut duplicate_input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    duplicate_input.hard_constraints = vec![
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: test_digest(b"first-reference"),
        },
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: test_digest(b"second-reference"),
        },
    ];
    assert_error(
        duplicate_input,
        LocalShadowError::InvalidInput(InvalidInput::DuplicateHardConstraint(
            "conflict",
            "candidate:000".to_string(),
            "candidate:001".to_string(),
        )),
    );
}

#[test]
fn noncanonical_candidate_interaction_and_constraint_inputs_are_rejected() {
    assert_error(
        local_input(vec![
            factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
            factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1),
        ]),
        LocalShadowError::InvalidInput(InvalidInput::NonCanonicalCandidateOrder),
    );

    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.interaction_edges.push(LocalPairInteraction {
        left_candidate_id: id("candidate:001"),
        right_candidate_id: id("candidate:000"),
        caller_supplied_marginal_gain: FixedQ32::ZERO,
        support_reference_digest: test_digest(b"edge-reference"),
    });
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::InvalidInteractionEndpoints),
    );

    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.hard_constraints = vec![
        LocalHardConstraint::Requires {
            candidate_id: id("candidate:001"),
            prerequisite_candidate_id: id("candidate:000"),
            support_reference_digest: test_digest(b"requires-reference"),
        },
        LocalHardConstraint::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_reference_digest: test_digest(b"conflict-reference"),
        },
    ];
    assert_error(
        input,
        LocalShadowError::InvalidInput(InvalidInput::NonCanonicalHardConstraintOrder),
    );
}

#[test]
fn factor_and_realization_aliases_are_rejected() {
    let first = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    let mut duplicate_factor = factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1);
    duplicate_factor.factor_id = first.factor_id.clone();
    assert_error(
        local_input(vec![first, duplicate_factor]),
        LocalShadowError::InvalidInput(InvalidInput::DuplicateFactor("factor:000".to_string())),
    );

    let first = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    let mut duplicate_realization = factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1);
    duplicate_realization.realization_id = first.realization_id.clone();
    assert_error(
        local_input(vec![first, duplicate_realization]),
        LocalShadowError::InvalidInput(InvalidInput::DuplicateRealization(
            "realization:000".to_string(),
        )),
    );
}

#[test]
fn unadmitted_illegal_and_zero_cost_factors_fail_closed() {
    let mut unadmitted = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    unadmitted.admitted = false;
    assert_error(
        local_input(vec![unadmitted]),
        LocalShadowError::InvalidInput(InvalidInput::UnadmittedFactor("candidate:000".to_string())),
    );

    let mut illegal = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    illegal.legal = false;
    assert_error(
        local_input(vec![illegal]),
        LocalShadowError::InvalidInput(InvalidInput::IllegalFactor("candidate:000".to_string())),
    );

    assert_error(
        local_input(vec![factor(
            /*index*/ 0, /*gain*/ 1, /*cost*/ 0,
        )]),
        LocalShadowError::InvalidInput(InvalidInput::InvalidFactorCost(
            "candidate:000".to_string(),
        )),
    );
}

#[test]
fn empty_support_references_fail_as_insufficient_evidence() {
    let mut candidate = factor(/*index*/ 0, /*gain*/ 1, /*cost*/ 1);
    candidate.support_digest = Digest32::ZERO;
    assert_error(
        local_input(vec![candidate]),
        LocalShadowError::InsufficientEvidence(InsufficientEvidence::EmptySupportReference(
            "factor candidate",
        )),
    );

    let mut input = local_input(vec![
        factor(/*index*/ 0, /*gain*/ 2, /*cost*/ 1),
        factor(/*index*/ 1, /*gain*/ 1, /*cost*/ 1),
    ]);
    input.maximum_selected_factors = 2;
    input.interaction_edges = complete_interactions(&input.factor_candidates);
    input.interaction_edges[0].support_reference_digest = Digest32::ZERO;
    assert_error(
        input,
        LocalShadowError::InsufficientEvidence(InsufficientEvidence::EmptySupportReference(
            "pair interaction",
        )),
    );
}

#[test]
fn local_shadow_digest_domains_are_stable() {
    let proposal = calculate(local_input(vec![factor(
        /*index*/ 0, /*gain*/ 7, /*cost*/ 2,
    )]));
    assert_eq!(
        (
            proposal.candidate_input_digest.to_string(),
            proposal.interaction_graph_digest.to_string(),
            proposal.hard_constraint_digest.to_string(),
            proposal.proposal_digest.to_string(),
        ),
        (
            "17dfcc5cc35662286aeace12e035d7442c3fd1d8c2bc233cc815d10a758565d8".to_string(),
            "1482cabda467e78ba783e93b24392c2c42cf42919db888e5e8153e3ecd9f473d".to_string(),
            "803a05bd96f1e3c10aed15a8e62b374578571909c7cedd77bf65f7275791108c".to_string(),
            "44ab529afe66c7062695a029ee5ca76eac29278b4a765aab9a6c4d55f18bf7d1".to_string(),
        )
    );
}
