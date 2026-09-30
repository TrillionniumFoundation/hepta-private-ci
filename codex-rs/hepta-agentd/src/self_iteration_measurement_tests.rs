//! Real V2 files with deterministic test model receipts. Assertions concern
//! physical execution/retention; no test receipt is production qualification.
use super::*;
use crate::neuron_runtime_v2::lock_metrics_tests::runtime_fixture;
use std::sync::atomic::Ordering;

#[test]
fn original_measurements_and_retained_commits_survive_replay_without_model_redispatch() {
    let baseline = runtime_fixture(1, Duration::from_micros(200), Duration::ZERO);
    let candidate = runtime_fixture(2, Duration::from_micros(400), Duration::ZERO);
    let mut baseline_port = baseline.canonical.clone();
    let mut candidate_port = candidate.canonical.clone();
    baseline_port.budget_micros = 10_000_000;
    candidate_port.budget_micros = 10_000_000;
    let cases = vec![AgentdSelfIterationQualificationCaseV1 {
        case_id: StableId::new("test.holdout.case").expect("id"),
        baseline_tick: baseline.input.clone(),
        candidate_tick: candidate.input.clone(),
        baseline_port,
        candidate_port,
    }];
    let cancellation = CancellationToken::new();
    let first = measure_self_iteration_qualification_v1(
        &baseline.handle,
        &candidate.handle,
        &cases,
        baseline.input.objective_digest,
        Duration::from_secs(30),
        &cancellation,
    )
    .expect("physical original measurement");
    assert_eq!(baseline.calls.load(Ordering::SeqCst), 1);
    assert_eq!(candidate.calls.load(Ordering::SeqCst), 1);
    assert!(!first[0].baseline_replayed);
    assert!(!first[0].candidate_replayed);
    assert!(first[0].guarded_retention_verified);
    assert!(!first[0].authority.grants_any());
    assert_eq!(first[0].baseline_model_latency_micros, 200);
    assert_eq!(first[0].candidate_model_latency_micros, 400);
    let replay = measure_self_iteration_qualification_v1(
        &baseline.handle,
        &candidate.handle,
        &cases,
        baseline.input.objective_digest,
        Duration::from_secs(30),
        &cancellation,
    )
    .expect("guarded existing receipts");
    assert_eq!(baseline.calls.load(Ordering::SeqCst), 1);
    assert_eq!(candidate.calls.load(Ordering::SeqCst), 1);
    assert!(replay[0].baseline_replayed);
    assert!(replay[0].candidate_replayed);
    assert_eq!(replay[0].baseline, first[0].baseline);
    assert_eq!(replay[0].candidate, first[0].candidate);
    assert_eq!(replay[0].candidate_model_latency_micros, 400);
}

#[test]
fn cancellation_and_dataset_binding_fail_before_physical_execution() {
    let baseline = runtime_fixture(1, Duration::ZERO, Duration::ZERO);
    let candidate = runtime_fixture(2, Duration::ZERO, Duration::ZERO);
    let mut baseline_port = baseline.canonical.clone();
    let mut candidate_port = candidate.canonical.clone();
    baseline_port.budget_micros = 10_000_000;
    candidate_port.budget_micros = 10_000_000;
    let mut cases = vec![AgentdSelfIterationQualificationCaseV1 {
        case_id: StableId::new("test.holdout.case").expect("id"),
        baseline_tick: baseline.input.clone(),
        candidate_tick: candidate.input.clone(),
        baseline_port,
        candidate_port,
    }];
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    assert!(
        measure_self_iteration_qualification_v1(
            &baseline.handle,
            &candidate.handle,
            &cases,
            baseline.input.objective_digest,
            Duration::from_secs(30),
            &cancellation
        )
        .is_err()
    );
    cases[0].candidate_tick.input_feature_digest =
        Digest32::of_bytes(b"substituted dataset feature");
    assert!(
        measure_self_iteration_qualification_v1(
            &baseline.handle,
            &candidate.handle,
            &cases,
            baseline.input.objective_digest,
            Duration::from_secs(30),
            &CancellationToken::new()
        )
        .is_err()
    );
    assert_eq!(baseline.calls.load(Ordering::SeqCst), 0);
    assert_eq!(candidate.calls.load(Ordering::SeqCst), 0);
}
