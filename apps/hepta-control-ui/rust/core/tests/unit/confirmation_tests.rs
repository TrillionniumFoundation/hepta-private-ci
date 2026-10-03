use super::*;
use crate::projection::{PROTOCOL_VERSION, normalize_session, normalize_snapshot};
use serde_json::{Value, json};

#[test]
fn confirmation_matches_javascript_and_binds_every_context_field() {
    let fixture: Value =
        serde_json::from_str(include_str!("../fixtures/javascript-reference.json")).unwrap();
    let session = normalize_session(&fixture["session"]["input"], PROTOCOL_VERSION, 1000).unwrap();
    let snapshot = normalize_snapshot(&fixture["snapshot"]["input"], &session).unwrap();
    let input_value = &fixture["confirmation"]["input"];
    let input = ConfirmationInput {
        target_id: input_value["targetId"].as_str().unwrap(),
        action: input_value["action"].as_str().unwrap(),
        reason: input_value["reason"].as_str().unwrap(),
        operation_id: input_value["operationId"].as_str().unwrap(),
    };
    let view = ConfirmationView {
        session: Some(&session),
        snapshot: Some(&snapshot),
        connected: true,
        authenticated: true,
        stale: false,
    };
    let confirmation = capture_confirmation(&view, &input).unwrap();
    assert_eq!(json!(confirmation), fixture["confirmation"]["captured"]);
    assert_confirmation(Some(&confirmation), &view, &input).unwrap();
    assert!(assert_confirmation(None, &view, &input).is_err());
    for case in fixture["confirmation"]["drift"].as_array().unwrap() {
        let mut session = session.clone();
        let mut snapshot = snapshot.clone();
        let mut changed_input = input_value.clone();
        let value = &case["value"];
        let path = case["path"].as_str().unwrap();
        match path {
            "sessionId" => session.session_id = value.as_str().unwrap().to_owned(),
            "identityId" => session.identity_id = value.as_str().unwrap().to_owned(),
            "permissionRevision" => session.permission_revision = value.as_u64().unwrap(),
            "connectionGeneration" => session.connection_generation = value.as_u64().unwrap(),
            "snapshot.generation" => snapshot.generation = value.as_u64().unwrap(),
            "snapshot.revision" => snapshot.revision = value.as_u64().unwrap(),
            "snapshot.semanticDigest" => {
                snapshot.semantic_digest = value.as_str().unwrap().to_owned()
            }
            "snapshot.modules.0.revision" => snapshot.modules[0].revision = value.as_u64().unwrap(),
            "snapshot.modules.0.semanticDigest" => {
                snapshot.modules[0].semantic_digest = value.as_str().unwrap().to_owned()
            }
            "input.targetId" => changed_input["targetId"] = value.clone(),
            "input.action" => changed_input["action"] = value.clone(),
            "input.reason" => changed_input["reason"] = value.clone(),
            "input.operationId" => changed_input["operationId"] = value.clone(),
            "connected" | "authenticated" | "stale" => {}
            _ => panic!("unknown fixture confirmation change"),
        }
        let view = ConfirmationView {
            session: Some(&session),
            snapshot: Some(&snapshot),
            connected: path != "connected",
            authenticated: path != "authenticated",
            stale: path == "stale",
        };
        let input = ConfirmationInput {
            target_id: changed_input["targetId"].as_str().unwrap(),
            action: changed_input["action"].as_str().unwrap(),
            reason: changed_input["reason"].as_str().unwrap(),
            operation_id: changed_input["operationId"].as_str().unwrap(),
        };
        let error = assert_confirmation(Some(&confirmation), &view, &input).unwrap_err();
        assert_eq!(
            json!({"error": error.code.as_str(), "retryable": error.retryable}),
            case["result"],
            "{path}"
        );
        assert_eq!(error.request_dispatched, Some(false));
    }
}

#[test]
fn removal_never_silently_selects_a_different_target() {
    assert_eq!(
        retained_target("fleet", &["agent".into(), "fleet".into()], true),
        "fleet"
    );
    assert_eq!(retained_target("fleet", &["agent".into()], true), "");
    assert_eq!(retained_target("", &["agent".into()], false), "agent");
    assert_eq!(retained_target("", &[], false), "");
}
