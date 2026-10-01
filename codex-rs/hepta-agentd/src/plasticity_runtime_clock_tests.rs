use super::*;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
#[test]
fn frozen_request_timestamp_cannot_freeze_current_host_time() {
    let clock = ControlledPlasticityRuntimeClockV1(AtomicU64::new(50));
    assert_eq!(admission_time(&clock, 50).unwrap(), 50);
    clock.0.store(90, Ordering::SeqCst);
    assert_eq!(admission_time(&clock, 50).unwrap(), 90);
    assert!(admission_time(&clock, 91).is_err());
}
