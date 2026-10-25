use super::*;
use pretty_assertions::assert_eq;

#[test]
fn original_session_wire_keeps_text_literal_and_rejects_authority_fields() {
    let bytes = br#"{"type":"submit","intent":{"client_intent_id":"intent-1","text":"a\\nb"}}"#;
    let command: ObjectiveCommand = serde_json::from_slice(bytes).unwrap();
    assert_eq!(command, ObjectiveCommand::Submit { intent: ObjectiveIntent {
        client_intent_id: "intent-1".into(), text: "a\\nb".into(),
    }});
    assert_eq!(command.validate(), Ok(()));
    for bytes in [
        br#"{"type":"submit","intent":{"client_intent_id":"intent-1","text":"a","authority_epoch":1}}"#.as_slice(),
        br#"{"type":"cancel","client_intent_id":"intent-1","expected_revision":2}"#.as_slice(),
        br#"{"type":"status","client_intent_id":"one","client_intent_id":"two"}"#.as_slice(),
    ] { assert!(serde_json::from_slice::<ObjectiveCommand>(bytes).is_err()); }
}

#[test]
fn original_session_can_decode_private_fields_absent_observation() {
    let mut view = ObjectiveObservation::new(Some("intent-1".into()), ObjectiveStage::SubmitUnknown);
    view.observed_unix_ms = 7;
    view.request_retained = true;
    view.issue = Some(ObjectiveHostIssue::TransportUnknown);
    assert_eq!(serde_json::to_value(&view).unwrap(), serde_json::json!({
        "observed_unix_ms":7, "client_intent_id":"intent-1", "stage":"submit_unknown",
        "request_retained":true, "publication_retained":false, "run":null,
        "cancellation":"not_requested", "issue":"transport_unknown"
    }));
}
