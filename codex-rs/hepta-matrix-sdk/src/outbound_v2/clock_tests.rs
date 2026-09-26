use std::time::Duration;

use super::DispatchClock;
use super::OutboxDispatchError;

#[tokio::test]
async fn elapsed_work_advances_observation_time() {
    let clock = DispatchClock::new(100);
    let before = clock.now_ms().expect("initial clock");
    tokio::time::sleep(Duration::from_millis(20)).await;
    let after = clock.now_ms().expect("elapsed clock");
    assert!(after >= before + 20);
}

#[tokio::test]
async fn repeated_deadline_reads_do_not_renew_the_lease() {
    let clock = DispatchClock::new(100);
    let first = clock.deadline(10_100).expect("live lease");
    tokio::time::sleep(Duration::from_millis(10)).await;
    let second = clock.deadline(10_100).expect("same lease");
    assert_eq!(first, second);
}

#[tokio::test]
async fn elapsed_authorization_cannot_reopen_an_expired_lease() {
    let clock = DispatchClock::new(100);
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert_eq!(clock.deadline(110), Err(OutboxDispatchError::LeaseExpired));
    assert_eq!(clock.deadline(99), Err(OutboxDispatchError::LeaseExpired));
}

#[tokio::test]
async fn durable_time_overflow_is_rejected() {
    let clock = DispatchClock::new(i64::MAX as u64);
    tokio::time::sleep(Duration::from_millis(2)).await;
    assert_eq!(clock.now_ms(), Err(OutboxDispatchError::Invalid));
}
