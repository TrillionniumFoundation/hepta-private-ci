use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-runtime-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn file(&self) -> File {
        self.named_file("journal")
    }

    fn named_file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(self.0.join(name)),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Default)]
struct MemoryWitness {
    current: Arc<Mutex<Option<JournalAnchor>>>,
    fail_next: Arc<AtomicBool>,
}

impl MemoryWitness {
    fn fail_next_compare_and_swap(&self) {
        self.fail_next.store(true, Ordering::SeqCst);
    }
}

impl AnchorWitnessStore for MemoryWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.current
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.fail_next.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        let mut current = self
            .current
            .lock()
            .map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        Ok(())
    }
}

struct FakeModel {
    calls: usize,
    corrupt_head: bool,
}

impl FakeModel {
    fn new() -> Self {
        Self {
            calls: 0,
            corrupt_head: false,
        }
    }
}

impl NeuronModelPort for FakeModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls += 1;
        let drive_q24 = (0..request.expected_output_width)
            .map(|index| match index {
                0 => Q,
                1 => Q / 2,
                _ => 0,
            })
            .collect::<Vec<_>>();
        let prediction_q24 = vec![0; request.expected_output_width];
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: Digest32::of_bytes(b"manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
            quantization_id: checked(StableId::new("q8")),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            backend_id: checked(StableId::new("cpu.reference")),
            runtime_digest: Digest32::of_bytes(b"runtime"),
            device_identity_digest: Digest32::of_bytes(b"device"),
            latency_micros: 50,
            resident_bytes: 4096,
        };
        let output_digest = checked(canonical_model_output_digest_v1(
            &drive_q24,
            &prediction_q24,
            &runtime_receipt,
        ));
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: if self.corrupt_head {
                Digest32::of_bytes(b"wrong-head")
            } else {
                request.head_digest
            },
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 7,
            transient_allocation_bytes: 8192,
            runtime_receipt,
        })
    }
}

fn native_config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn runtime_config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("neuron.config.1")),
        generation: native.generation,
        model_id: checked(StableId::new("model.1")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: native.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn subject() -> StableId {
    checked(StableId::new("subject.1"))
}

fn objective() -> Digest32 {
    Digest32::of_bytes(b"objective")
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: checked(subject_scope_digest(&subject())),
        objective_digest: objective(),
    }
}

fn input(sequence: u64, checkpoint_digest: Digest32) -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: checked(StableId::new(format!("tick.{sequence}"))),
        subject_id: subject(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1000,
        checkpoint_digest,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn canonical_runtime_commits_model_bound_calibrated_signal_and_recovers() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 16,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert!(!first.tick.abstain);
    assert_eq!(first.tick.sparsity_ppm, 200_000);
    assert_eq!(first.signal.model_runtime_digest.is_zero(), false);
    assert_eq!(model.calls, 1);
    let eligibility = checked(runtime.current_eligibility_sample()).expect("committed eligibility");
    assert_eq!(eligibility.checkpoint_digest(), first.tick.checkpoint_after);
    assert_eq!(eligibility.eligibility_q24().len(), native.width);
    let first_anchor = checked(runtime.current_anchor()).expect("committed anchor");
    assert_eq!(checked(witness.current()), Some(first_anchor));
    drop(runtime);

    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config,
        first_anchor,
        witness,
    ));
    assert_eq!(checked(recovered.current_anchor()), Some(first_anchor));
    let second = checked(recovered.tick(&mut model, input(2, first_anchor.checkpoint_digest)));
    assert_eq!(
        second.tick.checkpoint_before,
        first_anchor.checkpoint_digest
    );
    assert_eq!(model.calls, 2);
}

#[test]
fn witness_failure_after_commit_reconciles_without_reinvoking_model() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config,
        witness.clone(),
    ));
    witness.fail_next_compare_and_swap();
    let tick = input(1, Digest32::ZERO);
    let mut model = FakeModel::new();
    let failure = runtime.tick(&mut model, tick.clone()).err();
    assert!(matches!(
        failure,
        Some(NeuronRuntimeError::WitnessAfterCommit { .. })
    ));
    assert_eq!(model.calls, 1);
    let recovered = checked(runtime.tick(&mut model, tick));
    assert_eq!(model.calls, 1);
    let current_anchor = checked(runtime.current_anchor()).expect("reconciled anchor");
    assert_eq!(checked(witness.current()), Some(current_anchor));
    assert_eq!(
        recovered.tick.checkpoint_after,
        current_anchor.checkpoint_digest
    );
}

#[test]
fn model_identity_drift_rejects_before_checkpoint_mutation() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    model.corrupt_head = true;
    assert_eq!(
        runtime.tick(&mut model, input(1, Digest32::ZERO)).err(),
        Some(NeuronRuntimeError::ModelBindingMismatch)
    );
    assert_eq!(checked(runtime.current_anchor()), None);
}

#[test]
fn collapse_or_ood_forces_abstention_without_granting_authority() {
    let fixture = Fixture::new();
    let native = native_config();
    let mut config = runtime_config(&native);
    config.calibration.maximum_ood_ppm = 10_000;
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let output = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert!(output.tick.abstain);
    assert!(!output.signal.authority.grants_any());
}

#[test]
fn expired_calibration_advances_state_but_forces_fail_closed_abstention() {
    let fixture = Fixture::new();
    let native = native_config();
    let mut config = runtime_config(&native);
    config.calibration.expires_after_sequence = 1;
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness,
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let first_anchor = checked(runtime.current_anchor()).expect("first anchor");
    assert!(!first.tick.abstain);
    let second = checked(runtime.tick(&mut model, input(2, first_anchor.checkpoint_digest)));
    assert!(second.tick.abstain);
    assert_eq!(second.tick.confidence_ppm, 0);
    assert_eq!(second.tick.ood_ppm, 1_000_000);
    assert_eq!(
        checked(runtime.current_anchor())
            .expect("second anchor")
            .sequence,
        2
    );
}

#[test]
fn runtime_rollover_and_chain_recovery_preserve_latest_witness() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let final_anchor = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 2,
            config.clone(),
            witness.clone(),
        ));
        let mut model = FakeModel::new();
        let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
        let second = checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
        checked(runtime.rollover(fixture.named_file("successor"), /*max_records*/ 2));
        let third = checked(runtime.tick(&mut model, input(3, second.tick.checkpoint_after)));
        let fourth = checked(runtime.tick(&mut model, input(4, third.tick.checkpoint_after)));
        JournalAnchor {
            sequence: 4,
            checkpoint_digest: fourth.tick.checkpoint_after,
        }
    };
    assert_eq!(checked(witness.current()), Some(final_anchor));

    let mut recovered = checked(NeuronRuntime::recover_chain_root(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 2,
        config,
        witness.clone(),
    ));
    assert_eq!(
        checked(recovered.current_anchor())
            .expect("root end")
            .sequence,
        2
    );
    checked(recovered.recover_next_segment(fixture.named_file("successor"), /*max_records*/ 2));
    assert_eq!(checked(recovered.current_anchor()), Some(final_anchor));
    assert_eq!(checked(witness.current()), Some(final_anchor));
}

#[test]
fn deletion_rebuild_starts_fresh_successor_generation_without_old_state() {
    let fixture = Fixture::new();
    let old_native = native_config();
    let old_config = runtime_config(&old_native);
    let mut old_runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        old_native,
        scope(),
        /*max_records*/ 4,
        old_config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let committed = checked(old_runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let predecessor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: committed.tick.checkpoint_after,
    };
    drop(old_runtime);

    let mut successor_native = native_config();
    successor_native.generation = checked(Generation::new(2));
    let successor_config = runtime_config(&successor_native);
    let plan = NeuronDeletionRebuildPlanV1 {
        rebuild_id: checked(StableId::new("neuron-rebuild:runtime")),
        predecessor_generation: checked(Generation::new(1)),
        successor_generation: checked(Generation::new(2)),
        predecessor_checkpoint_digest: predecessor.checkpoint_digest,
        withdrawal_registry_head_digest: Digest32::of_bytes(b"withdrawal-head"),
        withdrawal_event_digest: Digest32::of_bytes(b"withdrawal-event"),
        retained_dataset_set_digest: Digest32::of_bytes(b"retained-datasets"),
        source_event_set_digest: Digest32::of_bytes(b"retained-events"),
        retained_event_count: 10,
        deleted_event_count: 2,
    };
    let (mut rebuilt, receipt) = checked(NeuronRuntime::bootstrap_after_deletion(
        fixture.named_file("rebuild"),
        successor_native,
        scope(),
        /*max_records*/ 4,
        successor_config,
        MemoryWitness::default(),
        predecessor,
        &plan,
    ));
    assert!(!receipt.state_reused);
    assert_eq!(checked(rebuilt.current_anchor()), None);
    let rebuilt_first = checked(rebuilt.tick(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(rebuilt_first.tick.checkpoint_before, Digest32::ZERO);
    assert_ne!(
        rebuilt_first.tick.checkpoint_after,
        predecessor.checkpoint_digest
    );
}


// This feature-only test uses the actual NeuronRuntime journal and independent
// AnchorWitnessStore, not merely an inference.control receipt fixture.
// A pending Journal commit may otherwise return its cached model output without
// calling InferenceControlModelPort again, so the whole tick needs source fencing.
#[cfg(feature = "amcn-shadow")]
mod amcn_pending_runtime {
    use super::*;

    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::TryLockError;

    use codex_hepta_infer_core::{
        NeuronFeatureObservationV1, NeuronFeatureReceiptV1, NeuronFeatureRequestV1,
        NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1,
        build_neuron_feature_receipt_v1,
    };
    use pretty_assertions::assert_eq;
    use crate::{
        AmcnFencedModelBindingV1, AmcnSourceArtifactFence, NeuronInferenceControlPort,
        NeuronModelError,
    };

    struct LiveSourceGate {
        source_lease: Arc<Mutex<bool>>,
        checks: Arc<AtomicUsize>,
    }

    /// Independently witnessed Journal CAS must execute under the same lock.
    #[derive(Clone)]
    struct FencedWitness {
        original: MemoryWitness,
        source_lease: Arc<Mutex<bool>>,
        cas_checks: Arc<AtomicUsize>,
    }

    impl AnchorWitnessStore for FencedWitness {
        fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
            self.original.current()
        }

        fn compare_and_swap(
            &mut self,
            expected: Option<JournalAnchor>,
            next: JournalAnchor,
        ) -> Result<(), WitnessStoreError> {
            assert!(
                matches!(self.source_lease.try_lock(), Err(TryLockError::WouldBlock)),
                "source lease RELEASED before real Runtime Witness CAS"
            );
            self.cas_checks.fetch_add(1, Ordering::SeqCst);
            self.original.compare_and_swap(expected, next)
        }
    }

    impl AmcnSourceArtifactFence for LiveSourceGate {
        fn with_fenced_candidate<T, E>(
            &mut self,
            _binding: &AmcnFencedModelBindingV1,
            _request: &NeuronModelRequestV1,
            action: impl FnOnce() -> Result<T, E>,
        ) -> Result<T, E>
        where
            E: From<NeuronModelError>,
        {
            let owner_lock = self.source_lease.lock()
                .map_err(|_| E::from(NeuronModelError::Indeterminate))?;
            self.checks.fetch_add(1, Ordering::SeqCst);
            if !*owner_lock {
                return Err(E::from(NeuronModelError::Rejected));
            }
            // One local critical section covers actual InferenceControl,
            // Journal commit AND independent runtime Witness CAS.
            let outcome = action();
            drop(owner_lock);
            outcome
        }
    }

    struct OwnerControl {
        config: NeuronRuntimeConfigV1,
        calls: Arc<AtomicUsize>,
        source_lease: Arc<Mutex<bool>>,
    }

    impl NeuronInferenceControlPort for OwnerControl {
        fn execute_feature(
            &mut self,
            request: &NeuronFeatureRequestV1,
        ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
            assert!(
                matches!(self.source_lease.try_lock(), Err(TryLockError::WouldBlock)),
                "source lease RELEASED before actual inference.control call"
            );
            self.calls.fetch_add(1, Ordering::SeqCst);
            let config = &self.config;
            let runtime_tuple = NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: config.model_manifest_digest,
                weights_digest: request.weights_digest,
                tokenizer_digest: config.tokenizer_digest,
                preprocessor_digest: config.preprocessor_digest,
                quantization_digest: config.quantization_digest,
                runtime_digest: config.runtime_digest,
                device_digest: config.device_digest,
            };
            let observation = NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: (0..request.expected_output_width)
                    .map(|index| match index { 0 => Q, 1 => Q / 2, _ => 0 })
                    .collect(),
                prediction_q24: vec![0; request.expected_output_width],
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 8192,
                queue_age_micros: 7,
                latency_micros: 50,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            };
            build_neuron_feature_receipt_v1(request, runtime_tuple, observation)
                .map_err(|_| NeuronModelError::Rejected)
        }
    }

    fn bound(request: &NeuronModelRequestV1) -> AmcnFencedModelBindingV1 {
        AmcnFencedModelBindingV1 {
            scope: checked(StableId::new("amcn:test-owner-scope")),
            request_id: request.request_id.clone(),
            config_id: request.config_id.clone(),
            generation: request.generation,
            model_id: request.model_id.clone(),
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            weights_digest: request.weights_digest,
            input_digest: request.input_digest,
            expected_output_width: request.expected_output_width,
            artifact_manifest_digest: Digest32::of_bytes(b"actual-param-lineage"),
            source_frontier_digest: Digest32::of_bytes(b"authoritative-source-cut"),
            withdrawal_registry_head_digest: Digest32::of_bytes(b"withdrawal-head"),
            quarantine_journal_head_digest: Digest32::of_bytes(b"monotonic-quarantine-head"),
            runtime_anchor_digest: Digest32::of_bytes(b"independent-runtime-anchor"),
        }
    }

    #[test]
    fn amcn_shadow_fence_runtime_pending_witness_reconciles_only_after_new_source_lease() {
        let fixture = Fixture::new();
        let native = native_config();
        let config = runtime_config(&native);
        let witness = MemoryWitness::default();
        let lease = Arc::new(Mutex::new(true));
        let cas_checks = Arc::new(AtomicUsize::new(0));
        let owned_witness = FencedWitness {
            original: witness.clone(),
            source_lease: Arc::clone(&lease),
            cas_checks: Arc::clone(&cas_checks),
        };
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(), native, scope(), 16, config.clone(), owned_witness,
        ));
        let request_input = input(1, Digest32::ZERO);
        let original_request = checked(runtime.model_request(&request_input));
        let binding = bound(&original_request);
        let calls = Arc::new(AtomicUsize::new(0));
        let checks = Arc::new(AtomicUsize::new(0));
        let mut fence = LiveSourceGate {
            source_lease: Arc::clone(&lease),
            checks: Arc::clone(&checks),
        };
        let mut control = OwnerControl {
            config, calls: Arc::clone(&calls),
            source_lease: Arc::clone(&lease),
        };

        // Model execution and journal commit really succeed; the separately
        // held witness fails after commit and leaves a cached pending receipt.
        witness.fail_next_compare_and_swap();
        let first = runtime.tick_amcn_fenced(
            &mut fence, &mut control, &binding, request_input.clone(),
        );
        assert!(matches!(first, Err(NeuronRuntimeError::WitnessAfterCommit { .. })));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(checked(witness.current()), None);

        // Revoke the original source between model execution and retry.
        *checked(lease.lock()) = false;
        let blocked = runtime.tick_amcn_fenced(
            &mut fence, &mut control, &binding, request_input.clone(),
        );
        assert_eq!(
            blocked, Err(NeuronRuntimeError::Model(NeuronModelError::Rejected)),
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(checked(witness.current()), None);
        assert_eq!(checks.load(Ordering::SeqCst), 2);

        // Fixture-only restoration of its valid source lease lets the pending
        // witness reconcile WITHOUT re-running the model or reusing an
        // unchecked cached output. Real owner tombstones must remain monotonic.
        *checked(lease.lock()) = true;
        let reconciled = checked(runtime.tick_amcn_fenced(
            &mut fence, &mut control, &binding, request_input,
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let anchor = checked(witness.current()).expect("witness reconciled");
        assert_eq!(anchor.checkpoint_digest, reconciled.tick.checkpoint_after);
        assert_eq!(checks.load(Ordering::SeqCst), 3);
        assert_eq!(cas_checks.load(Ordering::SeqCst), 2);
        assert!(!reconciled.signal.authority.grants_any());
    }

    #[test]
    fn amcn_shadow_fence_runtime_rejects_stale_binding_before_journal_or_model() {
        let fixture = Fixture::new();
        let native = native_config();
        let config = runtime_config(&native);
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(), native, scope(), 16, config.clone(),
            MemoryWitness::default(),
        ));
        let request_input = input(1, Digest32::ZERO);
        let request = checked(runtime.model_request(&request_input));
        let mut bad_binding = bound(&request);
        bad_binding.head_digest = Digest32::of_bytes(b"replaced-head");
        let calls = Arc::new(AtomicUsize::new(0));
        let checks = Arc::new(AtomicUsize::new(0));
        let source_lease = Arc::new(Mutex::new(true));
        let mut fence = LiveSourceGate {
            source_lease: Arc::clone(&source_lease),
            checks: Arc::clone(&checks),
        };
        let mut control = OwnerControl {
            config, calls: Arc::clone(&calls), source_lease,
        };
        assert_eq!(
            runtime.tick_amcn_fenced(
                &mut fence, &mut control, &bad_binding, request_input,
            ),
            Err(NeuronRuntimeError::Model(NeuronModelError::Rejected)),
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert_eq!(checks.load(Ordering::SeqCst), 0);
        assert_eq!(checked(runtime.current_anchor()), None);
    }

    // A genuinely disk-backed, independently locked Witness (not MemoryWitness)
    // verifies the same source lease is still held during its durable CAS.
    struct DiskFencedWitness {
        witness: crate::FileAnchorWitnessStore,
        source_lease: Arc<Mutex<bool>>,
        cas_checks: Arc<AtomicUsize>,
    }

    impl AnchorWitnessStore for DiskFencedWitness {
        fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
            self.witness.current()
        }

        fn compare_and_swap(
            &mut self,
            expected: Option<JournalAnchor>,
            next: JournalAnchor,
        ) -> Result<(), WitnessStoreError> {
            assert!(
                matches!(self.source_lease.try_lock(), Err(TryLockError::WouldBlock)),
                "source lease must remain held during the durable Witness CAS"
            );
            self.cas_checks.fetch_add(1, Ordering::SeqCst);
            self.witness.compare_and_swap(expected, next)
        }
    }

    #[test]
    fn amcn_shadow_fence_disk_witness_restart_refuses_revoked_old_head() {
        let fixture = Fixture::new();
        let native = native_config();
        let config = runtime_config(&native);
        let source_lease = Arc::new(Mutex::new(true));
        let calls = Arc::new(AtomicUsize::new(0));
        let checks = Arc::new(AtomicUsize::new(0));
        let cas_checks = Arc::new(AtomicUsize::new(0));
        let scope_identity = scope();
        let witnessed_generation = config.generation;

        let committed_anchor = {
            // Real append-only disk Witness and the real runtime Journal start
            // at independent physical files. Both are fsynced by their owners.
            let witness = checked(crate::FileAnchorWitnessStore::open(
                fixture.named_file("amcn-durable-witness"),
                scope_identity,
                witnessed_generation,
                16,
            ));
            let disk_witness = DiskFencedWitness {
                witness,
                source_lease: Arc::clone(&source_lease),
                cas_checks: Arc::clone(&cas_checks),
            };
            let mut runtime = checked(NeuronRuntime::bootstrap(
                fixture.file(),
                native.clone(),
                scope_identity,
                16,
                config.clone(),
                disk_witness,
            ));
            let first_input = input(1, Digest32::ZERO);
            let request = checked(runtime.model_request(&first_input));
            let binding = bound(&request);
            let mut gate = LiveSourceGate {
                source_lease: Arc::clone(&source_lease),
                checks: Arc::clone(&checks),
            };
            let mut control = OwnerControl {
                config: config.clone(),
                calls: Arc::clone(&calls),
                source_lease: Arc::clone(&source_lease),
            };
            let committed = checked(runtime.tick_amcn_fenced(
                &mut gate,
                &mut control,
                &binding,
                first_input,
            ));
            assert_eq!(calls.load(Ordering::SeqCst), 1);
            assert_eq!(cas_checks.load(Ordering::SeqCst), 1);
            let anchor = checked(runtime.current_anchor())
                .expect("disk Journal has a committed anchor");
            assert_eq!(anchor.checkpoint_digest, committed.tick.checkpoint_after);
            anchor
        };
        // The ephemeral runtime and disk Witness owners are now CLOSED.
        // Reopening at a newer generation against old Witness bytes must not
        // silently reinitialize an old acknowledged source/model history.
        assert_eq!(
            crate::FileAnchorWitnessStore::open(
                fixture.named_file("amcn-durable-witness"),
                scope_identity,
                checked(Generation::new(2)),
                16,
            ).err(),
            Some(WitnessStoreError::ContextMismatch)
        );
        let reopened = checked(crate::FileAnchorWitnessStore::open(
            fixture.named_file("amcn-durable-witness"),
            scope_identity,
            witnessed_generation,
            16,
        ));
        assert_eq!(checked(reopened.current()), Some(committed_anchor));
        let disk_witness = DiskFencedWitness {
            witness: reopened,
            source_lease: Arc::clone(&source_lease),
            cas_checks: Arc::clone(&cas_checks),
        };
        let mut runtime = checked(NeuronRuntime::recover(
            fixture.file(),
            native,
            scope_identity,
            16,
            config.clone(),
            committed_anchor,
            disk_witness,
        ));
        let second_input = input(2, committed_anchor.checkpoint_digest);
        let second_request = checked(runtime.model_request(&second_input));
        let bound = bound(&second_request);
        let mut gate = LiveSourceGate {
            source_lease: Arc::clone(&source_lease),
            checks: Arc::clone(&checks),
        };
        let mut control = OwnerControl {
            config,
            calls: Arc::clone(&calls),
            source_lease: Arc::clone(&source_lease),
        };
        // The source owner would have persisted a monotonic quarantine before
        // allowing a readmission. This negative test never claims that a bool
        // itself is a durable tombstone; it deliberately stays false.
        *checked(source_lease.lock()) = false;
        assert_eq!(
            runtime.tick_amcn_fenced(&mut gate, &mut control, &bound, second_input),
            Err(NeuronRuntimeError::Model(NeuronModelError::Rejected))
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(cas_checks.load(Ordering::SeqCst), 1);
        assert_eq!(checked(runtime.current_anchor()), Some(committed_anchor));
        assert_eq!(checks.load(Ordering::SeqCst), 2);
    }

}
