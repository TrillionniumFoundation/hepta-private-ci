//! Error propagation tests for the actual product recovery accumulator.

use super::*;

#[test]
fn retryable_unknown_lane_failure_is_retained_without_short_circuiting_terminal_work() {
    let mut first_error = None;
    retain_recovery_result(
        Err(AgentdError::Protocol(
            "automation queue reconcile failed: closed".to_string(),
        )),
        &mut first_error,
    )
    .expect("continue the reserved terminal lane");
    retain_recovery_result(Ok(()), &mut first_error).expect("terminal work can complete");
    assert!(matches!(first_error, Some(AgentdError::Protocol(_))));
}

#[test]
fn fatal_or_fenced_recovery_stops_even_after_an_earlier_retryable_error() {
    for error in [
        AutomationError::TimerFenced,
        AutomationError::AccessDenied,
        AutomationError::Corrupt,
        AutomationError::Invalid,
    ] {
        let mut first_error = Some(AgentdError::Automation(AutomationError::Unavailable));
        let result = retain_recovery_result(
            Err(AgentdError::Automation(error.clone())),
            &mut first_error,
        );
        assert!(matches!(result, Err(AgentdError::Automation(observed)) if observed == error));
    }
}

#[test]
fn taskflow_error_classes_survive_the_product_recovery_boundary() {
    use codex_hepta_automation::TaskFlowError;
    for (error, expected) in [
        (
            TaskFlowError::StaleFence,
            AutomationFailureDisposition::Fence,
        ),
        (
            TaskFlowError::Corrupt("damaged chain".to_string()),
            AutomationFailureDisposition::FailStop,
        ),
        (
            TaskFlowError::Invalid("invalid command".to_string()),
            AutomationFailureDisposition::FailStop,
        ),
        (
            TaskFlowError::Conflict("changed revision".to_string()),
            AutomationFailureDisposition::Isolate,
        ),
        (
            TaskFlowError::Unavailable,
            AutomationFailureDisposition::Retry,
        ),
    ] {
        assert_eq!(
            crate::automation::classify_recovery_error(&taskflow_error(error)),
            expected
        );
    }
}
