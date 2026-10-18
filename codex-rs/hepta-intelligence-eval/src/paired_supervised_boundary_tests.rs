use crate::paired_supervised_estimate::estimate_paired_cut;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use crate::*;
use codex_hepta_types::FixedQ32;

#[test]
fn paired_supervised_preserves_single_private_gold_consistency_for_both_policies() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    for case in 0..2 {
        let mut cut = signing.cut(&plan).cut;
        cut.rows[0].baseline.outcome = PairedClassObservationV1::Label {
            class_id: id(if case == 0 { "SUPPORT" } else { "CONTRADICT" }),
            correct: case != 0,
        };
        assert!(estimate_paired_cut(&plan, &cut).is_err());
    }
}

#[test]
fn paired_supervised_freezes_three_distinct_observed_evidence_dimensions() {
    for case in 0..3 {
        let mut value = inputs(128);
        match case {
            0 => {
                value.policy.required_evidence_metrics.retention = id("accuracy");
            }
            1 => {
                value.policy.required_evidence_metrics.unlearning = id("retention");
            }
            _ => {
                value.metrics[1].kind = PairedMetricKindV1::ObservedBounded {
                    minimum: FixedQ32::ZERO,
                    maximum: FixedQ32::ONE,
                };
            }
        }
        assert!(freeze_paired_supervised_plan_v1(value).is_err());
    }
}

#[test]
fn paired_supervised_rejects_omitted_graph_membership_or_scored_as_bridge_overlap() {
    for case in 0..2 {
        let mut value = inputs(128);
        match case {
            0 => {
                value.folds[0].holdout_records = vec![digest("row-2")];
            }
            _ => {
                value.unscored_source_records = vec![digest("row-2")];
            }
        }
        assert!(freeze_paired_supervised_plan_v1(value).is_err());
    }
}

#[test]
fn paired_supervised_cost_comes_from_original_monotonic_measurement_not_scalar_submission() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let mut cut = signing.cut(&plan).cut;
    let original = estimate_paired_cut(&plan, &cut).unwrap();
    for row in &mut cut.rows {
        row.candidate.original_elapsed_micros = Some(5_000);
    }
    let changed = estimate_paired_cut(&plan, &cut).unwrap();
    let before = original
        .metrics()
        .iter()
        .find(|m| m.metric_id == id("latency"))
        .unwrap();
    let after = changed
        .metrics()
        .iter()
        .find(|m| m.metric_id == id("latency"))
        .unwrap();
    assert_eq!(
        after.candidate.upper.raw() - before.candidate.upper.raw(),
        4_i64 << 32
    );
    let mut injected = signing.cut(&plan).cut;
    injected.rows[0]
        .observed_metrics
        .push(PairedObservedMetricV1 {
            metric_id: id("latency"),
            candidate: Some(FixedQ32::ZERO),
            baseline: Some(FixedQ32::ONE),
        });
    assert!(estimate_paired_cut(&plan, &injected).is_err());
}

#[test]
fn paired_supervised_original_elapsed_unknown_is_censored_and_not_zero_cost() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let mut cut = SigningFixture::new(false).cut(&plan).cut;
    cut.rows[0].candidate.original_elapsed_micros = None;
    assert!(matches!(
        estimate_paired_cut(&plan, &cut),
        Err(PairedSupervisedErrorV1::Incomplete {
            tasks: 128,
            censored: 1
        })
    ));
    cut.rows[0].candidate.original_elapsed_micros = Some(11_000);
    assert!(estimate_paired_cut(&plan, &cut).is_err());
}
