use super::*;
use pretty_assertions::assert_eq;

#[test]
fn notes_document_readback_matches_original_desktop_wire_without_terminal_claim() {
    let raw = include_str!("../tests/fixtures/notes-document-observation-v1.json");
    let view: ObjectiveObservation = serde_json::from_str(raw).unwrap();
    assert_eq!(view.stage, ObjectiveStage::SubmitUnknown);
    assert_eq!(view.run, None);
    assert_eq!(view.notes_document.as_ref().unwrap().revision, 5);
    assert_eq!(
        serde_json::to_value(view).unwrap(),
        serde_json::from_str::<serde_json::Value>(raw).unwrap()
    );
}

#[test]
fn original_session_wire_keeps_text_literal_and_rejects_authority_fields() {
    let bytes = br#"{"type":"submit","intent":{"client_intent_id":"intent-1","text":"a\\nb"}}"#;
    let command: ObjectiveCommand = serde_json::from_slice(bytes).unwrap();
    assert_eq!(
        command,
        ObjectiveCommand::Submit {
            intent: ObjectiveIntent {
                client_intent_id: "intent-1".into(),
                text: "a\\nb".into(),
            }
        }
    );
    assert_eq!(command.validate(), Ok(()));
    for bytes in [
        br#"{"type":"submit","intent":{"client_intent_id":"intent-1","text":"a","authority_epoch":1}}"#.as_slice(),
        br#"{"type":"cancel","client_intent_id":"intent-1","expected_revision":2}"#.as_slice(),
        br#"{"type":"status","client_intent_id":"one","client_intent_id":"two"}"#.as_slice(),
    ] { assert!(serde_json::from_slice::<ObjectiveCommand>(bytes).is_err()); }
}

#[test]
fn original_session_can_decode_private_fields_absent_observation() {
    let mut view =
        ObjectiveObservation::new(Some("intent-1".into()), ObjectiveStage::SubmitUnknown);
    view.observed_unix_ms = 7;
    view.request_retained = true;
    view.issue = Some(ObjectiveHostIssue::TransportUnknown);
    assert_eq!(
        serde_json::to_value(&view).unwrap(),
        serde_json::json!({
            "observed_unix_ms":7, "client_intent_id":"intent-1", "stage":"submit_unknown",
            "request_retained":true, "publication_retained":false, "run":null,
            "cancellation":"not_requested", "issue":"transport_unknown"
        })
    );
}

#[test]
fn notes_model_confirmation_carries_only_the_original_proposal_reference() {
    let raw = serde_json::json!({
        "type":"confirm_model_proposal", "proposal_id":"model-original",
        "proposal_sha256":"a".repeat(64),
    });
    let command: ObjectiveCommand = serde_json::from_value(raw.clone()).unwrap();
    assert_eq!(command.validate(), Ok(()));
    assert_eq!(serde_json::to_value(command).unwrap(), raw);
    for key in [
        "text",
        "thread_id",
        "call_id",
        "target",
        "expected_revision",
        "grant",
    ] {
        let mut changed = raw.clone();
        changed[key] = serde_json::json!("renderer substitution");
        assert!(serde_json::from_value::<ObjectiveCommand>(changed).is_err());
    }
    for digest in ["", "a", &"A".repeat(64), &"g".repeat(64)] {
        let mut changed = raw.clone();
        changed["proposal_sha256"] = serde_json::json!(digest);
        let command: ObjectiveCommand = serde_json::from_value(changed).unwrap();
        assert_eq!(command.validate(), Err(ObjectiveHostIssue::InvalidIntent));
    }
    let mut declined = raw;
    declined["type"] = serde_json::json!("decline_model_proposal");
    let command: ObjectiveCommand = serde_json::from_value(declined).unwrap();
    assert_eq!(command.client_intent_id(), Some("model-original"));
    assert_eq!(command.validate(), Ok(()));
}

#[test]
fn literal_submission_cannot_impersonate_a_model_proposal_identity() {
    let command = ObjectiveCommand::Submit {
        intent: ObjectiveIntent {
            client_intent_id: format!("model-{}", "a".repeat(64)),
            text: "replacement outside review".into(),
        },
    };
    assert_eq!(command.validate(), Err(ObjectiveHostIssue::InvalidIntent));
}
