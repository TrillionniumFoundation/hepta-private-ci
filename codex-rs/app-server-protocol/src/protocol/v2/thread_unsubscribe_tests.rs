use super::ThreadUnsubscribeParams;
use super::ThreadUnsubscribeResponse;
use super::ThreadUnsubscribeStatus;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn thread_unsubscribe_preserves_omitted_and_null_disposal_wire_behavior() {
    let omitted: ThreadUnsubscribeParams =
        serde_json::from_value(json!({"threadId":"original"})).unwrap();
    let null: ThreadUnsubscribeParams =
        serde_json::from_value(json!({"threadId":"original","ephemeralDisposal":null})).unwrap();
    assert_eq!(omitted, null);
    assert!(omitted.ephemeral_disposal.is_none());
    assert!(
        serde_json::from_value::<ThreadUnsubscribeParams>(
            json!({"threadId":"original","ephemeralDisposal":{}})
        )
        .is_err()
    );
    let explicit: ThreadUnsubscribeParams = serde_json::from_value(
        json!({"threadId":"original","ephemeralDisposal":{"expectedSessionId":"original-session"}}),
    )
    .unwrap();
    assert_eq!(
        explicit.ephemeral_disposal.unwrap().expected_session_id,
        "original-session"
    );
    let disposed: ThreadUnsubscribeResponse =
        serde_json::from_value(json!({"status":"ephemeralDisposed"})).unwrap();
    assert_eq!(disposed.status, ThreadUnsubscribeStatus::EphemeralDisposed);
}
