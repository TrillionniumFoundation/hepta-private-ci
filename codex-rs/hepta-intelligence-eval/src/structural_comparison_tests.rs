use super::*;

fn d(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn i(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn plan() -> FrozenStructuralComparisonV1 {
    FrozenStructuralComparisonV1 {
        candidate_id: i("candidate:split"),
        predecessor_id: i("predecessor:current"),
        no_change_id: i("candidate:no-change"),
        mutation: StructuralMutationKindV1::Split,
        topology_admission_digest: d(b"admission"),
        objective_digest: d(b"objective"),
        rollback_plan_digest: d(b"rollback"),
        generation: 1,
        frozen_plan_digest: d(b"plan"),
        dataset_digest: d(b"dataset"),
        metric_policy_digest: d(b"policy"),
        frozen_at_unix_ms: 1,
        future_start_unix_ms: 2,
        future_end_unix_ms: 3,
        maximum_compute_increase_ppm: 0,
        maximum_latency_increase_ppm: 0,
        maximum_rss_increase_ppm: 0,
        maximum_negative_transfer_ppm: 0,
        maximum_retention_loss_ppm: 0,
        minimum_ablation_delta_q24: 1,
    }
}

fn result() -> StructuralComparisonObservationV1 {
    StructuralComparisonObservationV1 {
        candidate_utility_q24: 11,
        predecessor_utility_q24: 10,
        no_change_utility_q24: 10,
        ablated_utility_q24: 9,
        candidate_compute_units: 100,
        matched_baseline_compute_units: 100,
        candidate_latency_p95_us: 100,
        baseline_latency_p95_us: 100,
        candidate_rss_peak_bytes: 1_000,
        baseline_rss_peak_bytes: 1_000,
        candidate_throughput_q24: 20,
        baseline_throughput_q24: 20,
        negative_transfer_ppm: 0,
        retention_loss_ppm: 0,
        recovery_observation_digest: d(b"recovery"),
        rollback_observation_digest: d(b"rollback"),
        holdout_observation_digest: d(b"holdout"),
        rollback_verified: true,
        recovery_verified: true,
    }
}

#[test]
fn matched_compute_and_ablation_are_strict() {
    let plan = plan();
    let observed = result();
    assert!(passes(&plan, &observed));
    let mut changed = observed.clone();
    changed.candidate_compute_units += 1;
    assert!(!passes(&plan, &changed));
    let mut changed = observed.clone();
    changed.ablated_utility_q24 = observed.candidate_utility_q24;
    assert!(!passes(&plan, &changed));
    let mut changed = observed.clone();
    changed.retention_loss_ppm = 1;
    assert!(!passes(&plan, &changed));
    let mut changed = observed.clone();
    changed.recovery_verified = false;
    assert!(!passes(&plan, &changed));
}

#[test]
fn frozen_plan_future_window_and_observations_are_signed() {
    let plan = plan();
    let observed = result();
    let exact = structural_comparison_signing_payload_v1(&plan, &observed).unwrap();
    let mut changed = observed.clone();
    changed.candidate_utility_q24 += 1;
    assert_ne!(
        structural_comparison_signing_payload_v1(&plan, &changed).unwrap(),
        exact
    );
    let mut invalid = plan.clone();
    invalid.future_start_unix_ms = invalid.frozen_at_unix_ms;
    assert_eq!(
        structural_comparison_signing_payload_v1(&invalid, &observed),
        Err(StructuralComparisonErrorV1::InvalidDesign)
    );
}
