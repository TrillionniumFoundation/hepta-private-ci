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
        witness.clone(),
    ));
    assert_eq!(checked(recovered.current_anchor()), Some(first_anchor));
    let second = checked(recovered.tick(
        &mut model,
        input(2, first_anchor.checkpoint_digest),
    ));
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
    let second = checked(runtime.tick(
        &mut model,
        input(2, first_anchor.checkpoint_digest),
    ));
    assert!(second.tick.abstain);
    assert_eq!(second.tick.confidence_ppm, 0);
    assert_eq!(second.tick.ood_ppm, 1_000_000);
    assert_eq!(
        checked(runtime.current_anchor()).expect("second anchor").sequence,
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
        let second = checked(runtime.tick(
            &mut model,
            input(2, first.tick.checkpoint_after),
        ));
        checked(runtime.rollover(
            fixture.named_file("successor"),
            /*max_records*/ 2,
        ));
        let third = checked(runtime.tick(
            &mut model,
            input(3, second.tick.checkpoint_after),
        ));
        let fourth = checked(runtime.tick(
            &mut model,
            input(4, third.tick.checkpoint_after),
        ));
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
        checked(recovered.current_anchor()).expect("root end").sequence,
        2
    );
    checked(recovered.recover_next_segment(
        fixture.named_file("successor"),
        /*max_records*/ 2,
    ));
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
