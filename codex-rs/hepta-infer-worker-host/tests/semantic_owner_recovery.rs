//! Actual inference-owner file recovery with an explicit non-model driver.
//! These tests establish dispatch/result bookkeeping, not Laya task efficacy.
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::RetrievalSourceV1;
use codex_hepta_infer_core::SemanticRetrievalRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::semantic::SemanticPhaseV1;
use codex_hepta_infer_worker_host::model_worker::*;
use codex_hepta_types::Digest32;

static NONCE: AtomicU64 = AtomicU64::new(0);

struct PathGuard(PathBuf);

impl PathGuard {
    fn new() -> Self {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        Self(std::env::temp_dir().join(format!(
            "hepta-worker-semantic-{}-{stamp}-{nonce}.journal",
            std::process::id()
        )))
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.0, 32).expect("real owner journal")
    }
}

impl Drop for PathGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[derive(Clone, Copy)]
enum Behavior {
    Reply,
    Lost,
    Malformed,
    OverBudget,
    NoMemoryMeasurement,
}

struct Driver {
    calls: Arc<AtomicUsize>,
    behavior: Behavior,
}

impl ModelDriver for Driver {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle {
            opaque_id: "fixture.handle".to_string(),
            observed_memory_bytes: 128,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        panic!("numeric or text runner must not replace semantic dispatch")
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

impl SemanticRetrievalDriver for Driver {
    fn run_semantic_retrieval(
        &mut self,
        _handle: &DriverModelHandle,
        request_wire: &[u8],
    ) -> Result<DriverSemanticRetrievalReplyV1, Error> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        match self.behavior {
            Behavior::Lost => return Err(Error::DriverFailure("lost result".to_string())),
            Behavior::Malformed => return Ok(DriverSemanticRetrievalReplyV1 {
                reply_wire: b"not a terminal reply".to_vec(),
                observed_memory_bytes: 128,
            }),
            _ => {}
        }
        let input = SemanticRetrievalRequestV1::decode(request_wire).expect("valid input");
        let mut reply = b"HPTARS\x01\x00".to_vec();
        reply.extend_from_slice(Digest32::of_bytes(request_wire).as_array());
        reply.extend_from_slice(&[0x22; 32]);
        reply.extend_from_slice(&2_u32.to_be_bytes());
        reply.extend_from_slice(&100_000_u32.to_be_bytes());
        reply.extend_from_slice(&900_000_u32.to_be_bytes());
        let tokens: u64 = if matches!(self.behavior, Behavior::OverBudget) { 65 } else { 12 };
        reply.extend_from_slice(&tokens.to_be_bytes());
        reply.extend_from_slice(&0_u64.to_be_bytes());
        reply.extend_from_slice(&7_u64.to_be_bytes());
        input.decode_reply(&reply).expect("valid fixture reply");
        Ok(DriverSemanticRetrievalReplyV1 {
            reply_wire: reply,
            observed_memory_bytes: if matches!(self.behavior, Behavior::NoMemoryMeasurement) { 0 } else { 128 },
        })
    }
}

fn manifest() -> ModelManifest {
    ModelManifest {
        model_id: "model.1".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: "3".repeat(64),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    }
}

fn worker(behavior: Behavior, calls: Arc<AtomicUsize>) -> InferenceWorker<Driver> {
    InferenceWorker::new(100, "worker.1".to_string(), 3, ResourceGrant {
        grant_id: "grant.1".to_string(),
        authority_epoch: 2,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 2,
        maximum_active_requests: 1,
        maximum_memory_bytes: 1024,
        semantic_digest: "9".repeat(64),
    }, Driver { calls, behavior }).expect("worker")
}

fn call(id: &str) -> SemanticRetrievalCallV1 {
    let input = SemanticRetrievalRequestV1 {
        operation_id: id.to_string(),
        workspace_id: "workspace.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "3".repeat(64),
        bundle_digest: "2".repeat(64),
        deadline_ms: 9000,
        query: "q".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.1".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    };
    let payload = Digest32::of_bytes(&input.encode().expect("wire")).to_string();
    SemanticRetrievalCallV1 {
        input,
        authorization: WorkerRequest {
            request_id: id.to_string(),
            reservation_id: format!("reservation.{id}"),
            model_digest: "2".repeat(64),
            payload_digest: payload.clone(),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: payload,
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
    }
}

#[test]
fn actual_owner_reopen_returns_original_reply_without_loading_or_running_model() {
    let path = PathGuard::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let original;
    {
        let mut control = path.open();
        let mut first = worker(Behavior::Reply, Arc::clone(&calls));
        first.load_model(100, manifest()).expect("load");
        original = first.run_semantic_retrieval_durable(
            &mut control, 100, "principal.1", "model.1", call("op.1"),
        ).expect("first computation");
        assert!(original.delivery_pending());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
    let before = fs::read(&path.0).expect("journal");
    let mut control = path.open();
    let mut reopened = worker(Behavior::Lost, Arc::clone(&calls));
    let replayed = reopened.run_semantic_retrieval_durable(
        &mut control, 20_000, "principal.1", "model.1", call("op.1"),
    ).expect("historical observation, not current permission");
    assert_eq!(replayed, original);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(fs::read(&path.0).expect("journal"), before);
}

#[test]
fn lost_or_malformed_result_is_reconcile_only_across_worker_restarts() {
    for behavior in [Behavior::Lost, Behavior::Malformed] {
        let path = PathGuard::new();
        let calls = Arc::new(AtomicUsize::new(0));
        {
            let mut control = path.open();
            let mut first = worker(behavior, Arc::clone(&calls));
            first.load_model(100, manifest()).expect("load");
            assert!(first.run_semantic_retrieval_durable(
                &mut control, 100, "principal.1", "model.1", call("op.1"),
            ).is_err());
        }
        let mut control = path.open();
        let mut second = worker(Behavior::Reply, Arc::clone(&calls));
        let recovered = second.run_semantic_retrieval_durable(
            &mut control, 101, "principal.1", "model.1", call("op.1"),
        ).expect("unknown observation");
        assert!(recovered.execution_unknown());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        second.load_model(100, manifest()).expect("load for another request");
        assert!(second.run_semantic_retrieval_durable(
            &mut control, 101, "principal.1", "model.1", call("op.2"),
        ).is_err());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}

#[test]
fn cancellation_before_entry_is_durable_negative_without_model_call() {
    let path = PathGuard::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut control = path.open();
    let mut runtime = worker(Behavior::Reply, Arc::clone(&calls));
    runtime.load_model(100, manifest()).expect("load");
    let mut cancelled = call("op.1");
    cancelled.authorization.cancelled = true;
    let result = runtime.run_semantic_retrieval_durable(
        &mut control, 100, "principal.1", "model.1", cancelled,
    ).expect("negative");
    assert_eq!(result.phase, SemanticPhaseV1::NotDispatched);
    let retry = runtime.run_semantic_retrieval_durable(
        &mut control, 101, "principal.1", "model.1", call("op.1"),
    ).expect("same negative");
    assert_eq!(retry, result);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn cancellation_after_lost_response_does_not_prove_non_execution() {
    let path = PathGuard::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut control = path.open();
    let mut runtime = worker(Behavior::Lost, Arc::clone(&calls));
    runtime.load_model(100, manifest()).expect("load");
    assert!(runtime.run_semantic_retrieval_durable(
        &mut control, 100, "principal.1", "model.1", call("op.1"),
    ).is_err());
    let mut cancelled = call("op.1");
    cancelled.authorization.cancelled = true;
    let result = runtime.run_semantic_retrieval_durable(
        &mut control, 101, "principal.1", "model.1", cancelled,
    ).expect("cancel intent");
    assert!(result.execution_unknown());
    assert!(result.cancel_requested);
    assert!(!result.delivery_pending());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn complete_but_unusable_results_preserve_observed_bytes() {
    for behavior in [Behavior::OverBudget, Behavior::NoMemoryMeasurement] {
        let path = PathGuard::new();
        let calls = Arc::new(AtomicUsize::new(0));
        let mut control = path.open();
        let mut runtime = worker(behavior, Arc::clone(&calls));
        runtime.load_model(100, manifest()).expect("load");
        let result = runtime.run_semantic_retrieval_durable(
            &mut control, 100, "principal.1", "model.1", call("op.1"),
        ).expect("observed output");
        assert_eq!(result.phase, SemanticPhaseV1::Completed);
        assert!(result.completion.is_some());
        assert!(!result.delivery_pending());
        assert!(!result.within_resource_budget);
        runtime.run_semantic_retrieval_durable(
            &mut control, 101, "principal.1", "model.1", call("op.2"),
        ).expect("terminal observation released capacity");
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }
}

#[test]
fn principal_or_semantic_input_cannot_be_substituted_for_cached_result() {
    let path = PathGuard::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut control = path.open();
    let mut runtime = worker(Behavior::Reply, Arc::clone(&calls));
    runtime.load_model(100, manifest()).expect("load");
    runtime.run_semantic_retrieval_durable(
        &mut control, 100, "principal.1", "model.1", call("op.1"),
    ).expect("original");
    assert!(runtime.run_semantic_retrieval_durable(
        &mut control, 101, "principal.2", "model.1", call("op.1"),
    ).is_err());
    let mut changed = call("op.1");
    changed.input.workspace_id = "workspace.2".to_string();
    let digest = Digest32::of_bytes(&changed.input.encode().expect("wire")).to_string();
    changed.authorization.payload_digest = digest.clone();
    changed.authorization.lease_payload_digest = digest;
    assert!(runtime.run_semantic_retrieval_durable(
        &mut control, 101, "principal.1", "model.1", changed,
    ).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn invalid_or_expired_new_request_never_admits_or_dispatches() {
    let path = PathGuard::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut control = path.open();
    let mut runtime = worker(Behavior::Reply, Arc::clone(&calls));
    runtime.load_model(100, manifest()).expect("load");
    assert!(runtime.run_semantic_retrieval_durable(
        &mut control, 9000, "principal.1", "model.1", call("op.1"),
    ).is_err());
    assert!(control.semantic_record("op.1").expect("lookup").is_none());
    let mut wrong = call("op.2");
    wrong.authorization.lease_payload_digest = "a".repeat(64);
    assert!(runtime.run_semantic_retrieval_durable(
        &mut control, 101, "principal.1", "model.1", wrong,
    ).is_err());
    assert!(control.semantic_record("op.2").expect("lookup").is_none());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}
