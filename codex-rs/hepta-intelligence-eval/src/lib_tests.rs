use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::*;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn request() -> EvaluationRequest {
    EvaluationRequest {
        evaluation_id: id("eval-1"),
        evaluator_id: id("independent-eval"),
        candidate_id: id("candidate"),
        candidate_producer_id: id("producer"),
        baseline_id: id("baseline"),
        objective_digest: Digest32::of_bytes(b"objective"),
        comparisons: vec![MetricComparison {
            metric_id: id("safety"),
            direction: Direction::Minimize,
            candidate: FixedQ32::ZERO,
            baseline: FixedQ32::ONE,
            minimum_delta: FixedQ32::ZERO,
            hard: true,
            support_digest: Digest32::of_bytes(b"evidence"),
        }],
    }
}

#[test]
fn eligible_is_not_promotion() {
    assert_eq!(
        must(evaluate(request())).disposition,
        Disposition::EligibleForFurtherReview
    );
}

#[test]
fn self_evaluation_is_rejected() {
    let mut value = request();
    value.evaluator_id = value.candidate_producer_id.clone();
    assert_eq!(evaluate(value), Err(Error::SelfEvaluation));
}

#[test]
fn hard_regression_is_rejected() {
    let mut value = request();
    value.comparisons[0].candidate = FixedQ32::ONE;
    value.comparisons[0].baseline = FixedQ32::ZERO;
    assert_eq!(must(evaluate(value)).disposition, Disposition::Ineligible);
}

#[test]
fn every_registered_threshold_is_enforced() {
    let mut value = request();
    value.comparisons[0].metric_id = id("latency");
    value.comparisons[0].hard = false;
    value.comparisons[0].candidate = FixedQ32::ONE;
    value.comparisons[0].baseline = FixedQ32::ZERO;
    let receipt = must(evaluate(value));
    assert_eq!(receipt.disposition, Disposition::Ineligible);
    assert_eq!(receipt.failed_metrics, vec![id("latency")]);
}

#[test]
fn registered_hard_regression_allowance_is_enforced_exactly() {
    let mut at_floor = request();
    at_floor.comparisons[0].minimum_delta = FixedQ32::from_raw(-2);
    at_floor.comparisons[0].candidate = FixedQ32::from_raw(2);
    at_floor.comparisons[0].baseline = FixedQ32::ZERO;
    let receipt = must(evaluate(at_floor));
    assert_eq!(receipt.disposition, Disposition::EligibleForFurtherReview);
    assert!(receipt.failed_metrics.is_empty());

    let mut below_floor = request();
    below_floor.comparisons[0].minimum_delta = FixedQ32::from_raw(-2);
    below_floor.comparisons[0].candidate = FixedQ32::from_raw(3);
    below_floor.comparisons[0].baseline = FixedQ32::ZERO;
    let receipt = must(evaluate(below_floor));
    assert_eq!(receipt.disposition, Disposition::Ineligible);
    assert_eq!(receipt.failed_metrics, vec![id("safety")]);
}

#[test]
fn unrepresentable_metric_deltas_fail_closed() {
    for (direction, candidate, baseline) in [
        (Direction::Maximize, i64::MAX, i64::MIN),
        (Direction::Maximize, i64::MIN, i64::MAX),
        (Direction::Minimize, i64::MIN, i64::MAX),
        (Direction::Minimize, i64::MAX, i64::MIN),
    ] {
        let mut value = request();
        value.comparisons[0].direction = direction;
        value.comparisons[0].candidate = FixedQ32::from_raw(candidate);
        value.comparisons[0].baseline = FixedQ32::from_raw(baseline);
        assert_eq!(evaluate(value), Err(Error::Arithmetic));
    }
}

#[test]
fn receipt_digest_binds_threshold_metadata_in_canonical_order() {
    let mut value = request();
    let mut latency = value.comparisons[0].clone();
    latency.metric_id = id("latency");
    latency.hard = false;
    value.comparisons.push(latency);

    let original = must(evaluate(value.clone()));
    let mut permuted = value.clone();
    permuted.comparisons.reverse();
    assert_eq!(must(evaluate(permuted)), original);

    let mut reclassified = value.clone();
    reclassified.comparisons[0].hard = false;
    let reclassified = must(evaluate(reclassified));
    assert_eq!(reclassified.disposition, original.disposition);
    assert_ne!(reclassified.evidence_digest, original.evidence_digest);

    value.comparisons[0].minimum_delta = FixedQ32::from_raw(-1);
    let relaxed = must(evaluate(value));
    assert_eq!(relaxed.disposition, original.disposition);
    assert_ne!(relaxed.evidence_digest, original.evidence_digest);
}

#[test]
fn missing_support_is_insufficient() {
    let mut value = request();
    value.comparisons[0].support_digest = Digest32::ZERO;
    assert_eq!(
        must(evaluate(value)).disposition,
        Disposition::InsufficientEvidence
    );
}
