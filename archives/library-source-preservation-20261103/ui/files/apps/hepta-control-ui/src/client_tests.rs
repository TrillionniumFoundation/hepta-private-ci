use super::*;
use crate::contract::{Action, Permission};
use crate::recovery::{RecoveryScope, RecoveryStore};
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

#[derive(Clone)]
struct Store {
    scope: RecoveryScope,
    records: Arc<Mutex<BTreeMap<String, Value>>>,
    fail_prepare: bool,
    fail_cleanup: bool,
}
impl RecoveryStore for Store {
    fn scope(&self) -> &RecoveryScope {
        &self.scope
    }
    fn load(&mut self) -> Result<BTreeMap<String, Value>> {
        Ok(self.records.lock().unwrap().clone())
    }
    fn prepare(&mut self, id: &str, value: &Value) -> Result<Preparation> {
        if self.fail_prepare {
            return Err(ControlError::new(ErrorCode::Storage));
        }
        let mut records = self.records.lock().unwrap();
        if let Some(prior) = records.get(id) {
            return if prior == value {
                Ok(Preparation::ExistingNeedsRecovery)
            } else {
                Err(ControlError::new(ErrorCode::OperationConflict))
            };
        }
        records.insert(id.into(), value.clone());
        Ok(Preparation::New)
    }
    fn complete(&mut self, id: &str, value: &Value) -> Result<()> {
        if self.fail_cleanup {
            return Err(ControlError::new(ErrorCode::Storage));
        }
        let mut records = self.records.lock().unwrap();
        if records.get(id).is_some_and(|prior| prior != value) {
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        records.remove(id);
        Ok(())
    }
}
struct Backend {
    session: Value,
    snapshot: Value,
    lookup: Value,
    requests: usize,
    ambiguous: bool,
    bad_ack: bool,
    refresh_error: bool,
    close_error: bool,
}
#[derive(Clone)]
struct Transport(Arc<Mutex<Backend>>);
impl ControlTransport for Transport {
    fn endpoint(&self) -> &str {
        "https://console.test/api/ui-control/v1/"
    }
    fn connect(&mut self, _: &Value) -> Result<Value> {
        Ok(self.0.lock().unwrap().session.clone())
    }
    fn refresh_session(&mut self, _: &Value) -> Result<Value> {
        Ok(self.0.lock().unwrap().session.clone())
    }
    fn read_snapshot(&mut self, _: &Value) -> Result<Value> {
        let backend = self.0.lock().unwrap();
        if backend.refresh_error {
            Err(ControlError::new(ErrorCode::Transport))
        } else {
            Ok(backend.snapshot.clone())
        }
    }
    fn request(&mut self, _: &str, input: &Value) -> Result<Value> {
        let mut backend = self.0.lock().unwrap();
        backend.requests += 1;
        if backend.ambiguous {
            return Err(ControlError {
                code: ErrorCode::Transport,
                request_dispatched: Some(true),
            });
        }
        Ok(
            json!({"accepted":true,"operationId":if backend.bad_ack{"foreign"}else{input["operationId"].as_str().unwrap()},
            "semanticDigest":input["semanticDigest"],"status":"accepted","auditTraceId":"audit.1"}),
        )
    }
    fn lookup(&mut self, _: &Value) -> Result<Value> {
        Ok(self.0.lock().unwrap().lookup.clone())
    }
    fn close(&mut self, _: &Value) -> Result<()> {
        if self.0.lock().unwrap().close_error {
            Err(ControlError::new(ErrorCode::Transport))
        } else {
            Ok(())
        }
    }
    fn revoke(&mut self, session: &Value) -> Result<()> {
        self.close(session)
    }
}
type Client = RuntimeClient<Transport, Store>;
fn fixture() -> (Client, Arc<Mutex<Backend>>, Store, Arc<AtomicU64>) {
    let backend = Arc::new(Mutex::new(Backend {
        session: json!({"authenticated":true,"protocolVersion":"hepta.ui-control.v1",
        "sessionId":"session.1","identityId":"operator.1","connectionGeneration":1,"permissionRevision":1,
        "expiresAt":1_000_000,"permissions":["hepta://ui.control/runtime.read","hepta://ui.control/runtime.stop"]}),
        snapshot: json!({"sessionId":"session.1","connectionGeneration":1,"generation":7,"revision":12,
            "modules":[{"id":"runtime.agentd","status":"ready","revision":9,"semanticDigest":"a".repeat(64)}]}),
        lookup: json!({"found":false}),
        requests: 0,
        ambiguous: false,
        bad_ack: false,
        refresh_error: false,
        close_error: false,
    }));
    let store = Store {
        scope: RecoveryScope {
            endpoint: "https://console.test/api/ui-control/v1/".into(),
            protocol_version: "hepta.ui-control.v1".into(),
            identity_id: "operator.1".into(),
        },
        records: Arc::new(Mutex::new(BTreeMap::new())),
        fail_prepare: false,
        fail_cleanup: false,
    };
    let now = Arc::new(AtomicU64::new(1000));
    let clock = Arc::clone(&now);
    let mut client = Client::with_clock(
        Transport(Arc::clone(&backend)),
        store.clone(),
        1024,
        Box::new(move || clock.load(Ordering::SeqCst)),
    )
    .unwrap();
    client.connect(&json!({})).unwrap();
    client.refresh_view().unwrap();
    (client, backend, store, now)
}
fn operation_input(id: &str) -> ConfirmationInput {
    ConfirmationInput {
        operation_id: id.into(),
        action: Action::RequestStop,
        target_id: "runtime.agentd".into(),
        reason: "Maintenance".into(),
    }
}
fn submit(client: &mut Client, id: &str) -> Result<OperationView> {
    let input = operation_input(id);
    let confirmation = client.capture_confirmation(&input)?;
    client.submit(Method::Stop, input, &confirmation)
}
fn terminal(backend: &Arc<Mutex<Backend>>, view: &OperationView) {
    backend.lock().unwrap().lookup = json!({"found":true,"operationId":view.operation_id,
    "semanticDigest":view.semantic_digest,"status":"succeeded","auditTraceId":"audit.1","outcomeDigest":"b".repeat(64)});
}

#[test]
fn actual_client_reserves_persists_dispatches_once_and_requires_terminal_lookup() {
    let (mut client, backend, store, _) = fixture();
    let first = submit(&mut client, "op.1").unwrap();
    assert_eq!(first.state, OperationState::Pending);
    assert_eq!(store.records.lock().unwrap().len(), 1);
    assert_eq!(submit(&mut client, "op.1").unwrap(), first);
    assert_eq!(backend.lock().unwrap().requests, 1);
    terminal(&backend, &first);
    let result = client.recover_operation("op.1").unwrap();
    assert_eq!(result.state, OperationState::Terminal);
    assert_eq!(result.terminal_status, Some(OperationStatus::Succeeded));
    assert!(store.records.lock().unwrap().is_empty());
    assert_eq!(backend.lock().unwrap().requests, 1);
}
#[test]
fn response_loss_missing_lookup_and_retry_never_redispatch() {
    let (mut client, backend, store, now) = fixture();
    backend.lock().unwrap().ambiguous = true;
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::AmbiguousSubmission
    );
    assert_eq!(
        client.recover_operation("op.1").unwrap().state,
        OperationState::Indeterminate
    );
    assert_eq!(
        submit(&mut client, "op.1").unwrap().state,
        OperationState::Indeterminate
    );
    assert_eq!(backend.lock().unwrap().requests, 1);
    client.close().unwrap();
    let clock = Arc::clone(&now);
    let mut reopened = Client::with_clock(
        Transport(Arc::clone(&backend)),
        store,
        1024,
        Box::new(move || clock.load(Ordering::SeqCst)),
    )
    .unwrap();
    reopened.connect(&json!({})).unwrap();
    reopened.refresh_view().unwrap();
    assert_eq!(
        submit(&mut reopened, "op.1").unwrap().state,
        OperationState::Indeterminate
    );
    assert_eq!(backend.lock().unwrap().requests, 1);
}
#[test]
fn malformed_ack_retains_recovery_identity() {
    let (mut client, backend, store, _) = fixture();
    backend.lock().unwrap().bad_ack = true;
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::AmbiguousSubmission
    );
    assert_eq!(store.records.lock().unwrap().len(), 1);
}
#[test]
fn expired_and_revised_confirmation_never_dispatch() {
    let (mut client, backend, _, now) = fixture();
    let input = operation_input("op.1");
    let confirmation = client.capture_confirmation(&input).unwrap();
    now.store(1_000_000, Ordering::SeqCst);
    assert_eq!(
        client
            .submit(Method::Stop, input, &confirmation)
            .unwrap_err()
            .code,
        ErrorCode::SessionExpired
    );
    assert_eq!(backend.lock().unwrap().requests, 0);
    let (mut client, backend, _, _) = fixture();
    let input = operation_input("op.2");
    let confirmation = client.capture_confirmation(&input).unwrap();
    backend.lock().unwrap().snapshot["revision"] = json!(13);
    client.refresh_view().unwrap();
    assert_eq!(
        client
            .submit(Method::Stop, input, &confirmation)
            .unwrap_err()
            .code,
        ErrorCode::StaleRevision
    );
    assert_eq!(backend.lock().unwrap().requests, 0);
}
#[test]
fn failed_refresh_stales_view_but_retains_high_watermark() {
    let (mut client, backend, _, _) = fixture();
    backend.lock().unwrap().refresh_error = true;
    assert!(client.refresh_view().is_err());
    assert!(client.view().unwrap().stale);
    {
        let mut backend = backend.lock().unwrap();
        backend.refresh_error = false;
        backend.snapshot["revision"] = json!(11);
    }
    assert_eq!(
        client.refresh_view().unwrap_err().code,
        ErrorCode::StaleRevision
    );
    backend.lock().unwrap().snapshot["revision"] = json!(12);
    assert!(!client.refresh_view().unwrap().stale);
}
#[test]
fn permission_revision_and_identity_switch_fail_closed() {
    let (mut client, backend, _, _) = fixture();
    backend.lock().unwrap().session["permissions"] = json!(["hepta://ui.control/runtime.read"]);
    assert_eq!(
        client.refresh_session().unwrap_err().code,
        ErrorCode::StalePermissionRevision
    );
    assert!(client.view().unwrap().session.is_none());
    assert_eq!(backend.lock().unwrap().requests, 0);
    let (mut client, backend, _, _) = fixture();
    backend.lock().unwrap().session["identityId"] = json!("operator.2");
    assert_eq!(
        client.refresh_session().unwrap_err().code,
        ErrorCode::SessionIdentityChanged
    );
}
#[test]
fn pending_data_is_isolated_on_identity_switch_and_retained_on_return() {
    let (mut client, backend, store, _) = fixture();
    submit(&mut client, "op.1").unwrap();
    client.close().unwrap();
    let mut other = store.clone();
    other.scope.identity_id = "operator.2".into();
    other.records = Arc::new(Mutex::new(BTreeMap::new()));
    client.replace_recovery_store(other).unwrap();
    backend.lock().unwrap().session["identityId"] = json!("operator.2");
    client.connect(&json!({})).unwrap();
    client.refresh_view().unwrap();
    assert!(client.view().unwrap().pending.is_empty());
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::OperationConflict
    );
    client.close().unwrap();
    client.replace_recovery_store(store).unwrap();
    backend.lock().unwrap().session["identityId"] = json!("operator.1");
    client.connect(&json!({})).unwrap();
    assert_eq!(client.view().unwrap().pending.len(), 1);
}
#[test]
fn terminal_cleanup_failure_does_not_erase_terminal_or_enable_replay() {
    let (mut client, backend, store, _) = fixture();
    client.recovery.fail_cleanup = true;
    let first = submit(&mut client, "op.1").unwrap();
    terminal(&backend, &first);
    assert_eq!(
        client.recover_operation("op.1").unwrap().state,
        OperationState::Terminal
    );
    assert!(client.view().unwrap().storage_error);
    assert_eq!(store.records.lock().unwrap().len(), 1);
    client.recovery.fail_cleanup = false;
    assert_eq!(client.cleanup_terminal(32).unwrap(), 1);
    assert!(!client.view().unwrap().storage_error);
    assert!(store.records.lock().unwrap().is_empty());
    assert_eq!(backend.lock().unwrap().requests, 1);
}
#[test]
fn close_removes_authority_even_if_transport_cleanup_fails() {
    let (mut client, backend, _, _) = fixture();
    backend.lock().unwrap().close_error = true;
    assert!(client.close().is_err());
    assert!(client.view().unwrap().session.is_none());
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::NotConnected
    );
}
#[test]
fn storage_failure_prevents_transport_and_preserves_uncertainty() {
    let (mut client, backend, _, _) = fixture();
    client.recovery.fail_prepare = true;
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::Storage
    );
    assert_eq!(backend.lock().unwrap().requests, 0);
    assert_eq!(
        client.view().unwrap().pending[0].state,
        OperationState::Indeterminate
    );
}
#[test]
fn changed_audit_identity_cannot_clean_terminal_record() {
    let (mut client, backend, store, _) = fixture();
    let first = submit(&mut client, "op.1").unwrap();
    terminal(&backend, &first);
    backend.lock().unwrap().lookup["auditTraceId"] = json!("audit.changed");
    assert_eq!(
        client.recover_operation("op.1").unwrap_err().code,
        ErrorCode::AckMismatch
    );
    assert_eq!(store.records.lock().unwrap().len(), 1);
}
#[test]
fn snapshot_content_drift_without_revision_is_rejected() {
    let (mut client, backend, _, _) = fixture();
    backend.lock().unwrap().snapshot["modules"][0]["status"] = json!("unavailable");
    assert_eq!(
        client.refresh_view().unwrap_err().code,
        ErrorCode::SnapshotDrift
    );
    assert!(client.view().unwrap().stale);
}
#[test]
fn missing_permission_does_not_create_pending_identity() {
    let (mut client, _, _, _) = fixture();
    client.session.as_mut().unwrap().permissions = vec![Permission::Read];
    assert_eq!(
        submit(&mut client, "op.1").unwrap_err().code,
        ErrorCode::PermissionDenied
    );
    assert!(client.view().unwrap().pending.is_empty());
}

#[test]
fn recovery_endpoint_mismatch_fails_before_connect_and_store_replacement() {
    let (mut client, backend, mut store, _) = fixture();
    client.close().unwrap();
    store.scope.endpoint = "https://other.test/api/ui-control/v1/".into();
    assert_eq!(
        client.replace_recovery_store(store.clone()),
        Err(ControlError::new(ErrorCode::Storage).not_dispatched())
    );
    assert_eq!(
        Client::new(Transport(Arc::clone(&backend)), store, 1024).err(),
        Some(ControlError::new(ErrorCode::Storage).not_dispatched())
    );
    client.recovery.scope.endpoint = "https://console.test/different-base/".into();
    assert_eq!(
        client.connect(&json!({})),
        Err(ControlError::new(ErrorCode::Storage).not_dispatched())
    );
    assert!(client.view().unwrap().session.is_none());
    assert_eq!(backend.lock().unwrap().requests, 0);
}

#[test]
fn equivalent_canonical_endpoint_urls_bind_to_the_same_recovery_scope() {
    let (_, backend, mut store, _) = fixture();
    store.scope.endpoint = "https://CONSOLE.TEST:443/api/ui-control/v1/".into();
    assert!(Client::new(Transport(backend), store, 1024).is_ok());
}

#[test]
fn malformed_optional_terminal_outcomes_never_clear_pending_recovery() {
    for malformed in [
        json!(42),
        json!({}),
        json!([]),
        json!(false),
        json!("bad-digest"),
    ] {
        let (mut client, backend, store, _) = fixture();
        let pending = submit(&mut client, "op.1").unwrap();
        terminal(&backend, &pending);
        backend.lock().unwrap().lookup["outcomeDigest"] = malformed;
        assert_eq!(
            client.recover_operation("op.1"),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
        assert_eq!(client.view().unwrap().pending, vec![pending]);
        assert_eq!(store.records.lock().unwrap().len(), 1);
        assert_eq!(backend.lock().unwrap().requests, 1);
    }
}

#[test]
fn malformed_found_and_audit_fields_never_establish_terminal_truth() {
    for malformed in [json!(null), json!(0), json!("false"), json!({})] {
        let (mut client, backend, store, _) = fixture();
        let pending = submit(&mut client, "op.1").unwrap();
        terminal(&backend, &pending);
        backend.lock().unwrap().lookup["found"] = malformed;
        assert_eq!(
            client.recover_operation("op.1"),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
        assert_eq!(client.view().unwrap().pending, vec![pending]);
        assert_eq!(store.records.lock().unwrap().len(), 1);
    }
    let (mut client, backend, store, _) = fixture();
    let pending = submit(&mut client, "op.1").unwrap();
    terminal(&backend, &pending);
    backend.lock().unwrap().lookup["auditTraceId"] = json!(123);
    assert_eq!(
        client.recover_operation("op.1"),
        Err(ControlError::new(ErrorCode::AckMismatch))
    );
    assert_eq!(client.view().unwrap().pending, vec![pending]);
    assert_eq!(store.records.lock().unwrap().len(), 1);
}

#[test]
fn malformed_restored_audit_identity_is_rejected_without_adoption_or_dispatch() {
    for malformed in [json!(123), json!(false), json!([]), json!({})] {
        let (mut client, backend, store, now) = fixture();
        submit(&mut client, "op.1").unwrap();
        client.close().unwrap();
        store.records.lock().unwrap().get_mut("op.1").unwrap()["auditTraceId"] = malformed;
        let clock = Arc::clone(&now);
        let mut reopened = Client::with_clock(
            Transport(Arc::clone(&backend)),
            store.clone(),
            1024,
            Box::new(move || clock.load(Ordering::SeqCst)),
        )
        .unwrap();
        assert_eq!(
            reopened.connect(&json!({})),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
        assert!(reopened.view().unwrap().session.is_none());
        assert_eq!(store.records.lock().unwrap().len(), 1);
        assert_eq!(backend.lock().unwrap().requests, 1);
    }
}

#[test]
fn cleanup_rotates_past_a_full_failed_batch_and_never_repeats_successes() {
    let (mut client, backend, store, _) = fixture();
    client.recovery.fail_cleanup = true;
    for index in 0..40 {
        let id = format!("op.{index:03}");
        let pending = submit(&mut client, &id).unwrap();
        terminal(&backend, &pending);
        assert_eq!(
            client.recover_operation(&id).unwrap().state,
            OperationState::Terminal
        );
    }
    assert_eq!(
        client.cleanup_terminal(32),
        Err(ControlError::new(ErrorCode::Storage))
    );
    client.recovery.fail_cleanup = false;
    assert_eq!(client.cleanup_terminal(8), Ok(8));
    assert_eq!(
        store
            .records
            .lock()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>(),
        (0..32)
            .map(|index| format!("op.{index:03}"))
            .collect::<Vec<_>>()
    );
    assert_eq!(client.cleanup_terminal(32), Ok(32));
    assert_eq!(client.cleanup_terminal(32), Ok(0));
    assert!(store.records.lock().unwrap().is_empty());
    assert_eq!(client.view().unwrap().completed.len(), 40);
    assert_eq!(backend.lock().unwrap().requests, 40);
}

#[test]
fn failed_terminal_cleanup_remains_principal_scoped_until_original_owner_returns() {
    let (mut client, backend, original, _) = fixture();
    client.recovery.fail_cleanup = true;
    let pending = submit(&mut client, "op.old").unwrap();
    terminal(&backend, &pending);
    let completed = client.recover_operation("op.old").unwrap();
    client.close().unwrap();
    let mut other = original.clone();
    other.scope.identity_id = "operator.2".to_owned();
    other.records = Arc::new(Mutex::new(BTreeMap::new()));
    client.replace_recovery_store(other.clone()).unwrap();
    backend.lock().unwrap().session["identityId"] = json!("operator.2");
    client.connect(&json!({})).unwrap();
    assert_eq!(client.cleanup_terminal(32), Ok(0));
    assert!(client.view().unwrap().completed.is_empty());
    assert_eq!(original.records.lock().unwrap().len(), 1);
    assert!(other.records.lock().unwrap().is_empty());
    client.close().unwrap();
    client.replace_recovery_store(original.clone()).unwrap();
    backend.lock().unwrap().session["identityId"] = json!("operator.1");
    client.connect(&json!({})).unwrap();
    assert_eq!(client.view().unwrap().completed, vec![completed]);
    assert_eq!(client.cleanup_terminal(32), Ok(1));
    assert!(original.records.lock().unwrap().is_empty());
    assert_eq!(backend.lock().unwrap().requests, 1);
}

#[test]
fn restore_and_admission_share_a_hard_aggregate_bound_without_erasing_terminal_facts() {
    let (mut client, _, _, _) = fixture();
    submit(&mut client, "template").unwrap();
    let template = client.ledger.pending.remove("template").unwrap();
    for index in 0..crate::ledger::MAX_RETAINED_OPERATIONS {
        let mut record = template.clone();
        let id = format!("retained.{index:04}");
        record.request.operation_id = id.clone();
        record.admitted_record["operationId"] = json!(id);
        record.state = OperationState::Terminal;
        record.audit_trace_id = Some("audit.1".to_owned());
        record.terminal_status = Some(OperationStatus::Succeeded);
        client.ledger.completed.insert(id, record);
    }
    let mut overflow = template.request.clone();
    overflow.operation_id = "overflow".to_owned();
    assert_eq!(
        client.ledger.reserve(overflow, /*now*/ 1000),
        Err(ControlError::new(ErrorCode::PendingLimit))
    );
    let mut incoming = template.admitted_record;
    incoming["operationId"] = json!("imported");
    assert_eq!(
        client
            .ledger
            .restore(BTreeMap::from([("imported".to_owned(), incoming)])),
        Err(ControlError::new(ErrorCode::PendingLimit))
    );
    assert!(client.ledger.pending.is_empty());
    assert_eq!(
        client.ledger.completed.len(),
        crate::ledger::MAX_RETAINED_OPERATIONS
    );
    assert!(
        client
            .ledger
            .completed
            .values()
            .all(|record| !record.cleanup_complete)
    );
}

#[test]
fn restore_is_monotone_for_exact_replays_and_atomic_for_conflicting_batches() {
    let (mut client, backend, store, _) = fixture();
    let first = submit(&mut client, "op.1").unwrap();
    let saved = store.records.lock().unwrap().clone();
    assert_eq!(client.ledger.restore(saved.clone()), Ok(()));
    assert_eq!(client.view().unwrap().pending, vec![first.clone()]);
    let mut new_record = saved["op.1"].clone();
    new_record["operationId"] = json!("op.0");
    let mut conflict = saved["op.1"].clone();
    conflict["sessionId"] = json!("other-session");
    assert_eq!(
        client.ledger.restore(BTreeMap::from([
            ("op.0".to_owned(), new_record),
            ("op.1".to_owned(), conflict)
        ])),
        Err(ControlError::new(ErrorCode::OperationConflict))
    );
    assert_eq!(client.view().unwrap().pending, vec![first.clone()]);
    terminal(&backend, &first);
    let completed = client.recover_operation("op.1").unwrap();
    assert_eq!(client.ledger.restore(saved), Ok(()));
    let view = client.view().unwrap();
    assert!(view.pending.is_empty());
    assert_eq!(view.completed, vec![completed]);
    assert_eq!(backend.lock().unwrap().requests, 1);
}
