use super::*;
use codex_hepta_automation::AutomationError;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn local_read_deadline_has_its_own_disposition() {
    assert_eq!(OBSERVATION_DEADLINE, Duration::from_secs(5));
    let stop = CancellationToken::new();
    let result = observe::<()>(
        std::future::pending(),
        Instant::now() + Duration::from_millis(10),
        &stop,
    )
    .await;
    assert!(matches!(result, Err(RecoveryError::ObservationDeadline)));
}

#[tokio::test]
async fn prior_cancellation_does_not_poll_the_network_operation() {
    let stop = CancellationToken::new();
    stop.cancel();
    let polled = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&polled);
    let result = observe(
        async move {
            observed.store(true, Ordering::SeqCst);
            Ok(())
        },
        Instant::now() + OBSERVATION_DEADLINE,
        &stop,
    )
    .await;
    assert!(matches!(result, Err(RecoveryError::Cancelled)));
    assert!(!polled.load(Ordering::SeqCst));
}

#[tokio::test]
async fn protocol_authority_and_corruption_errors_never_become_deferral() {
    let stop = CancellationToken::new();
    for error in [
        AgentdError::Protocol("remote peer says timed out".to_string()),
        AgentdError::GenerationFenced("changed owner".to_string()),
        AgentdError::Automation(AutomationError::Corrupt),
        AgentdError::Automation(AutomationError::AccessDenied),
    ] {
        let expected = error.to_string();
        let result = observe::<()>(
            async { Err(error) },
            Instant::now() + OBSERVATION_DEADLINE,
            &stop,
        )
        .await;
        let Err(RecoveryError::Fatal(actual)) = result else {
            panic!("real failures must retain fatal disposition");
        };
        assert_eq!(actual.to_string(), expected);
    }
}

#[test]
fn later_page_deadline_preserves_continuation_not_absence() {
    let result = deferred_turn_scan(1, Some("next-page".to_string()));
    assert!(matches!(result, Ok(TurnLookup::Continue(cursor)) if cursor == "next-page"));
    assert!(matches!(
        deferred_turn_scan(0, None),
        Err(RecoveryError::ObservationDeadline)
    ));
    assert!(matches!(
        deferred_turn_scan(1, None),
        Err(RecoveryError::Fatal(AgentdError::Protocol(_)))
    ));
}
