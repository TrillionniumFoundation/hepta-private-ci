use super::*;

#[test]
fn repeat_close_cannot_extend_the_deadline_or_authorize_an_update() {
    let start = Instant::now();
    let mut shutdown = Shutdown {
        update_requested: true,
        ..Shutdown::default()
    };
    shutdown.request(start);
    shutdown.request(start + Duration::from_secs(119));
    assert!(!shutdown.activation_allowed());
    shutdown.check_deadline(start + SHUTDOWN_GRACE);
    assert!(shutdown.failure.is_some());
    assert!(!shutdown.update_requested);
    shutdown.runtime_closed = true;
    assert!(!shutdown.activation_allowed());
}

#[test]
fn activation_requires_successful_close_and_no_shutdown_failure() {
    let mut shutdown = Shutdown {
        update_requested: true,
        ..Shutdown::default()
    };
    assert!(!shutdown.activation_allowed());
    shutdown.runtime_closed = true;
    assert!(shutdown.activation_allowed());
    shutdown.failure = Some("runtime close failed".to_owned());
    assert!(!shutdown.activation_allowed());
}
