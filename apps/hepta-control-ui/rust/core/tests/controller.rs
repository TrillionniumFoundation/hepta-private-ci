use hepta_control_core::controller::{
    Controller, LookupAdmission, SubmissionAdmission, SubmissionInput,
};
use hepta_control_core::error::{ControlError, ErrorCode};
use hepta_control_core::ledger::OperationState;
use hepta_control_core::projection::Action;
use serde_json::{Value, json};

fn session(identity: &str, id: &str, generation: u64) -> Value {
    json!({"authenticated":true,"protocolVersion":"hepta.ui-control.v1","sessionId":id,
        "identityId":identity,"connectionGeneration":generation,"permissionRevision":1,
        "expiresAt":100_000,"revoked":false,"permissions":["hepta://ui.control/runtime.read",
        "hepta://ui.control/runtime.request","hepta://ui.control/runtime.start","hepta://ui.control/runtime.stop"]})
}
fn snapshot(id: &str, generation: u64, revision: u64) -> Value {
    json!({"sessionId":id,"connectionGeneration":generation,"generation":7,"revision":revision,
        "modules":[{"id":"runtime.agentd","status":"ready","revision":11,"semanticDigest":"a".repeat(64)}]})
}
fn connect(controller: &mut Controller, identity: &str, id: &str, generation: u64) {
    let ticket = controller.begin_connect().unwrap();
    controller
        .connected(&ticket, &session(identity, id, generation), 1000)
        .unwrap();
    let ticket = controller.session_ticket(1000).unwrap();
    controller
        .snapshot_received(&ticket, &snapshot(id, generation, 11), 1000)
        .unwrap();
}
fn client() -> Controller {
    let mut c = Controller::new(1024).unwrap();
    connect(&mut c, "operator-1", "session-1", 1);
    c
}
fn input(id: &str) -> SubmissionInput {
    SubmissionInput {
        operation_id: id.into(),
        action: Action::RequestReconcile,
        target_id: "runtime.agentd".into(),
        reason: "Bounded audit fixture".into(),
        displayed_revision: 11,
        semantic_digest: None,
        confirmation: None,
    }
}
fn reserve(c: &mut Controller, id: &str) -> hepta_control_core::controller::SubmissionTicket {
    match c.begin_submit(input(id), 1000).unwrap() {
        SubmissionAdmission::New(ticket) => *ticket,
        _ => panic!("new expected"),
    }
}
fn ack(ticket: &hepta_control_core::controller::SubmissionTicket) -> Value {
    json!({"accepted":true,"operationId":ticket.request().operation_id(),
        "semanticDigest":ticket.request().semantic_digest(),"status":"accepted","auditTraceId":"audit-one"})
}
fn query(c: &mut Controller, id: &str) -> hepta_control_core::controller::LookupTicket {
    match c.begin_lookup(id, 1000).unwrap() {
        LookupAdmission::Query(ticket) => ticket,
        _ => panic!("query expected"),
    }
}
fn terminal(ticket: &hepta_control_core::controller::SubmissionTicket) -> Value {
    json!({"found":true,"operationId":ticket.request().operation_id(),"semanticDigest":ticket.request().semantic_digest(),
        "status":"succeeded","auditTraceId":"audit-one","outcomeDigest":"c".repeat(64)})
}

#[test]
fn reserve_is_synchronous_and_duplicate_does_not_dispatch() {
    let mut c = client();
    let first = reserve(&mut c, "same");
    assert_eq!(c.view(1000).pending_count, 1);
    assert!(matches!(
        c.begin_submit(input("same"), 1000).unwrap(),
        SubmissionAdmission::InFlight(_)
    ));
    let mut changed = input("same");
    changed.reason = "different".into();
    assert_eq!(
        c.begin_submit(changed, 1000).unwrap_err().code,
        ErrorCode::OperationConflict
    );
    let accepted = c
        .submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    assert_eq!(accepted.state, OperationState::Pending);
    assert!(!accepted.authority_granted);
}

#[test]
fn persisted_request_is_revalidated_before_dispatch() {
    let mut c = client();
    let ticket = reserve(&mut c, "saved");
    let snapshot_ticket = c.session_ticket(1000).unwrap();
    c.snapshot_received(&snapshot_ticket, &snapshot("session-1", 1, 12), 1001)
        .unwrap();
    let error = c.revalidate_dispatch(&ticket, 1001).unwrap_err();
    assert_eq!(error.request_dispatched, Some(false));
    c.submission_failed(&ticket, &error, 1001).unwrap_err();
    assert!(c.view(1001).pending.is_empty());
}

#[test]
fn confirmation_binds_permission_target_and_reason() {
    let mut c = client();
    let mut op = input("confirmed");
    op.confirmation = Some(c.capture_confirmation(&op, 1000).unwrap());
    op.reason = "changed after dialog".into();
    assert_eq!(
        c.begin_submit(op, 1000).unwrap_err().code,
        ErrorCode::StaleRevision
    );
    assert_eq!(c.view(1000).pending_count, 0);
}

#[test]
fn reconnect_cannot_reuse_operation_identity() {
    let mut c = client();
    let first = reserve(&mut c, "original");
    c.submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    c.close();
    connect(&mut c, "operator-1", "session-2", 2);
    assert_eq!(
        c.begin_submit(input("original"), 1002).unwrap_err().code,
        ErrorCode::OperationConflict
    );
    assert_eq!(c.view(1002).pending_count, 1);
}

#[test]
fn late_acknowledgement_stays_with_original_principal() {
    let mut c = client();
    let first = reserve(&mut c, "late");
    c.close();
    connect(&mut c, "operator-2", "session-2", 2);
    c.submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    assert_eq!(c.view(1001).pending_count, 0);
    assert_eq!(c.export_recovery()["operations"], json!([]));
    c.close();
    connect(&mut c, "operator-1", "session-3", 3);
    assert_eq!(
        c.view(1002).pending[0].audit_trace_id.as_deref(),
        Some("audit-one")
    );
}

#[test]
fn late_lookup_cannot_cross_session_or_disconnected_boundary() {
    let mut c = client();
    let first = reserve(&mut c, "lookup");
    c.submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    let lookup = query(&mut c, "lookup");
    c.close();
    assert!(c.lookup_received(&lookup, &terminal(&first), 1002).is_err());
    connect(&mut c, "operator-1", "session-2", 2);
    assert_eq!(
        c.lookup_received(&lookup, &terminal(&first), 1003)
            .unwrap_err()
            .code,
        ErrorCode::StaleGeneration
    );
    assert_eq!(c.view(1003).pending_count, 1);
}

#[test]
fn missing_lookup_does_not_retire_ambiguous_identity() {
    let mut c = client();
    let first = reserve(&mut c, "uncertain");
    c.submission_failed(
        &first,
        &ControlError::new(ErrorCode::Transport).with_dispatch(true),
        1001,
    )
    .unwrap_err();
    let lookup = query(&mut c, "uncertain");
    let result = c
        .lookup_received(&lookup, &json!({"found":false}), 1002)
        .unwrap();
    assert_eq!(result.state, OperationState::Indeterminate);
    assert_eq!(
        c.export_recovery()["operations"].as_array().unwrap().len(),
        1
    );
}

#[test]
fn missing_or_changed_admission_trace_cannot_create_terminal_fact() {
    let mut c = client();
    let first = reserve(&mut c, "trace");
    c.submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    for trace in [Value::Null, json!("other")] {
        let lookup = query(&mut c, "trace");
        let mut observed = terminal(&first);
        observed["auditTraceId"] = trace;
        assert_eq!(
            c.lookup_received(&lookup, &observed, 1002)
                .unwrap_err()
                .code,
            ErrorCode::AckMismatch
        );
    }
    assert_eq!(c.view(1002).pending_count, 1);
}

#[test]
fn recovery_merge_is_atomic_preserves_live_reservations_and_terminal_history() {
    let mut c = client();
    let first = reserve(&mut c, "kept");
    let saved = c.export_recovery();
    c.restore_recovery(&json!({"schema":"hepta.ui-control.recovery-state.v1","operations":[]}))
        .unwrap();
    assert!(matches!(
        c.begin_submit(input("kept"), 1000).unwrap(),
        SubmissionAdmission::InFlight(_)
    ));
    c.submission_acknowledged(&first, &ack(&first), 1001)
        .unwrap();
    let lookup = query(&mut c, "kept");
    c.lookup_received(&lookup, &terminal(&first), 1002).unwrap();
    c.restore_recovery(&saved).unwrap();
    assert_eq!(c.view(1002).completed_count, 1);
    assert_eq!(c.view(1002).pending_count, 0);
}

#[test]
fn recovery_import_rejects_cross_principal_reassignment() {
    let mut c = client();
    let _ = reserve(&mut c, "private");
    let saved = c.export_recovery();
    c.close();
    connect(&mut c, "operator-2", "session-2", 2);
    assert_eq!(
        c.restore_recovery(&saved).unwrap_err().code,
        ErrorCode::OperationConflict
    );
}

#[test]
fn snapshot_failure_retains_high_watermark_and_disables_mutation() {
    let mut c = client();
    let ticket = c.session_ticket(1000).unwrap();
    c.snapshot_failed(&ticket, &ControlError::new(ErrorCode::Transport));
    assert!(c.view(1001).stale);
    assert_eq!(
        c.begin_submit(input("blocked"), 1001).unwrap_err().code,
        ErrorCode::StaleRevision
    );
    assert_eq!(
        c.snapshot_received(&ticket, &snapshot("session-1", 1, 10), 1001)
            .unwrap_err()
            .code,
        ErrorCode::StaleRevision
    );
}

#[test]
fn view_removes_expired_authority_without_erasing_operations() {
    let mut c = client();
    let _ = reserve(&mut c, "retained");
    let view = c.view(100_000);
    assert!(!view.connected);
    assert!(view.permissions.is_empty());
    assert!(view.stale);
    assert_eq!(view.pending_count, 1);
}

#[test]
fn combined_capacity_applies_across_principals() {
    let mut c = Controller::new(1).unwrap();
    connect(&mut c, "operator-1", "session-1", 1);
    let _ = reserve(&mut c, "one");
    c.close();
    connect(&mut c, "operator-2", "session-2", 2);
    assert_eq!(
        c.begin_submit(input("two"), 1001).unwrap_err().code,
        ErrorCode::PendingLimit
    );
}

#[test]
fn closed_connection_cannot_be_resurrected_by_late_handshake() {
    let mut c = Controller::new(1024).unwrap();
    let ticket = c.begin_connect().unwrap();
    c.close();
    assert_eq!(
        c.connected(&ticket, &session("operator-1", "session-1", 1), 1000)
            .unwrap_err()
            .code,
        ErrorCode::Aborted
    );
    assert!(!c.view(1000).connected);
}

#[test]
fn identical_refresh_fences_old_observation_tickets() {
    let mut c = client();
    let old = c.session_ticket(1000).unwrap();
    c.session_refreshed(&old, &session("operator-1", "session-1", 1), 1000)
        .unwrap();
    assert_eq!(
        c.snapshot_received(&old, &snapshot("session-1", 1, 11), 1001)
            .unwrap_err()
            .code,
        ErrorCode::StaleGeneration
    );
}

#[test]
fn recovery_numeric_fields_match_javascript_integer_valued_decimals() {
    let mut c = client();
    let _ = reserve(&mut c, "decimal");
    let mut state = c.export_recovery();
    for name in ["generation", "connectionGeneration", "displayedRevision"] {
        let value = state["operations"][0][name].as_u64().unwrap();
        state["operations"][0][name] = serde_json::from_str(&format!("{value}.0")).unwrap();
    }
    let mut restored = client();
    restored.restore_recovery(&state).unwrap();
    assert_eq!(restored.view(1001).pending_count, 1);
}

#[test]
fn existing_durable_preparation_ambiguity_preserves_local_identity() {
    let mut c = client();
    let ticket = reserve(&mut c, "durable");
    let error = ControlError::new(ErrorCode::AmbiguousSubmission).with_dispatch(true);
    assert_eq!(
        c.submission_failed(&ticket, &error, 1001).unwrap_err().code,
        ErrorCode::AmbiguousSubmission
    );
    assert_eq!(c.view(1001).pending[0].state, OperationState::Indeterminate);
    assert_eq!(
        c.export_recovery()["operations"][0]["operationId"],
        "durable"
    );
}

#[test]
fn malformed_rejection_object_never_erases_an_unresolved_identity() {
    for forbidden in ["constructor", "prototype", "__proto__"] {
        let mut c = client();
        let ticket = reserve(&mut c, "malformed");
        let mut rejection = json!({"accepted":false});
        rejection[forbidden] = json!(1);
        assert_eq!(
            c.submission_acknowledged(&ticket, &rejection, 1001)
                .unwrap_err()
                .code,
            ErrorCode::AmbiguousSubmission
        );
        assert_eq!(c.view(1001).pending[0].state, OperationState::Indeterminate);
        assert!(hepta_control_core::ledger::validate_response_object(&rejection).is_err());
    }
}

#[test]
fn forbidden_lookup_fields_cannot_create_terminal_fact() {
    let mut c = client();
    let ticket = reserve(&mut c, "lookup-root");
    c.submission_acknowledged(&ticket, &ack(&ticket), 1001)
        .unwrap();
    let lookup = query(&mut c, "lookup-root");
    let mut observed = terminal(&ticket);
    observed["constructor"] = json!(1);
    assert_eq!(
        c.lookup_received(&lookup, &observed, 1002)
            .unwrap_err()
            .code,
        ErrorCode::InvalidInput
    );
    assert_eq!(c.view(1002).pending_count, 1);
}

#[test]
fn recovery_backoff_and_metrics_follow_principal_not_session_reconnect() {
    let mut c = client();
    let ticket = reserve(&mut c, "backoff");
    c.submission_acknowledged(&ticket, &ack(&ticket), 1001)
        .unwrap();
    assert_eq!(c.select_recovery(1001), vec!["backoff"]);
    c.recovery_failed("backoff", 1001);
    c.close();
    connect(&mut c, "operator-1", "session-2", 2);
    assert_eq!(c.view(1002).recovery_metrics.failures, 1);
    assert!(c.select_recovery(1002).is_empty());
    c.close();
    connect(&mut c, "operator-2", "session-3", 3);
    assert_eq!(c.view(1002).recovery_metrics.failures, 0);
    assert_eq!(c.view(1002).pending_count, 0);
}

#[test]
fn authentication_refresh_does_not_require_or_grant_console_read_permission() {
    let mut controller = Controller::new(1024).unwrap();
    let mut raw = session("chat-user", "chat-session", 1);
    raw["permissions"] = json!(["hepta://ui.control/runtime.request"]);
    let connect = controller.begin_connect().unwrap();
    controller.connected(&connect, &raw, 1000).unwrap();
    assert_eq!(
        controller.session_ticket(1000).unwrap_err().code,
        ErrorCode::PermissionDenied
    );
    let auth = controller.authentication_ticket(1000).unwrap();
    assert_eq!(
        controller
            .snapshot_received(&auth, &snapshot("chat-session", 1, 11), 1000)
            .unwrap_err()
            .code,
        ErrorCode::PermissionDenied
    );
    controller.session_refreshed(&auth, &raw, 1000).unwrap();
    assert!(controller.view(1000).connected);
    assert!(controller.authentication_ticket(100_001).is_err());
    assert!(!controller.view(100_001).connected);
}
