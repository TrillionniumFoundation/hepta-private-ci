use super::*;

#[test]
fn window_is_bounded_and_percentiles_are_nearest_rank() {
    let metrics = Metrics::default();
    for value in 1..=300 {
        metrics.record(Phase::FinalProof, Duration::from_micros(value));
    }
    let value = metrics.snapshot();
    assert_eq!(
        value["observations"]["final_proof"],
        serde_json::json!({
            "count": 300,
            "total_micros_saturating": 45150,
            "maximum_micros": 300,
            "retained_samples": 256,
            "p50_micros": 172,
            "p95_micros": 288,
            "p99_micros": 298,
        })
    );
}

#[test]
fn an_unobserved_phase_is_not_a_zero_latency_claim() {
    let metrics = Metrics::default();
    let value = metrics.snapshot();
    assert_eq!(value["observations"]["final_proof"]["count"], 0);
    assert!(value["observations"]["final_proof"]["p99_micros"].is_null());
    assert!(value["observations"]["final_proof"]["maximum_micros"].is_null());
}

#[test]
fn leaving_a_failed_phase_still_records_attempted_time() {
    let metrics = Metrics::default();
    let result: Result<(), &str> = (|| {
        let _sample = metrics.measure(Phase::PreSendPersistence);
        Err("fixture failure")
    })();
    assert!(result.is_err());
    assert_eq!(
        metrics.snapshot()["observations"]["pre_send_persistence"]["count"],
        1
    );
}

#[test]
fn diagnostics_do_not_hold_a_lock_across_measured_work() {
    let metrics = Metrics::default();
    let sample = metrics.measure(Phase::RequestPreparation);
    metrics.record(Phase::FinalProof, Duration::from_micros(3));
    assert_eq!(
        metrics.snapshot()["observations"]["final_proof"]["count"],
        1
    );
    drop(sample);
    assert_eq!(
        metrics.snapshot()["observations"]["request_preparation"]["count"],
        1
    );
}
