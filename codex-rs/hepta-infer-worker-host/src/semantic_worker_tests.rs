//! Real durable-owner reopen and resource guards; model replies are synthetic.
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::RetrievalSourceV1;

use super::super::DriverRunObservation;
use super::super::ModelManifest;
use super::super::ResourceGrant;
use super::*;

#[derive(Clone, Copy)]
enum Mode {
    Complete,
    Fail,
    Incomplete,
    MissingMemory,
    OverBudget,
    Malformed,
    Panic,
}

struct Driver {
    journal: PathBuf,
    calls: Arc<AtomicUsize>,
    mode: Mode,
}

impl ModelDriver for Driver {
    fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle {
            opaque_id: "handle.1".to_string(),
            observed_memory_bytes: 32,
        })
    }

    fn run(
        &mut self,
        _: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        panic!("semantic work must not become numeric inference")
    }

    fn unload(&mut self, _: &DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

impl SemanticRetrievalDriver for Driver {
    fn run_semantic_retrieval(
        &mut self,
        _: &DriverModelHandle,
        wire: &[u8],
        limits: &SemanticResourceLimitsV2,
    ) -> Result<DriverSemanticRetrievalReplyV2, Error> {
        // A real file read at physical-entry time, not a mocked fsync callback.
        let journal = std::fs::read_to_string(&self.journal).expect("durable journal");
        assert!(journal.contains("ReserveResourcesV2"));
        assert!(journal.contains("\"Fence\""));
        assert_eq!(limits.total_bytes().expect("bound"), 128);
        self.calls.fetch_add(1, Ordering::SeqCst);
        match self.mode {
            Mode::Fail => return Err(Error::DriverFailure("lost response".to_string())),
            Mode::Panic => panic!("driver panicked after entry"),
            Mode::Complete
            | Mode::Incomplete
            | Mode::MissingMemory
            | Mode::OverBudget
            | Mode::Malformed => {}
        }
        let request = SemanticRetrievalRequestV1::decode(wire).expect("request");
        let mut reply = b"HPTARS\x01\x00".to_vec();
        reply.extend_from_slice(Digest32::of_bytes(wire).as_array());
        reply.extend_from_slice(&[0x22; 32]);
        reply.extend_from_slice(&2_u32.to_be_bytes());
        reply.extend_from_slice(&100_000_u32.to_be_bytes());
        reply.extend_from_slice(&900_000_u32.to_be_bytes());
        for value in [12_u64, 0, 7] {
            reply.extend_from_slice(&value.to_be_bytes());
        }
        request
            .decode_reply(&reply)
            .expect("valid reply before mutation");
        if matches!(self.mode, Mode::Malformed) {
            reply.push(0);
        }
        Ok(DriverSemanticRetrievalReplyV2 {
            reply_wire: reply,
            terminal_observed: !matches!(self.mode, Mode::Incomplete),
            observed_memory_bytes: match self.mode {
                Mode::MissingMemory => None,
                Mode::OverBudget => Some(512),
                Mode::Complete | Mode::Fail | Mode::Incomplete | Mode::Malformed | Mode::Panic => {
                    Some(96)
                }
            },
        })
    }
}

fn worker(
    path: PathBuf,
    calls: Arc<AtomicUsize>,
    mode: Mode,
    generation: u64,
    memory: u64,
) -> InferenceWorker<Driver> {
    InferenceWorker::new(
        100,
        format!("worker.{generation}"),
        generation,
        ResourceGrant {
            grant_id: format!("grant.{generation}"),
            authority_epoch: 1,
            generation,
            expires_at_ms: 5000,
            revoked: false,
            maximum_models: 2,
            maximum_active_requests: 2,
            maximum_memory_bytes: memory,
            semantic_digest: format!("{generation:x}").repeat(64),
        },
        Driver {
            journal: path,
            calls,
            mode,
        },
    )
    .expect("worker")
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
        maximum_tokens: 256,
        maximum_resident_bytes: 64,
    }
}

fn call() -> SemanticRetrievalCallV2 {
    let input = SemanticRetrievalRequestV1 {
        operation_id: "op.1".to_string(),
        workspace_id: "workspace.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "3".repeat(64),
        bundle_digest: "2".repeat(64),
        deadline_ms: 9000,
        query: "find alpha".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.1".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    };
    let payload = Digest32::of_bytes(&input.encode().expect("wire")).to_string();
    SemanticRetrievalCallV2 {
        input,
        maximum_resident_bytes: 64,
        authorization: WorkerRequest {
            request_id: "op.1".to_string(),
            reservation_id: "reservation.1".to_string(),
            model_digest: "2".repeat(64),
            payload_digest: payload.clone(),
            maximum_tokens: 64,
            deadline_ms: 9000,
            lease_payload_digest: payload,
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
            maximum_kv_bytes: 16,
            maximum_transient_bytes: 48,
        },
    }
}

#[test]
fn result_reopens_under_replacement_and_never_runs_again() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("journal");
    let calls = Arc::new(AtomicUsize::new(0));
    let mut owner = DurableInferenceControl::open(&path, 32).expect("owner");
    let mut first = worker(path.clone(), Arc::clone(&calls), Mode::Complete, 3, 256);
    first.load_model(100, manifest()).expect("load");
    let result = first
        .run_semantic_retrieval_durable(&mut owner, 100, "principal.1", "model.1", call())
        .expect("result");
    assert!(result.delivery_pending());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        first.resource_snapshot().expect("resources").reserved_bytes,
        64
    );
    drop(owner);
    let before = std::fs::read(&path).expect("bytes");
    let mut owner = DurableInferenceControl::open(&path, 32).expect("reopen");
    let mut replacement = worker(path.clone(), Arc::clone(&calls), Mode::Fail, 4, 64);
    let replay = replacement
        .run_semantic_retrieval_durable(&mut owner, 20_000, "principal.1", "model.1", call())
        .expect("expired history, no loaded model");
    assert_eq!(replay, result);
    assert_eq!(std::fs::read(&path).expect("bytes"), before);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let mut altered = call();
    altered.authorization.maximum_kv_bytes += 1;
    altered.authorization.maximum_transient_bytes -= 1;
    assert!(
        replacement
            .run_semantic_retrieval_durable(&mut owner, 20_000, "principal.1", "model.1", altered)
            .is_err()
    );
    assert!(
        replacement
            .run_semantic_retrieval_durable(
                &mut owner,
                20_000,
                "principal.other",
                "model.1",
                call()
            )
            .is_err()
    );
    assert_eq!(std::fs::read(&path).expect("bytes"), before);
}

#[test]
fn unknown_cancel_and_reopen_do_not_refund_or_redispatch() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("journal");
    let calls = Arc::new(AtomicUsize::new(0));
    let mut owner = DurableInferenceControl::open(&path, 32).expect("owner");
    let mut first = worker(path.clone(), Arc::clone(&calls), Mode::Fail, 3, 256);
    first.load_model(100, manifest()).expect("load");
    assert!(
        first
            .run_semantic_retrieval_durable(&mut owner, 100, "principal.1", "model.1", call())
            .is_err()
    );
    let resources = first.resource_snapshot().expect("resources");
    assert!(resources.fenced);
    assert_eq!(resources.reserved_bytes, 128);
    assert_eq!(resources.quarantined_reservations, 1);
    drop(owner);
    let mut owner = DurableInferenceControl::open(&path, 32).expect("reopen");
    let mut replacement = worker(path, Arc::clone(&calls), Mode::Complete, 4, 64);
    let mut cancelled = call();
    cancelled.authorization.cancelled = true;
    let result = replacement
        .run_semantic_retrieval_durable(&mut owner, 20_000, "principal.1", "model.1", cancelled)
        .expect("cancelled history");
    assert!(result.execution_unknown());
    assert!(result.cancel_requested);
    assert!(!result.delivery_pending());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn cancellation_and_capacity_rejection_do_not_enter_driver() {
    for memory in [100, 256] {
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("journal");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut owner = DurableInferenceControl::open(&path, 32).expect("owner");
        let mut worker = worker(path, Arc::clone(&calls), Mode::Complete, 3, memory);
        worker.load_model(100, manifest()).expect("load");
        let mut cancelled = call();
        cancelled.authorization.cancelled = true;
        let result = worker.run_semantic_retrieval_durable(
            &mut owner,
            100,
            "principal.1",
            "model.1",
            cancelled,
        );
        if memory == 100 {
            assert!(result.is_err());
            assert!(owner.semantic_record("op.1").expect("lookup").is_none());
        } else {
            assert_eq!(
                result.expect("cancel").phase,
                SemanticPhaseV1::NotDispatched
            );
        }
        assert_eq!(
            worker
                .resource_snapshot()
                .expect("resources")
                .reserved_bytes,
            64
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn missing_measurement_and_over_budget_preserve_result_but_block_delivery() {
    for mode in [Mode::MissingMemory, Mode::OverBudget] {
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("journal");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut owner = DurableInferenceControl::open(&path, 32).expect("owner");
        let mut worker = worker(path.clone(), calls, mode, 3, 256);
        worker.load_model(100, manifest()).expect("load");
        let observed = worker
            .run_semantic_retrieval_durable(&mut owner, 100, "principal.1", "model.1", call())
            .expect("retain observation");
        assert_eq!(observed.phase, SemanticPhaseV1::Completed);
        assert!(!observed.delivery_pending());
        assert!(worker.resource_snapshot().expect("resources").fenced);
        drop(owner);
        let reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
        assert_eq!(
            reopened.semantic_record("op.1").expect("history"),
            Some(&observed)
        );
    }
}

#[test]
fn malformed_nonterminal_and_panicking_driver_leave_durable_unknown() {
    for mode in [Mode::Malformed, Mode::Incomplete, Mode::Panic] {
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("journal");
        let calls = Arc::new(AtomicUsize::new(0));
        let mut owner = DurableInferenceControl::open(&path, 32).expect("owner");
        let mut worker = worker(path.clone(), Arc::clone(&calls), mode, 3, 256);
        worker.load_model(100, manifest()).expect("load");
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            worker.run_semantic_retrieval_durable(&mut owner, 100, "principal.1", "model.1", call())
        }));
        assert!(!matches!(result, Ok(Ok(_))));
        assert!(worker.resource_snapshot().expect("resources").fenced);
        assert_eq!(
            worker
                .resource_snapshot()
                .expect("resources")
                .reserved_bytes,
            128
        );
        drop(owner);
        let reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
        assert!(
            reopened
                .semantic_record("op.1")
                .expect("lookup")
                .expect("record")
                .execution_unknown()
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
