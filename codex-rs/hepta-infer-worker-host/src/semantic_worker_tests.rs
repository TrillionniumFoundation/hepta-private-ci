//! Real journal reopening with a synthetic, counted model driver.
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::RetrievalSourceV1;

use super::super::DriverRunObservation;
use super::super::ModelManifest;
use super::super::ResourceGrant;
use super::*;

struct Driver(Arc<AtomicUsize>);

impl ModelDriver for Driver {
    fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
        panic!("history lookup must not load a model")
    }

    fn run(
        &mut self,
        _: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        panic!("history lookup must not invoke numeric inference")
    }

    fn unload(&mut self, _: DriverModelHandle) -> Result<(), Error> {
        panic!("history lookup must not unload a model")
    }
}

impl SemanticRetrievalDriver for Driver {
    fn run_semantic_retrieval(
        &mut self,
        _: &DriverModelHandle,
        _: &[u8],
    ) -> Result<DriverSemanticRetrievalReplyV1, Error> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(Error::DriverFailure("unexpected dispatch".to_string()))
    }
}

fn replacement(calls: Arc<AtomicUsize>) -> InferenceWorker<Driver> {
    InferenceWorker::new(
        100,
        "worker.replacement".to_string(),
        4,
        ResourceGrant {
            grant_id: "grant.replacement".to_string(),
            authority_epoch: 3,
            generation: 4,
            expires_at_ms: 200,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 8,
            maximum_memory_bytes: 2048,
            semantic_digest: "a".repeat(64),
        },
        Driver(calls),
    )
    .expect("replacement worker")
}

fn call() -> SemanticRetrievalCallV1 {
    let input = SemanticRetrievalRequestV1 {
        operation_id: "op.original".to_string(),
        workspace_id: "workspace.original".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "3".repeat(64),
        bundle_digest: "2".repeat(64),
        deadline_ms: 9000,
        query: "find alpha".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.original".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    };
    let digest = Digest32::of_bytes(&input.encode().expect("wire")).to_string();
    SemanticRetrievalCallV1 {
        input,
        authorization: WorkerRequest {
            request_id: "op.original".to_string(),
            reservation_id: "reservation.original".to_string(),
            model_digest: "2".repeat(64),
            payload_digest: digest.clone(),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: digest,
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
    }
}

fn seed(control: &mut DurableInferenceControl, phase: SemanticPhaseV1) -> SemanticRecordV1 {
    let input = call();
    let wire = input.input.encode().expect("wire");
    let reserved = control
        .reserve_semantic(
            100,
            SemanticAdmissionV1 {
                request_wire: wire.clone(),
                principal_id: "principal.original".to_string(),
                reservation_id: input.authorization.reservation_id,
                worker_id: "worker.original".to_string(),
                worker_generation: 3,
                maximum_tokens: 64,
                maximum_memory_bytes: 1024,
                authority_binding_digest: "9".repeat(64),
            },
            1,
        )
        .expect("original admission");
    if phase == SemanticPhaseV1::Reserved {
        return reserved;
    }
    if phase == SemanticPhaseV1::NotDispatched {
        return control.cancel_semantic("op.original").expect("cancel");
    }
    let fenced = control
        .fence_semantic_dispatch("op.original", reserved.revision, 101)
        .expect("original fence");
    if phase == SemanticPhaseV1::DispatchFenced {
        return fenced;
    }
    let mut reply = b"HPTARS\x01\x00".to_vec();
    reply.extend_from_slice(Digest32::of_bytes(&wire).as_array());
    reply.extend_from_slice(&[0x22; 32]);
    reply.extend_from_slice(&2_u32.to_be_bytes());
    reply.extend_from_slice(&100_000_u32.to_be_bytes());
    reply.extend_from_slice(&900_000_u32.to_be_bytes());
    for value in [12_u64, 0, 7] {
        reply.extend_from_slice(&value.to_be_bytes());
    }
    control
        .complete_semantic(
            "op.original",
            SemanticCompletionV1 {
                reply_wire: reply,
                observed_memory_bytes: Some(128),
            },
        )
        .expect("original completion")
}

#[test]
fn completed_unknown_and_negative_survive_replacement_without_rebinding() {
    for phase in [
        SemanticPhaseV1::Completed,
        SemanticPhaseV1::DispatchFenced,
        SemanticPhaseV1::NotDispatched,
    ] {
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("owner.journal");
        let original = seed(
            &mut DurableInferenceControl::open(&path, 32).expect("owner"),
            phase,
        );
        let before = std::fs::read(&path).expect("bytes");
        let mut reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut worker = replacement(Arc::clone(&calls));
        let observed = worker
            .run_semantic_retrieval_durable(
                &mut reopened,
                20_000,
                "principal.original",
                "model.not.loaded",
                call(),
            )
            .expect("historical observation after grant and request expiry");
        assert_eq!(observed, original);
        assert_eq!(std::fs::read(&path).expect("bytes"), before);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn cancelled_unknown_remains_unknown_after_replacement_and_reopen() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("owner.journal");
    let mut control = DurableInferenceControl::open(&path, 32).expect("owner");
    let original = seed(&mut control, SemanticPhaseV1::DispatchFenced);
    let mut cancelled = call();
    cancelled.authorization.cancelled = true;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = replacement(Arc::clone(&calls));
    let observed = worker
        .run_semantic_retrieval_durable(
            &mut control,
            150,
            "principal.original",
            "model.not.loaded",
            cancelled,
        )
        .expect("persist cancel intent, not a negative execution result");
    assert_eq!(observed.admission, original.admission);
    assert!(observed.execution_unknown());
    assert!(observed.cancel_requested);
    assert!(!observed.delivery_pending());
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
    let retry = worker
        .run_semantic_retrieval_durable(
            &mut reopened,
            20_000,
            "principal.original",
            "model.not.loaded",
            call(),
        )
        .expect("retry retains cancellation and original fence");
    assert_eq!(retry, observed);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn replacement_rejects_reserved_work_instead_of_implicitly_taking_ownership() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("owner.journal");
    let mut control = DurableInferenceControl::open(&path, 32).expect("owner");
    let original = seed(&mut control, SemanticPhaseV1::Reserved);
    let before = std::fs::read(&path).expect("bytes");
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = replacement(Arc::clone(&calls));
    assert!(
        worker
            .run_semantic_retrieval_durable(
                &mut control,
                150,
                "principal.original",
                "model.not.loaded",
                call(),
            )
            .is_err()
    );
    assert_eq!(
        control.semantic_record("op.original").expect("record"),
        Some(&original)
    );
    assert_eq!(std::fs::read(&path).expect("bytes"), before);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn historical_lookup_rejects_principal_reservation_budget_and_wire_substitution() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("owner.journal");
    let mut control = DurableInferenceControl::open(&path, 32).expect("owner");
    let original = seed(&mut control, SemanticPhaseV1::Completed);
    let before = std::fs::read(&path).expect("bytes");
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = replacement(Arc::clone(&calls));
    let mut reservation = call();
    reservation.authorization.reservation_id = "reservation.changed".to_string();
    let mut budget = call();
    budget.authorization.maximum_tokens = 63;
    let mut input = call();
    input.input.workspace_id = "workspace.changed".to_string();
    let digest = Digest32::of_bytes(&input.input.encode().expect("wire")).to_string();
    input.authorization.payload_digest = digest.clone();
    input.authorization.lease_payload_digest = digest;
    for (principal, request) in [
        ("principal.other", call()),
        ("principal.original", reservation),
        ("principal.original", budget),
        ("principal.original", input),
    ] {
        assert!(
            worker
                .run_semantic_retrieval_durable(
                    &mut control,
                    150,
                    principal,
                    "model.not.loaded",
                    request,
                )
                .is_err()
        );
    }
    assert_eq!(
        control.semantic_record("op.original").expect("record"),
        Some(&original)
    );
    assert_eq!(std::fs::read(&path).expect("bytes"), before);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}
