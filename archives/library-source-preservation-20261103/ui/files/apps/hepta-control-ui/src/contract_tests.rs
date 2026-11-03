use super::*;
use crate::projection::normalize_snapshot;
use pretty_assertions::assert_eq;
use serde_json::json;

fn raw_session() -> Value {
    json!({"authenticated":true,"protocolVersion":UI_CONTROL_PROTOCOL_VERSION,
        "sessionId":"session-1","identityId":"operator-1","connectionGeneration":5,
        "permissionRevision":2,"expiresAt":10000,"revoked":false,
        "permissions":["hepta://ui.control/runtime.stop","hepta://ui.control/runtime.read",
            "hepta://ui.control/runtime.start","hepta://ui.control/runtime.request"]})
}

fn session() -> Session {
    normalize_session(&raw_session(), UI_CONTROL_PROTOCOL_VERSION, /*now*/ 1).unwrap()
}

fn intent() -> OperationIntent {
    OperationIntent {
        action: Action::RequestReconcile,
        target_id: "runtime.agentd".to_owned(),
        generation: 7,
        displayed_revision: 11,
        reason: "Recover the degraded worker.".to_owned(),
    }
}

fn request() -> OperationRequest {
    let intent = intent();
    OperationRequest {
        protocol_version: UI_CONTROL_PROTOCOL_VERSION.to_owned(),
        method: Method::Request,
        operation_id: "operation-1".to_owned(),
        semantic_digest: digest_operation_intent(&intent).unwrap(),
        action: intent.action,
        target_id: intent.target_id,
        reason: intent.reason,
        session_id: "session-1".to_owned(),
        connection_generation: 5,
        generation: 7,
        displayed_revision: 11,
        snapshot_digest: "b".repeat(64),
    }
}

#[test]
fn intent_digest_matches_javascript_and_binds_every_semantic_field() {
    let original = intent();
    assert_eq!(
        digest_operation_intent(&original),
        Ok("16cf32c0b2fe63c52e6db161fdbf30f9582c258d0ad5090f55009dbda8b143ad".to_owned())
    );
    for changed in [
        OperationIntent {
            action: Action::RequestRetry,
            ..original.clone()
        },
        OperationIntent {
            target_id: "other".to_owned(),
            ..original.clone()
        },
        OperationIntent {
            generation: 8,
            ..original.clone()
        },
        OperationIntent {
            displayed_revision: 12,
            ..original.clone()
        },
        OperationIntent {
            reason: "Different reason.".to_owned(),
            ..original.clone()
        },
    ] {
        assert_ne!(
            digest_operation_intent(&changed),
            digest_operation_intent(&original)
        );
    }
}

#[test]
fn rejects_unknown_critical_intent_fields_and_invalid_reasons() {
    let mut extra = serde_json::to_value(intent()).unwrap();
    extra["authorityGranted"] = json!(true);
    assert_eq!(
        build_operation_intent(&extra),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
    for reason in [
        "".to_owned(),
        "a".repeat(1025),
        "e\u{301}".to_owned(),
        "reason\n".to_owned(),
    ] {
        assert_eq!(
            digest_operation_intent(&OperationIntent { reason, ..intent() }),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
    }
    let mut integral = serde_json::to_value(intent()).unwrap();
    integral["generation"] = json!(7.0);
    assert_eq!(build_operation_intent(&integral), Ok(intent()));
}

#[test]
fn session_normalization_sorts_permissions_and_checks_authentication_protocol_and_expiry() {
    assert_eq!(
        session(),
        Session {
            protocol_version: UI_CONTROL_PROTOCOL_VERSION.to_owned(),
            authenticated: true,
            session_id: "session-1".to_owned(),
            identity_id: "operator-1".to_owned(),
            connection_generation: 5,
            permission_revision: 2,
            expires_at: 10000,
            revoked: false,
            permissions: vec![
                Permission::Read,
                Permission::Request,
                Permission::Start,
                Permission::Stop
            ]
        }
    );
    for (field, value, code) in [
        ("authenticated", json!(false), ErrorCode::PermissionDenied),
        (
            "protocolVersion",
            json!("other-protocol"),
            ErrorCode::ProtocolMismatch,
        ),
        ("expiresAt", json!(1), ErrorCode::SessionExpired),
        ("revoked", json!(true), ErrorCode::SessionRevoked),
        ("permissionRevision", json!(0), ErrorCode::InvalidInput),
        ("permissions", json!([]), ErrorCode::InvalidInput),
        (
            "permissions",
            json!([
                "hepta://ui.control/runtime.read",
                "hepta://ui.control/runtime.read"
            ]),
            ErrorCode::InvalidInput,
        ),
        ("permissions", json!(["root"]), ErrorCode::InvalidInput),
    ] {
        let mut value_session = raw_session();
        value_session[field] = value;
        assert_eq!(
            normalize_session(&value_session, UI_CONTROL_PROTOCOL_VERSION, /*now*/ 1),
            Err(ControlError::new(code))
        );
    }
}

#[test]
fn optional_session_extensions_are_accepted_but_still_bounded_canonical_data() {
    let mut extended = raw_session();
    extended["diagnostic"] = json!("healthy");
    extended["revoked"] = json!("false");
    extended["connectionGeneration"] = json!(5.0);
    assert_eq!(
        normalize_session(&extended, UI_CONTROL_PROTOCOL_VERSION, /*now*/ 1),
        Ok(session())
    );
    extended["diagnostic"] = json!({"constructor":"hostile"});
    assert_eq!(
        normalize_session(&extended, UI_CONTROL_PROTOCOL_VERSION, /*now*/ 1),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
}

#[test]
fn request_validation_binds_digest_method_and_protocol() {
    assert_eq!(request().validate(), Ok(()));
    assert_eq!(
        OperationRequest {
            semantic_digest: "c".repeat(64),
            ..request()
        }
        .validate(),
        Err(ControlError::new(ErrorCode::OperationConflict))
    );
    assert_eq!(
        OperationRequest {
            method: Method::Start,
            ..request()
        }
        .validate(),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
    assert_eq!(
        OperationRequest {
            protocol_version: "other".to_owned(),
            ..request()
        }
        .validate(),
        Err(ControlError::new(ErrorCode::ProtocolMismatch))
    );
}

#[test]
fn acknowledgements_bind_operation_digest_audit_and_active_status() {
    let request = request();
    let acknowledgement = json!({"accepted":true,"operationId":request.operation_id,
        "semanticDigest":request.semantic_digest,"status":"accepted","auditTraceId":"audit-1"});
    assert_eq!(
        validate_acknowledgement(&request, &acknowledgement),
        Ok(Acknowledgement {
            status: OperationStatus::Accepted,
            audit_trace_id: "audit-1".to_owned()
        })
    );
    for (key, value, code) in [
        ("operationId", json!("other"), ErrorCode::AckMismatch),
        (
            "semanticDigest",
            json!("b".repeat(64)),
            ErrorCode::AckMismatch,
        ),
        ("status", json!("succeeded"), ErrorCode::AckMismatch),
        ("status", json!("invented"), ErrorCode::AckMismatch),
        ("auditTraceId", json!(null), ErrorCode::InvalidInput),
        ("accepted", json!(null), ErrorCode::InvalidInput),
        ("accepted", json!(false), ErrorCode::BackendRejected),
    ] {
        let mut changed = acknowledgement.clone();
        changed[key] = value;
        assert_eq!(
            validate_acknowledgement(&request, &changed),
            Err(ControlError::new(code))
        );
    }
    assert_eq!(
        validate_audit_trace(Some("audit-1"), Some("audit-2")),
        Err(ControlError::new(ErrorCode::AckMismatch))
    );
    assert_eq!(
        validate_audit_trace(None, None),
        Err(ControlError::new(ErrorCode::AckMismatch))
    );
    assert_eq!(validate_audit_trace(None, Some("audit-1")), Ok("audit-1"));
}

#[test]
fn terminal_observation_requires_a_terminal_fact_and_preserves_optional_outcome() {
    let value = json!({"operationId":"operation-1","semanticDigest":"a".repeat(64),"status":"succeeded",
        "terminalObserved":true,"auditTraceId":"audit-1","outcomeDigest":"0".repeat(64)});
    let observed = normalize_observation(&value).unwrap();
    assert_eq!(serde_json::to_value(observed).unwrap(), value);
    for (key, replacement) in [
        ("terminalObserved", json!(false)),
        ("status", json!("accepted")),
        ("outcomeDigest", json!("bad")),
        ("authorityGranted", json!(true)),
    ] {
        let mut changed = value.clone();
        changed[key] = replacement;
        assert_eq!(
            normalize_observation(&changed),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
    }
}

#[test]
fn confirmation_binds_every_context_field_and_fails_closed_before_dispatch() {
    let session = session();
    let snapshot = normalize_snapshot(
        &json!({"sessionId":"session-1","connectionGeneration":5,
        "generation":7,"revision":11,"modules":[{"id":"runtime.agentd","revision":3,
        "semanticDigest":"a".repeat(64),"status":"degraded"}]}),
        &session,
    )
    .unwrap();
    let input = ConfirmationInput {
        operation_id: "operation-1".to_owned(),
        action: Action::RequestReconcile,
        target_id: "runtime.agentd".to_owned(),
        reason: "Recover the degraded worker.".to_owned(),
    };
    let confirmation = capture_confirmation(Some(&session), Some(&snapshot), &input).unwrap();
    assert_eq!(
        assert_confirmation(&confirmation, Some(&session), Some(&snapshot), &input),
        Ok(())
    );
    let original = serde_json::to_value(&confirmation).unwrap();
    for key in original.as_object().unwrap().keys() {
        let mut changed = original.clone();
        changed[key] = if key == "action" {
            json!("request_retry")
        } else if original[key].is_number() {
            json!(original[key].as_u64().unwrap() + 1)
        } else {
            json!(format!("{}-changed", original[key].as_str().unwrap()))
        };
        let context: ConfirmationContext = serde_json::from_value(changed).unwrap();
        assert_eq!(
            assert_confirmation(&context, Some(&session), Some(&snapshot), &input),
            Err(ControlError::new(ErrorCode::StaleRevision).not_dispatched()),
            "{key}"
        );
    }
    assert_eq!(
        capture_confirmation(None, Some(&snapshot), &input),
        Err(ControlError::new(ErrorCode::StaleRevision).not_dispatched())
    );
    assert_eq!(
        capture_confirmation(Some(&session), None, &input),
        Err(ControlError::new(ErrorCode::StaleRevision).not_dispatched())
    );
    let removed = ConfirmationInput {
        target_id: "removed".to_owned(),
        ..input
    };
    assert_eq!(
        capture_confirmation(Some(&session), Some(&snapshot), &removed),
        Err(ControlError::new(ErrorCode::StaleRevision).not_dispatched())
    );
}

#[test]
fn selection_does_not_silently_retarget_after_removal() {
    let ids = vec!["a".to_owned(), "b".to_owned()];
    assert_eq!(retained_target("b", &ids, /*initialized*/ true), "b");
    assert_eq!(retained_target("removed", &ids, /*initialized*/ true), "");
    assert_eq!(retained_target("", &ids, /*initialized*/ false), "a");
}
