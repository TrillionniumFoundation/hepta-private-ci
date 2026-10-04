use super::*;
use crate::evaluation_signing_payload_v1;
use crate::evaluation_signing_payload_v2;

fn roles(count: usize) -> Vec<MetricRoleContractV2> {
    (0..count)
        .map(|index| MetricRoleContractV2 {
            metric_id: id(&format!("metric-{index:03}")),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        })
        .collect()
}

#[test]
fn signing_payload_rejects_oversized_metrics_before_serialization() {
    let mut value = bundle();
    value.metrics = (0..=MAX_METRICS)
        .map(|index| MetricGateV1 {
            metric_id: id(&format!("metric-{index:03}")),
            ..metric()
        })
        .collect();
    assert_eq!(
        evaluation_signing_payload_v1(&value),
        Err(EvaluationClosureError::MetricLimit)
    );
    assert_eq!(
        evaluation_signing_payload_v2(&value, &roles(MAX_METRICS)),
        Err(EvaluationClosureError::MetricLimit)
    );
}

#[test]
fn signing_payload_rejects_oversized_snapshot_lineage() {
    let mut value = bundle();
    value.snapshot_ids = vec![id("lineage-entry"); MAX_LINEAGE_IDS + 1];
    assert_eq!(
        evaluation_signing_payload_v1(&value),
        Err(EvaluationClosureError::FoldLineageLimit)
    );
}

#[test]
fn signing_payload_rejects_oversized_window_lineage() {
    let mut value = bundle();
    value.future_window_ids = vec![id("lineage-entry"); MAX_LINEAGE_IDS + 1];
    assert_eq!(
        evaluation_signing_payload_v1(&value),
        Err(EvaluationClosureError::FoldLineageLimit)
    );
}

#[test]
fn role_signing_rejects_oversized_roles_before_copying_them() {
    assert_eq!(
        evaluation_signing_payload_v2(&bundle(), &roles(MAX_METRICS + 1)),
        Err(EvaluationClosureError::MetricLimit)
    );
}

#[test]
fn plan_freezing_rejects_oversized_roles_before_contract_copying() {
    assert_eq!(
        freeze_cross_fold_plan_v2(plan(), roles(MAX_METRICS + 1)),
        Err(EvaluationClosureError::MetricLimit)
    );
}

#[test]
fn maximum_metric_count_remains_supported_for_freezing_and_signing() {
    let roles = roles(MAX_METRICS);
    let mut plan = plan();
    plan.metric_contracts = roles
        .iter()
        .map(|role| MetricContractV1 {
            metric_id: role.metric_id.clone(),
            ..metric_contract()
        })
        .collect();
    let frozen = freeze_cross_fold_plan_v2(plan, roles.clone()).expect("maximum-size plan");
    let mut value = bundle();
    value.frozen_plan = frozen;
    value.metrics = roles
        .iter()
        .map(|role| MetricGateV1 {
            metric_id: role.metric_id.clone(),
            ..metric()
        })
        .collect();
    assert!(evaluation_signing_payload_v1(&value).is_ok());
    assert!(evaluation_signing_payload_v2(&value, &roles).is_ok());
}
