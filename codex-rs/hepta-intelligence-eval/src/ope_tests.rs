use super::*;
use std::fmt::Debug;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn probability(quarters: u64) -> ProbabilityQ32 {
    must(ProbabilityQ32::from_raw(quarters * (1 << 30)))
}

fn fixture() -> (OpePlan, Vec<OpeRow>) {
    let plan = OpePlan {
        plan_digest: Digest32::of_bytes(b"frozen-plan"),
        outcome_watermark: 100,
        minimum_rows: 4,
        minimum_ess: FixedQ32::from_raw(2 << 32),
        maximum_weight: FixedQ32::from_raw(50 << 32),
    };
    let rows = [(2, 1, true), (1, 2, false), (2, 1, true), (1, 2, true)]
        .into_iter()
        .enumerate()
        .map(|(index, (behavior, evaluation, success))| OpeRow {
            decision_id: id(&format!("decision-{index}")),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: probability(behavior),
                    evaluation_probability: probability(evaluation),
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: probability(4 - behavior),
                    evaluation_probability: probability(4 - evaluation),
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(if success {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            }),
            outcome_observed_at: 50,
            outcome_evidence: Digest32::of_bytes(b"independent-outcome"),
            outcome_model_evidence: Digest32::of_bytes(b"zero-tabular-baseline"),
        })
        .collect();
    (plan, rows)
}

#[test]
fn documented_ope_golden_vector_is_exact() {
    let (plan, rows) = fixture();
    let result = must(estimate_ope(&plan, &rows));
    assert_eq!(
        (
            result.ips.raw(),
            result.snips.raw(),
            result.doubly_robust.raw(),
            result.effective_sample_size.raw(),
            result.maximum_observed_weight.raw()
        ),
        (3221225472, 2576980378, 3221225472, 12632256753, 8589934592)
    );
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn row_and_candidate_permutations_preserve_every_receipt_field() {
    let (plan, mut rows) = fixture();
    let expected = must(estimate_ope(&plan, &rows));
    rows.reverse();
    for row in &mut rows {
        row.actions.reverse();
    }
    assert_eq!(must(estimate_ope(&plan, &rows)), expected);
}

#[test]
fn nonzero_outcome_model_uses_residual_correction() {
    let (plan, mut rows) = fixture();
    for row in &mut rows {
        for action in &mut row.actions {
            action.predicted_outcome = FixedQ32::from_raw(1 << 31);
        }
    }
    let result = must(estimate_ope(&plan, &rows));
    assert_eq!(result.doubly_robust.raw(), 2684354560); // 0.625
    assert_eq!(result.ips.raw(), 3221225472);
}

#[test]
fn pending_outcome_is_not_zero_reward() {
    let (plan, mut rows) = fixture();
    rows[0].finalized_outcome = None;
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::PendingOutcome));
}

#[test]
fn outcome_after_frozen_watermark_is_rejected() {
    let (plan, mut rows) = fixture();
    rows[0].outcome_observed_at = 101;
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::OutcomeAfterWatermark)
    );
}

#[test]
fn unsupported_unchosen_action_is_also_rejected() {
    let (plan, mut rows) = fixture();
    rows[0].actions[0].behavior_probability = ProbabilityQ32::ONE;
    rows[0].actions[1].behavior_probability = ProbabilityQ32::ZERO;
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::UnsupportedAction));
}

#[test]
fn incomplete_candidates_and_unknown_choice_are_rejected() {
    let (plan, mut rows) = fixture();
    rows[0].complete_candidates = false;
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::IncompleteCandidates)
    );
    rows[0].complete_candidates = true;
    rows[0].chosen_action = id("not-in-set");
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::UnknownChosenAction)
    );
}

#[test]
fn duplicate_observations_cannot_inflate_sample_count() {
    let (plan, mut rows) = fixture();
    rows[1].decision_id = rows[0].decision_id.clone();
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::DuplicateDecision));
}

#[test]
fn distribution_and_weight_gates_are_enforced() {
    let (mut plan, mut rows) = fixture();
    rows[0].actions[1].behavior_probability = ProbabilityQ32::ONE;
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::InvalidDistribution)
    );
    let (_, rows) = fixture();
    plan.maximum_weight = FixedQ32::ONE;
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::WeightLimit));
}

#[test]
fn exact_weight_ceiling_cannot_be_weakened_by_q32_rounding() {
    let (mut plan, mut rows) = fixture();
    plan.maximum_weight = FixedQ32::from_raw(5 << 30);
    for offset in [0_u64, 1] {
        // At offset zero the chosen ratio is exactly 5/4. At offset one it
        // exceeds 5/4 by 1/(3*2^32-4), less than half one raw Q32 unit.
        let behavior = (3 << 30) - offset;
        let evaluation = (15 << 28) - offset;
        for row in &mut rows {
            row.actions[0].behavior_probability = must(ProbabilityQ32::from_raw(behavior));
            row.actions[0].evaluation_probability = must(ProbabilityQ32::from_raw(evaluation));
            row.actions[1].behavior_probability = must(ProbabilityQ32::from_raw(
                ProbabilityQ32::ONE.raw() - behavior,
            ));
            row.actions[1].evaluation_probability = must(ProbabilityQ32::from_raw(
                ProbabilityQ32::ONE.raw() - evaluation,
            ));
        }
        if offset == 0 {
            let estimate = must(estimate_ope(&plan, &rows));
            assert_eq!(estimate.maximum_observed_weight, plan.maximum_weight);
        } else {
            assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::WeightLimit));
        }
    }
}

#[test]
fn effective_sample_size_cannot_be_replaced_by_raw_row_count() {
    let (mut plan, rows) = fixture();
    plan.minimum_ess = FixedQ32::from_raw(3 << 32);
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::InsufficientSupport)
    );
}

#[test]
fn exact_ess_floor_cannot_be_weakened_by_q32_rounding() {
    let (mut plan, template) = fixture();
    plan.minimum_rows = 400;
    plan.minimum_ess = FixedQ32::from_raw(400 << 32);
    let mut rows = Vec::new();
    for index in 0..400 {
        let mut row = template[0].clone();
        row.decision_id = id(&format!("ess-boundary-{index}"));
        for action in &mut row.actions {
            action.behavior_probability = probability(/*quarters*/ 2);
            action.evaluation_probability = probability(/*quarters*/ 2);
        }
        rows.push(row);
    }
    let exact = must(estimate_ope(&plan, &rows));
    assert_eq!(exact.effective_sample_size, plan.minimum_ess);

    // Weights are 399 copies of 1 and one copy of 1 - 32768/2^32.
    // ESS is strictly below 400 by about 0.249375 raw Q32 units, so the
    // required nearest-even report remains 400 while that floor must reject.
    rows[0].actions[0].evaluation_probability = must(ProbabilityQ32::from_raw((1 << 31) - 16_384));
    rows[0].actions[1].evaluation_probability = must(ProbabilityQ32::from_raw((1 << 31) + 16_384));
    assert_eq!(
        estimate_ope(&plan, &rows),
        Err(OpeError::InsufficientSupport)
    );

    plan.minimum_ess = FixedQ32::from_raw((400 << 32) - 1);
    let supported = must(estimate_ope(&plan, &rows));
    assert_eq!(supported.effective_sample_size, exact.effective_sample_size);

    plan.minimum_ess = FixedQ32::from_raw(400 << 32);
    let mut extra = rows[1].clone();
    extra.decision_id = id("ess-boundary-extra");
    rows.push(extra);
    assert_eq!(
        must(estimate_ope(&plan, &rows)).effective_sample_size.raw(),
        401 << 32
    );
}

#[test]
fn scaled_ratio_preserves_exact_floor_and_ties_even_at_wide_bounds() {
    let cases = [
        (0, i128::MAX, 0, 0),
        (1, 2, SCALE / 2, SCALE / 2),
        (3, 2 * SCALE, 1, 2),
        (5, 2 * SCALE, 2, 2),
        (1 << 126, 1 << 125, 2 * SCALE, 2 * SCALE),
        (i128::MAX, i128::MAX, SCALE, SCALE),
        (i128::MAX - 1, i128::MAX, SCALE - 1, SCALE),
        (i128::MAX, i128::MAX - 1, SCALE, SCALE),
    ];
    for (numerator, denominator, floor, rounded) in cases {
        assert_eq!(
            must(scaled_ratio(numerator, denominator)),
            ScaledRatio { floor, rounded }
        );
    }
    for (numerator, denominator) in [(0, 0), (1, -1), (-1, 1), (i128::MAX, 1)] {
        assert_eq!(
            scaled_ratio(numerator, denominator),
            Err(OpeError::Arithmetic)
        );
    }
}

#[test]
fn missing_evidence_and_out_of_range_outcomes_are_rejected() {
    let (plan, mut rows) = fixture();
    rows[0].outcome_evidence = Digest32::ZERO;
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::MissingEvidence));
    rows[0].outcome_evidence = Digest32::of_bytes(b"observer");
    rows[0].finalized_outcome = Some(FixedQ32::from_raw(-1));
    assert_eq!(estimate_ope(&plan, &rows), Err(OpeError::InvalidOutcome));
}

#[test]
fn signed_rounding_is_ties_to_even() {
    assert_eq!(must(round_ratio(5, 2)), 2);
    assert_eq!(must(round_ratio(7, 2)), 4);
    assert_eq!(must(round_ratio(-5, 2)), -2);
    assert_eq!(must(round_ratio(-7, 2)), -4);
}

#[test]
fn tiny_supported_weights_retain_exact_ess() {
    let (mut plan, mut rows) = fixture();
    plan.minimum_ess = FixedQ32::from_raw(4 << 32);
    for row in &mut rows {
        row.actions[0].behavior_probability = probability(2);
        row.actions[1].behavior_probability = probability(2);
        row.actions[0].evaluation_probability = must(ProbabilityQ32::from_raw(1));
        row.actions[1].evaluation_probability = must(ProbabilityQ32::from_raw((1 << 32) - 1));
        row.finalized_outcome = Some(FixedQ32::ONE);
    }
    let result = must(estimate_ope(&plan, &rows));
    assert_eq!(result.effective_sample_size.raw(), 4 << 32);
    assert_eq!(result.ips.raw(), 2);
    assert_eq!(result.snips, FixedQ32::ONE);
}
