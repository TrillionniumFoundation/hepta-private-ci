use super::AppServerDrainHandle;

#[test]
fn repeated_drain_requests_preserve_the_real_completion_acknowledgement() {
    let handle = AppServerDrainHandle::new();
    assert!(!handle.drained());
    handle.request_drain();
    assert!(!handle.drained());
    handle.mark_drained();
    assert!(handle.drained());
    handle.request_drain();
    handle.request_drain();
    assert!(handle.drained());
    assert_eq!(handle.running_turns(), 0);
}

#[test]
fn requesting_drain_does_not_acknowledge_outstanding_turns() {
    let handle = AppServerDrainHandle::new();
    handle.observe_running_turns(2);
    handle.request_drain();
    handle.request_drain();
    assert!(!handle.drained());
    assert_eq!(handle.running_turns(), 2);
}
