use super::*;
use std::time::Duration;

#[test]
fn histogram_retains_failures_without_global_lock() {
    let histogram = PhaseLatencyHistogramV1::default();
    histogram.observe(Duration::from_micros(1), true);
    histogram.observe(Duration::from_micros(7), false);
    let observation = histogram.snapshot();
    assert_eq!(observation.observations, 2);
    assert_eq!(observation.failures, 1);
    assert_eq!(observation.max_micros, 7);
    assert!(observation.p50_bound_micros >= 1);
    assert!(observation.p95_bound_micros >= 7);
    assert!(observation.p99_bound_micros >= 7);
}

#[test]
fn timed_owner_result_preserves_failure_and_value() {
    let histogram = PhaseLatencyHistogramV1::default();
    let success = histogram.time_value(|| 9_u64);
    assert_eq!(success, 9);
    let failure = histogram.time_result(|| Err::<(), &str>("fenced"));
    assert_eq!(failure, Err("fenced"));
    assert_eq!(histogram.snapshot().observations, 2);
    assert_eq!(histogram.snapshot().failures, 1);
}
