use super::*;

#[test]
fn ready_events_cannot_bypass_cancel_or_an_expired_deadline() {
    let cancellation = CancellationToken::new();
    let future_deadline = Instant::now() + std::time::Duration::from_secs(10);
    check_observation_boundary(future_deadline, &cancellation).unwrap();
    assert_eq!(
        check_observation_boundary(Instant::now(), &cancellation),
        Err(LOCAL_DEADLINE_ELAPSED.to_string())
    );
    cancellation.cancel();
    assert_eq!(
        check_observation_boundary(future_deadline, &cancellation),
        Err(LOCAL_CANCELLED.to_string())
    );
}
