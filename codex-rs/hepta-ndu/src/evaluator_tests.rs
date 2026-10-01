use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::canonical_evaluation_policy_digest;
use super::canonical_scalarization_digest;
use super::evaluate_candidates;
use super::evaluate_candidates_with_policy;
use super::legacy_evaluation_policy;
use crate::AggregationOperator;
use crate::AxisAggregationRule;
use crate::AxisDirection;
use crate::AxisLimit;
use crate::AxisValue;
use crate::ContributionSet;
use crate::EvaluationDisposition;
use crate::EvaluationPolicyV1;
use crate::FeasibilityPosture;
use crate::NduError;
use crate::NduEvaluationReceipt;
use crate::RequiredOrganSet;
use crate::ScalarizationProfile;
use crate::UtilityContribution;
use crate::UtilityProfile;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn contribution_from(
    candidate: &str,
    organ: &str,
    success: i64,
    latency: i64,
) -> UtilityContribution {
    UtilityContribution {
        candidate_id: id(candidate),
        organ_id: id(organ),
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(1)),
        feasibility: FeasibilityPosture::Feasible,
        utility: vec![
            AxisValue {
                axis: id("success"),
                value: q32(success),
            },
            AxisValue {
                axis: id("latency"),
                value: q32(latency),
            },
        ],
        risk: vec![AxisValue {
            axis: id("privacy-risk"),
            value: FixedQ32::ZERO,
        }],
        resource: vec![AxisValue {
            axis: id("compute"),
            value: q32(1),
        }],
        uncertainty: vec![
            AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            },
            AxisValue {
                axis: id("latency"),
                value: FixedQ32::ZERO,
            },
        ],
        support_digest: Digest32::of_bytes(format!("{candidate}:{organ}").as_bytes()),
    }
}

fn contribution(candidate: &str, success: i64, latency: i64) -> UtilityContribution {
    contribution_from(candidate, "planner", success, latency)
}

fn profile() -> UtilityProfile {
    UtilityProfile {
        profile_id: id("utility-v1"),
        axis_registry_digest: Digest32::of_bytes(b"utility-v1-axis-registry"),
        normalization_manifest_digest: Digest32::of_bytes(b"utility-v1-normalization"),
        dimensions: vec![
            (id("success"), AxisDirection::Maximize),
            (id("latency"), AxisDirection::Minimize),
        ],
        risk_ceilings: vec![AxisLimit {
            axis: id("privacy-risk"),
            maximum: FixedQ32::ZERO,
        }],
        resource_ceilings: vec![AxisLimit {
            axis: id("compute"),
            maximum: q32(10),
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    }
}

fn set(contributions: Vec<UtilityContribution>) -> ContributionSet {
    ContributionSet {
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: must(Generation::new(1)),
        contributions,
    }
}

#[test]
fn hard_violation_is_filtered_before_utility() {
    let abstain = contribution("abstain", 0, 0);
    let mut unsafe_candidate = contribution("unsafe-high-score", 100, 0);
    unsafe_candidate.feasibility = FeasibilityPosture::HardConstraintViolation;

    let receipt = must(evaluate_candidates(
        set(vec![abstain, unsafe_candidate]),
        profile(),
        None,
    ));

    assert_eq!(
        receipt.disposition,
        EvaluationDisposition::InfeasibleExplicitAbstain
    );
    assert_eq!(receipt.advisory_recommendation, Some(id("abstain")));
    assert_eq!(receipt.rejected_candidates.len(), 1);
}

#[test]
fn non_dominated_candidates_without_scalarization_require_slow_path() {
    let receipt = must(evaluate_candidates(
        set(vec![
            contribution("abstain", 0, 0),
            contribution("fast", 1, 1),
            contribution("accurate", 2, 2),
        ]),
        profile(),
        None,
    ));

    assert_eq!(
        receipt.disposition,
        EvaluationDisposition::ParetoSetRequiresSlowPath
    );
    assert_eq!(receipt.advisory_recommendation, None);
    assert_eq!(receipt.pareto_frontier.len(), 3);
}

#[test]
fn registered_scalarization_produces_advisory_recommendation() {
    let scalarization = ScalarizationProfile {
        profile_id: id("weights-v1"),
        weights: vec![
            AxisValue {
                axis: id("success"),
                value: FixedQ32::ONE,
            },
            AxisValue {
                axis: id("latency"),
                value: FixedQ32::ZERO,
            },
        ],
    };
    let receipt = must(evaluate_candidates(
        set(vec![
            contribution("abstain", 0, 0),
            contribution("fast", 1, 1),
            contribution("accurate", 2, 2),
        ]),
        profile(),
        Some(scalarization),
    ));

    assert_eq!(
        receipt.disposition,
        EvaluationDisposition::ScalarizedRecommendation
    );
    assert_eq!(receipt.advisory_recommendation, Some(id("accurate")));
    assert!(receipt.scalarization_profile_digest.is_some());
}

#[test]
fn missing_required_contribution_is_not_treated_as_zero() {
    let mut required = profile();
    required.required_organs.organ_ids.push(id("risk-observer"));

    let error = must_err(evaluate_candidates(
        set(vec![contribution("abstain", 0, 0)]),
        required,
        None,
    ));

    assert_eq!(error.code(), "NDU-E003");
}

#[test]
fn infeasible_abstain_is_rejected_before_any_recommendation() {
    let mut abstain = contribution("abstain", 0, 0);
    abstain.feasibility = FeasibilityPosture::HardConstraintViolation;

    let error = must_err(evaluate_candidates(
        set(vec![abstain, contribution("safe", 1, 1)]),
        profile(),
        None,
    ));

    assert_eq!(error.code(), "NDU-E005");
}

#[test]
fn scalarization_digest_is_computed_from_canonical_inputs() {
    let first = ScalarizationProfile {
        profile_id: id("weights-v1"),
        weights: vec![
            AxisValue {
                axis: id("success"),
                value: FixedQ32::ONE,
            },
            AxisValue {
                axis: id("latency"),
                value: FixedQ32::ZERO,
            },
        ],
    };
    let mut reordered = first.clone();
    reordered.weights.reverse();

    assert_eq!(
        must(canonical_scalarization_digest(&first)),
        must(canonical_scalarization_digest(&reordered))
    );
}

#[test]
fn policy_selects_axis_specific_aggregation_instead_of_implicit_sum() {
    let mut profile = profile();
    profile.required_organs.organ_ids.push(id("observer"));
    let mut policy = must(legacy_evaluation_policy(&profile));
    policy
        .utility_rules
        .iter_mut()
        .find(|rule| rule.axis == id("success"))
        .expect("success rule")
        .operator = AggregationOperator::Maximum;
    let receipt = must(evaluate_candidates_with_policy(
        set(vec![
            contribution_from("abstain", "planner", 0, 0),
            contribution_from("abstain", "observer", 0, 0),
            contribution_from("work", "planner", 1, 0),
            contribution_from("work", "observer", 2, 0),
        ]),
        profile,
        None,
        policy,
    ));
    let work = receipt
        .base
        .evaluated_candidates
        .iter()
        .find(|candidate| candidate.candidate_id == id("work"))
        .expect("work candidate");
    let success = work
        .utility
        .iter()
        .find(|value| value.axis == id("success"))
        .expect("success axis");

    assert_eq!(success.value, q32(2));
    assert!(!receipt.evaluation_policy_digest.is_zero());
    assert!(!receipt.evaluation_digest_v2.is_zero());
}

#[test]
fn require_equal_aggregation_rejects_conflicting_owners() {
    let mut profile = profile();
    profile.required_organs.organ_ids.push(id("observer"));
    let mut policy = must(legacy_evaluation_policy(&profile));
    policy
        .utility_rules
        .iter_mut()
        .find(|rule| rule.axis == id("success"))
        .expect("success rule")
        .operator = AggregationOperator::RequireEqual;

    let error = must_err(evaluate_candidates_with_policy(
        set(vec![
            contribution_from("abstain", "planner", 0, 0),
            contribution_from("abstain", "observer", 0, 0),
            contribution_from("work", "planner", 1, 0),
            contribution_from("work", "observer", 2, 0),
        ]),
        profile,
        None,
        policy,
    ));

    assert_eq!(error.code(), "NDU-E004");
}

#[test]
fn pareto_tolerance_is_digest_bound_and_changes_dominance() {
    let profile = profile();
    let contributions = vec![
        contribution("abstain", 0, 0),
        contribution("near", 1, 0),
        contribution("better", 2, 0),
    ];
    let exact = must(evaluate_candidates(
        set(contributions.clone()),
        profile.clone(),
        None,
    ));
    assert_eq!(exact.pareto_frontier.len(), 1);

    let mut policy = must(legacy_evaluation_policy(&profile));
    policy
        .pareto_absolute_tolerances
        .iter_mut()
        .find(|value| value.axis == id("success"))
        .expect("success tolerance")
        .value = q32(1);
    let tolerant = must(evaluate_candidates_with_policy(
        set(contributions),
        profile,
        None,
        policy,
    ));

    assert_eq!(tolerant.base.pareto_frontier.len(), 2);
    assert_eq!(
        tolerant.base.disposition,
        EvaluationDisposition::ParetoSetRequiresSlowPath
    );
}

#[test]
fn policy_digest_is_permutation_invariant() {
    let profile = profile();
    let first = must(legacy_evaluation_policy(&profile));
    let mut reordered = first.clone();
    reordered.utility_rules.reverse();
    reordered.risk_rules.reverse();
    reordered.resource_rules.reverse();
    reordered.uncertainty_rules.reverse();
    reordered.pareto_absolute_tolerances.reverse();

    assert_eq!(
        must(canonical_evaluation_policy_digest(&profile, &first)),
        must(canonical_evaluation_policy_digest(&profile, &reordered))
    );
}

#[test]
fn missing_uncertainty_axis_is_unavailable() {
    let abstain = contribution("abstain", 0, 0);
    let mut work = contribution("work", 1, 1);
    work.uncertainty.retain(|value| value.axis == id("success"));

    let error = must_err(evaluate_candidates(
        set(vec![abstain, work]),
        profile(),
        None,
    ));
    assert_eq!(error.code(), "NDU-E004");
}

#[test]
fn candidate_support_digest_binds_organ_and_contribution_semantics() {
    let mut open_profile = profile();
    open_profile.required_organs.organ_ids.clear();
    let first = must(evaluate_candidates(
        set(vec![
            contribution("abstain", 0, 0),
            contribution("work", 1, 1),
        ]),
        open_profile.clone(),
        None,
    ));
    let first_support = first
        .evaluated_candidates
        .iter()
        .find(|candidate| candidate.candidate_id == id("work"))
        .expect("work candidate")
        .support_digest;

    let mut changed = contribution("work", 1, 1);
    changed.organ_id = id("other-organ");
    let second = must(evaluate_candidates(
        set(vec![contribution("abstain", 0, 0), changed]),
        open_profile,
        None,
    ));
    let second_support = second
        .evaluated_candidates
        .iter()
        .find(|candidate| candidate.candidate_id == id("work"))
        .expect("work candidate")
        .support_digest;

    assert_ne!(first_support, second_support);
}

fn legacy_reference_policy() -> EvaluationPolicyV1 {
    // Spell out the historical contract independently of the policy generator.
    let rule = |axis, operator| AxisAggregationRule {
        axis: id(axis),
        operator,
    };
    EvaluationPolicyV1 {
        policy_id: id("legacy-sum-max-zero-tolerance-v1"),
        utility_rules: vec![
            rule("success", AggregationOperator::Sum),
            rule("latency", AggregationOperator::Sum),
        ],
        risk_rules: vec![rule("privacy-risk", AggregationOperator::Sum)],
        resource_rules: vec![rule("compute", AggregationOperator::Sum)],
        uncertainty_rules: vec![
            rule("success", AggregationOperator::Maximum),
            rule("latency", AggregationOperator::Maximum),
        ],
        pareto_absolute_tolerances: legacy_axis_values(&[("success", 0), ("latency", 0)]),
    }
}

fn legacy_axis_values(values: &[(&str, i64)]) -> Vec<AxisValue> {
    values
        .iter()
        .map(|(axis, value)| AxisValue {
            axis: id(axis),
            value: q32(*value),
        })
        .collect()
}

fn legacy_multi_organ_fixture() -> (ContributionSet, UtilityProfile) {
    let mut profile = profile();
    profile.required_organs.organ_ids.push(id("observer"));
    profile.risk_ceilings[0].maximum = q32(/*value*/ 3);
    let mut work_planner =
        contribution_from("work", "planner", /*success*/ 1, /*latency*/ 0);
    work_planner.risk[0].value = q32(/*value*/ 1);
    work_planner.resource[0].value = q32(/*value*/ 2);
    work_planner.uncertainty = legacy_axis_values(&[("success", 1), ("latency", 2)]);
    let mut work_observer =
        contribution_from("work", "observer", /*success*/ 2, /*latency*/ 0);
    work_observer.risk[0].value = q32(/*value*/ 2);
    work_observer.resource[0].value = q32(/*value*/ 3);
    work_observer.uncertainty = legacy_axis_values(&[("success", 3), ("latency", 4)]);
    (
        set(vec![
            contribution_from("abstain", "planner", /*success*/ 0, /*latency*/ 0),
            contribution_from(
                "abstain", "observer", /*success*/ 0, /*latency*/ 0,
            ),
            work_planner,
            work_observer,
        ]),
        profile,
    )
}

fn assert_legacy_equivalent(
    input: ContributionSet,
    profile: UtilityProfile,
    scalarization: Option<ScalarizationProfile>,
) -> Result<NduEvaluationReceipt, NduError> {
    let legacy = evaluate_candidates(input.clone(), profile.clone(), scalarization.clone());
    let explicit =
        evaluate_candidates_with_policy(input, profile, scalarization, legacy_reference_policy())
            .map(|receipt| receipt.base);
    assert_eq!(legacy, explicit);
    legacy
}

#[test]
fn legacy_compatibility_matches_explicit_policy_for_complete_receipts() {
    let (input, profile) = legacy_multi_organ_fixture();
    let mut hard_violation = input.clone();
    hard_violation.contributions[2].feasibility = FeasibilityPosture::HardConstraintViolation;
    let mut risk_violation = input.clone();
    risk_violation.contributions[3].risk[0].value = q32(/*value*/ 3);
    let mut resource_violation = input.clone();
    resource_violation.contributions[2].resource[0].value = q32(/*value*/ 8);
    let mut tradeoff = input.clone();
    tradeoff.contributions[2].utility[1].value = q32(/*value*/ 1);
    tradeoff.contributions[3].utility[1].value = q32(/*value*/ 2);
    let scalarization = ScalarizationProfile {
        profile_id: id("legacy-equivalence-weights"),
        weights: legacy_axis_values(&[("success", 1), ("latency", 0)]),
    };
    let mut tied_scalarization = scalarization.clone();
    for weight in &mut tied_scalarization.weights {
        weight.value = FixedQ32::from_raw(FixedQ32::ONE.raw() / 2);
    }
    let scenarios = [
        (
            input,
            None,
            EvaluationDisposition::UniqueParetoRecommendation,
        ),
        (
            hard_violation,
            None,
            EvaluationDisposition::InfeasibleExplicitAbstain,
        ),
        (
            risk_violation,
            None,
            EvaluationDisposition::InfeasibleExplicitAbstain,
        ),
        (
            resource_violation,
            None,
            EvaluationDisposition::InfeasibleExplicitAbstain,
        ),
        (
            tradeoff.clone(),
            None,
            EvaluationDisposition::ParetoSetRequiresSlowPath,
        ),
        (
            tradeoff.clone(),
            Some(scalarization),
            EvaluationDisposition::ScalarizedRecommendation,
        ),
        (
            tradeoff,
            Some(tied_scalarization),
            EvaluationDisposition::ScalarizationTieRequiresSlowPath,
        ),
    ];
    for (mut input, mut scalarization, disposition) in scenarios {
        let receipt = must(assert_legacy_equivalent(
            input.clone(),
            profile.clone(),
            scalarization.clone(),
        ));
        assert_eq!(receipt.disposition, disposition);
        if disposition == EvaluationDisposition::UniqueParetoRecommendation {
            let work = receipt
                .evaluated_candidates
                .iter()
                .find(|candidate| candidate.candidate_id == id("work"))
                .expect("work candidate");
            assert_eq!(
                (&work.utility, &work.risk, &work.resource, &work.uncertainty),
                (
                    &legacy_axis_values(&[("latency", 0), ("success", 3)]),
                    &legacy_axis_values(&[("privacy-risk", 3)]),
                    &legacy_axis_values(&[("compute", 5)]),
                    &legacy_axis_values(&[("latency", 4), ("success", 3)]),
                )
            );
        }
        input.contributions.reverse();
        for contribution in &mut input.contributions {
            contribution.utility.reverse();
            contribution.risk.reverse();
            contribution.resource.reverse();
            contribution.uncertainty.reverse();
        }
        let mut reordered_profile = profile.clone();
        reordered_profile.dimensions.reverse();
        reordered_profile.required_organs.organ_ids.reverse();
        if let Some(scalarization) = &mut scalarization {
            scalarization.weights.reverse();
        }
        assert_eq!(
            must(assert_legacy_equivalent(
                input,
                reordered_profile,
                scalarization
            )),
            receipt
        );
    }
}

#[test]
fn legacy_compatibility_preserves_complete_error_values() {
    let (input, profile) = legacy_multi_organ_fixture();
    let mut missing_organ = input.clone();
    missing_organ.contributions.truncate(/*len*/ 3);
    let mut duplicate = input.clone();
    duplicate.contributions.push(input.contributions[2].clone());
    let mut mixed_objective = input.clone();
    mixed_objective.contributions[2].objective_digest = Digest32::of_bytes(b"other-objective");
    let mut mixed_generation = input.clone();
    mixed_generation.contributions[2].generation = must(Generation::new(/*value*/ 2));
    let mut missing_axis = input.clone();
    for contribution in &mut missing_axis.contributions[2..] {
        contribution
            .uncertainty
            .retain(|value| value.axis == id("success"));
    }
    let mut overflow = input.clone();
    overflow.contributions[2].utility[0].value = FixedQ32::from_raw(i64::MAX);
    let cases = [
        (
            missing_organ,
            NduError::MissingRequiredOrgan {
                candidate: "work".to_owned(),
                organ: "observer".to_owned(),
            },
        ),
        (
            duplicate,
            NduError::DuplicateOrganContribution {
                candidate: "work".to_owned(),
                organ: "planner".to_owned(),
            },
        ),
        (mixed_objective, NduError::MixedObjective),
        (mixed_generation, NduError::MixedGeneration),
        (
            missing_axis,
            NduError::MissingAxis {
                candidate: "work".to_owned(),
                axis: "uncertainty:latency".to_owned(),
            },
        ),
        (overflow, NduError::Arithmetic),
    ];
    for (input, error) in cases {
        assert_eq!(
            assert_legacy_equivalent(input, profile.clone(), /*scalarization*/ None),
            Err(error)
        );
    }
    let mut invalid_profile = profile;
    invalid_profile.axis_registry_digest = Digest32::ZERO;
    assert_eq!(
        assert_legacy_equivalent(input, invalid_profile, /*scalarization*/ None),
        Err(NduError::EmptyProfileDigest("axis_registry"))
    );
}
