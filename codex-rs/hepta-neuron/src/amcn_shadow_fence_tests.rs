use super::*;

use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex, TryLockError,
};

use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureRequestV1, NeuronFeatureReceiptV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1, build_neuron_feature_receipt_v1,
};

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture error: {error:?}"))
}

fn request() -> NeuronModelRequestV1 {
    NeuronModelRequestV1 {
        request_id: checked(StableId::new("amcn:shadow:tick1")),
        config_id: checked(StableId::new("amcn:shadow:config1")),
        generation: checked(Generation::new(7)),
        model_id: checked(StableId::new("amcn:shadow:model1")),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"head"),
        weights_digest: Digest32::of_bytes(b"weights"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_vector_q24: vec![Q / 4, -Q / 8],
        expected_output_width: 5,
    }
}

#[derive(Clone, Debug)]
struct SourceSnapshot {
    scope: StableId,
    generation: Generation,
    source_frontier: Digest32,
    withdrawal_head: Digest32,
    quarantine_head: Digest32,
    manifest: Digest32,
    runtime_anchor: Digest32,
    withdrawn: bool,
    pending_recovery: bool,
}

fn snapshot() -> SourceSnapshot {
    SourceSnapshot {
        scope: checked(StableId::new("amcn:tenant:research")),
        generation: checked(Generation::new(7)),
        source_frontier: Digest32::of_bytes(b"source-frontier"),
        withdrawal_head: Digest32::of_bytes(b"withdrawal-register"),
        quarantine_head: Digest32::of_bytes(b"monotonic-ledger-head"),
        manifest: Digest32::of_bytes(b"source-ancestry-and-weights"),
        runtime_anchor: Digest32::of_bytes(b"runtime-independent-checkpoint"),
        withdrawn: false,
        pending_recovery: false,
    }
}

fn binding(request: &NeuronModelRequestV1, source: &SourceSnapshot) -> AmcnFencedModelBindingV1 {
    AmcnFencedModelBindingV1 {
        scope: source.scope.clone(),
        request_id: request.request_id.clone(),
        config_id: request.config_id.clone(),
        generation: request.generation,
        model_id: request.model_id.clone(),
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        weights_digest: request.weights_digest,
        input_digest: request.input_digest,
        expected_output_width: request.expected_output_width,
        artifact_manifest_digest: source.manifest,
        source_frontier_digest: source.source_frontier,
        withdrawal_registry_head_digest: source.withdrawal_head,
        quarantine_journal_head_digest: source.quarantine_head,
        runtime_anchor_digest: source.runtime_anchor,
    }
}

struct TestFence {
    state: Arc<Mutex<SourceSnapshot>>,
    visits: Arc<AtomicUsize>,
}

impl AmcnSourceArtifactFence for TestFence {
    fn with_fenced_candidate<T>(
        &mut self,
        bound: &AmcnFencedModelBindingV1,
        request: &NeuronModelRequestV1,
        action: impl FnOnce() -> Result<T, NeuronModelError>,
    ) -> Result<T, NeuronModelError> {
        // A POSIX/same-process mock of the REQUIRED host transaction fence.
        // This is not a CognitiveStore or persistent withdrawal witness.
        let locked = self.state.lock().map_err(|_| NeuronModelError::Indeterminate)?;
        if locked.withdrawn
            || locked.pending_recovery
            || locked.scope != bound.scope
            || locked.generation != bound.generation
            || request.generation != locked.generation
            || locked.source_frontier != bound.source_frontier_digest
            || locked.withdrawal_head != bound.withdrawal_registry_head_digest
            || locked.quarantine_head != bound.quarantine_journal_head_digest
            || locked.manifest != bound.artifact_manifest_digest
            || locked.runtime_anchor != bound.runtime_anchor_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        self.visits.fetch_add(1, Ordering::SeqCst);
        // Deliberately hold locked across the REAL inference.control dispatch.
        let answer = action();
        drop(locked);
        answer
    }
}

struct Control {
    source: Arc<Mutex<SourceSnapshot>>,
    calls: Arc<AtomicUsize>,
    status: NeuronFeatureTerminalStatusV1,
    corrupt: bool,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        assert!(
            matches!(self.source.try_lock(), Err(TryLockError::WouldBlock)),
            "a competing source writer could acquire the lock DURING model invocation"
        );
        let success = self.status == NeuronFeatureTerminalStatusV1::Succeeded;
        let mut receipt = checked(build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: Digest32::of_bytes(b"real-manifest-port"),
                weights_digest: request.weights_digest,
                tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
                preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
                quantization_digest: Digest32::of_bytes(b"quantization"),
                runtime_digest: Digest32::of_bytes(b"runtime"),
                device_digest: Digest32::of_bytes(b"host-device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: if success {
                    vec![Q; request.expected_output_width]
                } else {
                    Vec::new()
                },
                prediction_q24: if success {
                    vec![0; request.expected_output_width]
                } else {
                    Vec::new()
                },
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 1024,
                queue_age_micros: 1,
                latency_micros: 17,
                status: self.status,
            },
        ));
        if self.corrupt {
            receipt.receipt_digest = Digest32::of_bytes(b"forged-feature-receipt");
        }
        Ok(receipt)
    }
}

struct Scenario {
    source: Arc<Mutex<SourceSnapshot>>,
    visits: Arc<AtomicUsize>,
    model_calls: Arc<AtomicUsize>,
}

impl Scenario {
    fn new() -> Self {
        Self {
            source: Arc::new(Mutex::new(snapshot())),
            visits: Arc::new(AtomicUsize::new(0)),
            model_calls: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn snapshot(&self) -> SourceSnapshot {
        checked(self.source.lock()).clone()
    }

    fn execute(
        &self,
        bound: AmcnFencedModelBindingV1,
        request: &NeuronModelRequestV1,
        status: NeuronFeatureTerminalStatusV1,
        corrupt: bool,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let mut owner = TestFence {
            state: Arc::clone(&self.source),
            visits: Arc::clone(&self.visits),
        };
        let mut control = Control {
            source: Arc::clone(&self.source),
            calls: Arc::clone(&self.model_calls),
            status,
            corrupt,
        };
        let mut port = AmcnFencedNeuronModelPort::new(&mut owner, &mut control, bound);
        port.execute(request)
    }

    fn success(
        &self,
        bound: AmcnFencedModelBindingV1,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.execute(bound, request, NeuronFeatureTerminalStatusV1::Succeeded, false)
    }
}

#[test]
fn amcn_shadow_fence_holds_owner_lock_during_real_inference_control_model_port() {
    let case = Scenario::new();
    let request = request();
    let bound = binding(&request, &case.snapshot());
    let result = checked(case.success(bound, &request));
    assert_eq!(result.drive_q24, vec![Q; 5]);
    assert_eq!(case.visits.load(Ordering::SeqCst), 1);
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 1);
    assert!(case.source.try_lock().is_ok(), "fence should release after result");
    assert!(!AMCN_SHADOW_PRODUCTION_ACCEPTED);
}

#[test]
fn amcn_shadow_fence_revocation_and_pending_recovery_never_call_model() {
    let case = Scenario::new();
    let request = request();
    let bound = binding(&request, &case.snapshot());
    {
        let mut state = checked(case.source.lock());
        state.withdrawn = true;
    }
    assert_eq!(case.success(bound.clone(), &request), Err(NeuronModelError::Rejected));
    {
        let mut state = checked(case.source.lock());
        state.withdrawn = false;
        state.pending_recovery = true;
    }
    assert_eq!(case.success(bound, &request), Err(NeuronModelError::Rejected));
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 0);
}

#[test]
fn amcn_shadow_fence_restored_source_must_not_reset_persisted_quarantine() {
    let case = Scenario::new();
    let request = request();
    let before = case.snapshot();
    let bound = binding(&request, &before);
    {
        let mut state = checked(case.source.lock());
        // Simulate restored identical source bytes but advanced durable
        // quarantine and withdrawal heads after a revocation.
        state.quarantine_head = Digest32::of_bytes(b"revoked-ancestor-persisted");
        state.withdrawal_head = Digest32::of_bytes(b"withdrawal-after-restart");
        state.withdrawn = true;
    }
    assert_eq!(case.success(bound.clone(), &request), Err(NeuronModelError::Rejected));
    {
        let mut state = checked(case.source.lock());
        state.withdrawn = false;
        state.pending_recovery = true;
    }
    let updated = binding(&request, &case.snapshot());
    assert_eq!(case.success(updated, &request), Err(NeuronModelError::Rejected));
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 0);
}

#[test]
fn amcn_shadow_fence_exact_request_identity_and_generation_checked_before_owner() {
    let case = Scenario::new();
    let req = request();
    let bound = binding(&req, &case.snapshot());

    let mut changed = req.clone();
    changed.head_digest = Digest32::of_bytes(b"swapped-head");
    assert_eq!(case.success(bound.clone(), &changed), Err(NeuronModelError::Rejected));
    changed = req.clone();
    changed.weights_digest = Digest32::of_bytes(b"swapped-weights");
    assert_eq!(case.success(bound.clone(), &changed), Err(NeuronModelError::Rejected));
    changed = req.clone();
    changed.input_digest = Digest32::of_bytes(b"forged-feature-input");
    assert_eq!(case.success(bound.clone(), &changed), Err(NeuronModelError::Rejected));
    changed = req.clone();
    changed.generation = checked(Generation::new(8));
    assert_eq!(case.success(bound.clone(), &changed), Err(NeuronModelError::Rejected));
    changed = req.clone();
    changed.request_id = checked(StableId::new("amcn:other-tick"));
    assert_eq!(case.success(bound.clone(), &changed), Err(NeuronModelError::Rejected));
    let mut zero = bound;
    zero.runtime_anchor_digest = Digest32::ZERO;
    assert_eq!(case.success(zero, &req), Err(NeuronModelError::Rejected));
    assert_eq!(case.visits.load(Ordering::SeqCst), 0);
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 0);
}

#[test]
fn amcn_shadow_fence_owner_rollback_or_source_change_is_rejected_before_model() {
    let case = Scenario::new();
    let req = request();
    let bound = binding(&req, &case.snapshot());
    {
        let mut state = checked(case.source.lock());
        state.source_frontier = Digest32::of_bytes(b"changed-source-revision");
    }
    assert_eq!(case.success(bound.clone(), &req), Err(NeuronModelError::Rejected));
    {
        let mut state = checked(case.source.lock());
        state.source_frontier = bound.source_frontier_digest;
        state.runtime_anchor = Digest32::of_bytes(b"independent-witness-advanced");
    }
    assert_eq!(case.success(bound, &req), Err(NeuronModelError::Rejected));
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 0);
}

#[test]
fn amcn_shadow_fence_preserves_verified_failed_and_indeterminate_terminals() {
    let case = Scenario::new();
    let req = request();
    let bound = binding(&req, &case.snapshot());
    assert_eq!(
        case.execute(
            bound.clone(),
            &req,
            NeuronFeatureTerminalStatusV1::Indeterminate,
            false,
        ),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(
        case.execute(bound.clone(), &req, NeuronFeatureTerminalStatusV1::Failed, false),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(
        case.execute(
            bound,
            &req,
            NeuronFeatureTerminalStatusV1::Succeeded,
            true,
        ),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(case.model_calls.load(Ordering::SeqCst), 3);
}
