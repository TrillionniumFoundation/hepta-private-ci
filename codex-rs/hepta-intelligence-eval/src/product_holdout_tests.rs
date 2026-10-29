//! Regression controls for the original product runner, not model efficacy.
use pretty_assertions::assert_eq;

use super::*;

type LineageChange = (&'static str, fn(&mut TemporalComparisonInputsV1));

fn runner() -> ProductEvaluationRunnerV1<MemoryCas> {
    ProductEvaluationRunnerV1::new(
        FencedFinalHoldoutOwnerV1::initialize(
            MemoryCas::default(),
            digest("frozen-lineage-holdout-owner"),
            HoldoutWriterFenceV1 {
                owner_id: id("evaluation-owner"),
                generation: 1,
                lease_digest: digest("lease-1"),
            },
        )
        .unwrap(),
    )
}

#[test]
fn product_runner_accepts_exact_frozen_lineage_in_any_row_order() {
    let mut fixture = fixture();
    let frozen = freeze_product_evaluation_plan_v1(
        fixture.cross_fold.clone(),
        fixture.roles,
        fixture.sources,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .unwrap();
    let original = fixture.provider.inputs.clone().unwrap();
    let mut first = runner();
    let expected = first
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        )
        .unwrap();
    let mut reordered = original;
    reordered.training.reverse();
    reordered.targets.reverse();
    reordered.candidate_observations.reverse();
    reordered.baseline_observations.reverse();
    reordered.assignments.reverse();
    fixture.provider.inputs = Some(reordered);
    let actual = runner()
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        )
        .unwrap();
    assert_eq!(actual, expected);
}

#[test]
fn product_runner_rejects_changed_released_lineage_without_refunding_holdout() {
    let changes: [LineageChange; 7] = [
        ("training principal", |inputs| {
            inputs.training[0].principal_lineage = id("replacement-training-principal")
        }),
        ("training episode", |inputs| {
            inputs.training[0].episode_lineage = id("replacement-training-episode")
        }),
        ("training window", |inputs| {
            inputs.training[0].window_id = id("replacement-training-window")
        }),
        ("holdout principal", |inputs| {
            inputs.targets[0].principal_lineage = id("replacement-holdout-principal")
        }),
        ("holdout episode", |inputs| {
            inputs.targets[0].episode_lineage = id("replacement-holdout-episode")
        }),
        ("omitted holdout unit", |inputs| {
            inputs.targets.pop();
            inputs.candidate_observations.pop();
            inputs.baseline_observations.pop();
            inputs.assignments.pop();
        }),
        ("undeclared shared unit", |inputs| {
            inputs.targets[0].principal_lineage = inputs.targets[1].principal_lineage.clone();
            inputs.targets[0].episode_lineage = inputs.targets[1].episode_lineage.clone();
            inputs.assignments[0].cluster_id = inputs.assignments[1].cluster_id.clone();
        }),
    ];
    for (name, change) in changes {
        let mut fixture = fixture();
        let frozen = freeze_product_evaluation_plan_v1(
            fixture.cross_fold.clone(),
            fixture.roles.clone(),
            fixture.sources.clone(),
            &fixture.candidate_plan,
            &fixture.baseline_plan,
        )
        .unwrap();
        let original = fixture.provider.inputs.clone();
        change(fixture.provider.inputs.as_mut().unwrap());
        let mut runner = runner();
        let result = runner.evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        );
        assert!(
            matches!(
                result,
                Err(ProductEvaluationError::Binding("frozen final fold lineage"))
            ),
            "{name}: {result:?}"
        );
        assert_eq!(fixture.provider.release_count, 1);
        let consumed = runner.holdout_anchor();
        assert_eq!(consumed.record_count, 1);
        // Exact replay is an existing recovery path. A new plan cannot reuse
        // the consumed material after seeing an unsuccessful first release.
        fixture.provider.inputs = original;
        fixture.cross_fold.plan_id = id("replacement-plan-after-rejection");
        let replacement = freeze_product_evaluation_plan_v1(
            fixture.cross_fold,
            fixture.roles,
            fixture.sources,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
        )
        .unwrap();
        let retry = runner.evaluate_temporal_comparison(
            &replacement,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        );
        assert!(
            retry.is_err(),
            "{name}: a rejected release must not refund the consumed holdout"
        );
        assert_eq!(fixture.provider.release_count, 1);
        assert_eq!(runner.holdout_anchor(), consumed);
    }
}
