use super::*;
use pretty_assertions::assert_eq;

#[test]
fn absent_capability_is_not_implicitly_negotiated() {
    let request: InitializeParams = serde_json::from_value(serde_json::json!({
        "clientName": "legacy",
    }))
    .expect("legacy request");
    let response: InitializeResponse = serde_json::from_value(serde_json::json!({
        "sessionId": "legacy",
    }))
    .expect("legacy response");
    assert!(!request.process_exit_observation);
    assert!(!response.process_exit_observation);
}

#[test]
fn observation_failure_has_no_numeric_exit_or_sequence() {
    let notification = ExecObservationFailedNotification {
        process_id: ProcessId::from("original"),
        reason: ProcessObservationFailureReason::ExitObservationLost,
    };
    assert_eq!(
        serde_json::to_value(notification).expect("wire value"),
        serde_json::json!({
            "processId": "original", "reason": "exitObservationLost",
        })
    );
}

#[test]
fn unknown_observation_failure_reasons_are_rejected() {
    assert!(
        serde_json::from_value::<ExecObservationFailedNotification>(serde_json::json!({
            "processId": "original", "reason": "assumeExited",
        }))
        .is_err()
    );
}
