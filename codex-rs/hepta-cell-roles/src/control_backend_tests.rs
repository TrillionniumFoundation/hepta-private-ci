use super::*;
use crate::ControlDispatchStatusV1;
use crate::ControlRoleOwnerV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn intent(operation: ControlOperationKindV1, dispatch: &str) -> ControlDispatchIntentV1 {
    ControlDispatchIntentV1 {
        dispatch_id: StableId::new(dispatch).expect("dispatch id"),
        cell_id: StableId::new("cell.control.backend").expect("cell id"),
        generation: Generation::new(3).expect("generation"),
        scope_digest: digest("scope"),
        operation,
        request_digest: digest("request"),
        route_fence_digest: digest("fence"),
        idempotency_key_digest: digest(dispatch),
        payload_digest: digest("payload"),
        precondition_digest: digest("precondition"),
        effect_class_digest: digest("effect"),
        deadline_ms: 10,
        expiry_ms: 20,
        authority: AuthorityPosture::DENY_ALL,
    }
}

struct AcceptingBackend {
    calls: usize,
}

impl ControlDispatchBackendV1 for AcceptingBackend {
    fn submit(
        &mut self,
        intent: &ControlDispatchIntentV1,
    ) -> Result<ControlBackendSubmissionReceiptV1, ControlBackendErrorV1> {
        self.calls += 1;
        Ok(ControlBackendSubmissionReceiptV1 {
            dispatch_id: intent.dispatch_id.clone(),
            cell_id: intent.cell_id.clone(),
            generation: intent.generation,
            operation: intent.operation,
            intent_digest: intent.content_digest().expect("intent digest"),
            route_fence_digest: intent.route_fence_digest,
            backend_receipt_digest: digest("backend-submit"),
            already_submitted: self.calls > 1,
        })
    }
}

struct UnavailableBackend;

impl ControlDispatchBackendV1 for UnavailableBackend {
    fn submit(
        &mut self,
        _intent: &ControlDispatchIntentV1,
    ) -> Result<ControlBackendSubmissionReceiptV1, ControlBackendErrorV1> {
        Err(ControlBackendErrorV1::Unavailable(
            "registered owner missing",
        ))
    }
}

fn owner_path(label: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-control-backend-{label}-{}-{}.bin",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ))
}

fn setup(
    path: &std::path::Path,
    operation: ControlOperationKindV1,
    dispatch: &str,
) -> (DurableControlRoleOwnerV1, ControlDispatchIntentV1) {
    let mut owner = DurableControlRoleOwnerV1::open(path).expect("open");
    owner
        .activate_generation(
            StableId::new("cell.control.backend").expect("cell id"),
            Generation::new(3).expect("generation"),
            digest("fence"),
        )
        .expect("generation");
    let intent = intent(operation, dispatch);
    owner.prepare(intent.clone()).expect("prepare");
    (owner, intent)
}

#[test]
fn backend_submission_binds_all_control_roles_and_terminal_receipt() {
    for (index, operation) in [
        ControlOperationKindV1::Planner,
        ControlOperationKindV1::Router,
        ControlOperationKindV1::Communication,
        ControlOperationKindV1::ActionProposal,
    ]
    .into_iter()
    .enumerate()
    {
        let path = owner_path(&format!("role-{index}"));
        let dispatch_id = format!("dispatch.backend.role.{index}");
        let (mut owner, intent) = setup(&path, operation, &dispatch_id);
        let mut backend = AcceptingBackend { calls: 0 };
        let result = owner
            .submit_to_backend(&intent.dispatch_id, &mut backend)
            .expect("submit");
        let submission = match &result.outcome {
            ControlBackendDispatchOutcomeV1::Submitted(receipt) => receipt.clone(),
            ControlBackendDispatchOutcomeV1::Unavailable(error) => {
                panic!("unexpected unavailable backend: {error:?}")
            }
        };
        assert_eq!(
            result.local_receipt.status,
            ControlDispatchStatusV1::Forwarded
        );
        let terminal = ControlBackendTerminalReceiptV1 {
            dispatch_id: intent.dispatch_id.clone(),
            cell_id: intent.cell_id.clone(),
            generation: intent.generation,
            operation,
            intent_digest: intent.content_digest().expect("intent digest"),
            route_fence_digest: intent.route_fence_digest,
            submission_receipt_digest: submission.content_digest(),
            terminal_receipt_digest: digest("backend-terminal"),
        };
        let local_terminal = owner
            .record_backend_terminal(&intent.dispatch_id, &submission, &terminal)
            .expect("terminal");
        assert_eq!(local_terminal.status, ControlDispatchStatusV1::Terminal);
        let reopened = DurableControlRoleOwnerV1::open(&path).expect("reopen");
        assert_eq!(
            reopened
                .inner()
                .dispatch_intent(&intent.dispatch_id)
                .expect("intent"),
            &intent
        );
        let _ = std::fs::remove_file(path);
    }
}

#[test]
fn unavailable_backend_leaves_forwarded_outbox_for_retry() {
    let path = owner_path("unavailable");
    let (mut owner, intent) = setup(
        &path,
        ControlOperationKindV1::Communication,
        "dispatch.backend.unavailable",
    );
    let mut backend = UnavailableBackend;
    let result = owner
        .submit_to_backend(&intent.dispatch_id, &mut backend)
        .expect("local forward");
    assert_eq!(
        result.outcome,
        ControlBackendDispatchOutcomeV1::Unavailable(ControlBackendErrorV1::Unavailable(
            "registered owner missing",
        ))
    );
    assert_eq!(
        result.local_receipt.status,
        ControlDispatchStatusV1::Forwarded
    );
    let reopened = DurableControlRoleOwnerV1::open(&path).expect("reopen");
    assert_eq!(
        reopened
            .dispatch_receipt(&intent.dispatch_id)
            .expect("record")
            .status,
        ControlDispatchStatusV1::Forwarded
    );
    let _ = std::fs::remove_file(path);
}

#[test]
fn backend_receipt_mismatch_cannot_close_forwarded_record() {
    let path = owner_path("mismatch");
    let (mut owner, intent) = setup(
        &path,
        ControlOperationKindV1::Router,
        "dispatch.backend.mismatch",
    );
    let mut backend = AcceptingBackend { calls: 0 };
    let result = owner
        .submit_to_backend(&intent.dispatch_id, &mut backend)
        .expect("submit");
    let submission = match result.outcome {
        ControlBackendDispatchOutcomeV1::Submitted(receipt) => receipt,
        ControlBackendDispatchOutcomeV1::Unavailable(error) => panic!("unexpected: {error:?}"),
    };
    let mut terminal = ControlBackendTerminalReceiptV1 {
        dispatch_id: intent.dispatch_id.clone(),
        cell_id: intent.cell_id.clone(),
        generation: intent.generation,
        operation: intent.operation,
        intent_digest: intent.content_digest().expect("intent digest"),
        route_fence_digest: intent.route_fence_digest,
        submission_receipt_digest: submission.content_digest(),
        terminal_receipt_digest: digest("terminal"),
    };
    terminal.route_fence_digest = digest("stale-fence");
    assert_eq!(
        owner.record_backend_terminal(&intent.dispatch_id, &submission, &terminal),
        Err(ControlOwnerErrorV1::BackendReceiptMismatch)
    );
    let reopened = DurableControlRoleOwnerV1::open(&path).expect("reopen");
    assert_eq!(
        reopened
            .dispatch_receipt(&intent.dispatch_id)
            .expect("record")
            .status,
        ControlDispatchStatusV1::Forwarded
    );
    let _ = std::fs::remove_file(path);
}
