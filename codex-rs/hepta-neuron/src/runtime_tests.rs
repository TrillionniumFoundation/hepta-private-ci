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
    fail_after_commit: Arc<AtomicBool>,
    delay_micros: Arc<AtomicU64>,
    config_digest: Option<Digest32>,
    context: Option<(JournalScope, Generation)>,
}

impl MemoryWitness {
    fn for_config(config: &NeuronRuntimeConfigV1) -> Self {
        Self {
            config_digest: Some(checked(config.semantic_digest())),
            context: Some((scope(), config.generation)),
            ..Self::default()
        }
    }

    fn fail_next_compare_and_swap(&self) {
        self.fail_next.store(true, Ordering::SeqCst);
    }
}

impl AnchorWitnessStore for MemoryWitness {
    fn verify_context(
        &self,
        scope: JournalScope,
        generation: Generation,
    ) -> Result<(), WitnessStoreError> {
        match self.context {
            Some(context) if context == (scope, generation) => Ok(()),
            Some(_) => Err(WitnessStoreError::ContextMismatch),
            None => Err(WitnessStoreError::UnboundRuntimeConfig),
        }
    }

    fn runtime_config_digest(&self) -> Result<Digest32, WitnessStoreError> {
        self.config_digest
            .ok_or(WitnessStoreError::UnboundRuntimeConfig)
    }

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
        std::thread::sleep(std::time::Duration::from_micros(
            self.delay_micros.load(Ordering::SeqCst),
        ));
        if self.fail_after_commit.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Indeterminate);
        }
        Ok(())
    }
}

struct FakeModel {
    calls: usize,
    corrupt_head: bool,
    latency_micros: u64,
}

impl FakeModel {
    fn new() -> Self {
        Self {
            calls: 0,
            corrupt_head: false,
            latency_micros: 50,
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
            latency_micros: self.latency_micros,
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
    let witness = MemoryWitness::for_config(&config);
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
    let witness = MemoryWitness::for_config(&config);
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
    let pending_tick = runtime
        .pending
        .as_ref()
        .expect("pending output")
        .output
        .tick
        .clone();
    assert_eq!(
        runtime.current_eligibility_sample(),
        Err(NeuronRuntimeError::PendingReconciliation)
    );
    assert_eq!(
        runtime.canonical_checkpoint(&pending_tick, 1_900_000_000_000),
        Err(crate::NeuronProtocolError::BindingMismatch(
            "acknowledgement witness"
        ))
    );
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
        config.clone(),
        MemoryWitness::for_config(&config),
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
        config.clone(),
        MemoryWitness::for_config(&config),
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
    let witness = MemoryWitness::for_config(&config);
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
    let witness = MemoryWitness::for_config(&config);
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
        old_config.clone(),
        MemoryWitness::for_config(&old_config),
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
        successor_config.clone(),
        MemoryWitness::for_config(&successor_config),
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

#[test]
fn chain_recovery_blocks_intermediate_publication_and_reconciles_committed_tail() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::for_config(&config);
    let mut model = FakeModel::new();
    let (second, fourth_anchor) = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 2,
            config.clone(),
            witness.clone(),
        ));
        let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
        let second = checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
        checked(runtime.rollover(fixture.named_file("successor"), /*max_records*/ 2));
        let third = checked(runtime.tick(&mut model, input(3, second.tick.checkpoint_after)));
        witness.fail_next_compare_and_swap();
        assert!(matches!(
            runtime.tick(&mut model, input(4, third.tick.checkpoint_after)),
            Err(NeuronRuntimeError::WitnessAfterCommit { .. })
        ));
        (
            second,
            checked(runtime.current_anchor()).expect("committed fourth anchor"),
        )
    };
    let mut recovered = checked(NeuronRuntime::recover_chain_root(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 2,
        config,
        witness.clone(),
    ));
    let before_calls = model.calls;
    assert_eq!(
        recovered.tick(&mut model, input(3, second.tick.checkpoint_after)),
        Err(NeuronRuntimeError::RecoveryWitnessMismatch)
    );
    assert_eq!(model.calls, before_calls);
    assert_eq!(
        recovered.rollover(fixture.named_file("unexpected"), /*max_records*/ 2),
        Err(NeuronRuntimeError::RecoveryWitnessMismatch)
    );
    assert_eq!(
        recovered.current_eligibility_sample(),
        Err(NeuronRuntimeError::RecoveryWitnessMismatch)
    );
    assert_eq!(
        recovered.canonical_checkpoint(&second.tick, 1_900_000_000_000),
        Err(crate::NeuronProtocolError::BindingMismatch(
            "acknowledgement witness"
        ))
    );
    checked(recovered.recover_next_segment(fixture.named_file("successor"), /*max_records*/ 2));
    assert_eq!(checked(recovered.current_anchor()), Some(fourth_anchor));
    assert_eq!(checked(witness.current()), Some(fourth_anchor));
    checked(recovered.rollover(fixture.named_file("next"), /*max_records*/ 2));
    checked(recovered.tick(&mut model, input(5, fourth_anchor.checkpoint_digest)));
}

#[test]
fn acknowledged_but_indeterminate_witness_retry_does_not_repeat_model_or_cas() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::for_config(&config);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let tick = input(1, Digest32::ZERO);
    witness.fail_after_commit.store(true, Ordering::SeqCst);
    assert!(matches!(
        runtime.tick(&mut model, tick.clone()),
        Err(NeuronRuntimeError::WitnessAfterCommit {
            error: WitnessStoreError::Indeterminate,
            ..
        })
    ));
    let acknowledged = checked(witness.current()).expect("durable acknowledgement");
    let output = checked(runtime.tick(&mut model, tick));
    assert_eq!(model.calls, 1);
    assert_eq!(output.tick.checkpoint_after, acknowledged.checkpoint_digest);
}

#[test]
fn invalid_runtime_context_rejects_before_model_execution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 8,
        config.clone(),
        MemoryWitness::for_config(&config),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let valid = input(2, first.tick.checkpoint_after);
    let mut skipped = valid.clone();
    skipped.logical_sequence = 3;
    let mut old_clock = valid.clone();
    old_clock.monotonic_time_micros = 1000;
    let mut other_subject = valid.clone();
    other_subject.subject_id = checked(StableId::new("subject.other"));
    let mut other_objective = valid.clone();
    other_objective.objective_digest = Digest32::of_bytes(b"other objective");
    let mut other_body = valid;
    other_body.body_generation = Some(2);
    for (tick, error) in [
        (
            skipped,
            JournalError::Mechanism(crate::SparseError::Sequence),
        ),
        (
            old_clock,
            JournalError::Mechanism(crate::SparseError::Clock),
        ),
        (other_subject, JournalError::ContextMismatch),
        (other_objective, JournalError::ContextMismatch),
        (
            other_body,
            JournalError::Mechanism(crate::SparseError::ScopeDrift),
        ),
    ] {
        assert_eq!(
            runtime.tick(&mut model, tick),
            Err(NeuronRuntimeError::Journal(error))
        );
        assert_eq!(model.calls, 1);
    }
}

#[test]
fn resource_latency_covers_witness_acknowledgement_and_reported_model_execution() {
    let fixture = Fixture::new();
    let native = native_config();
    let mut config = runtime_config(&native);
    config.resource_envelope.p95_latency_micros = 1000;
    config.resource_envelope.p99_latency_micros = 2000;
    let witness = MemoryWitness::for_config(&config);
    witness.delay_micros.store(20_000, Ordering::SeqCst);
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
    assert!(first.tick.resource_receipt.execution_micros >= 20_000);
    assert!(first.tick.abstain && first.signal.abstain);
    model.latency_micros = 1_000_000;
    let second = checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
    assert!(second.tick.resource_receipt.execution_micros >= 1_000_000);
    assert!(second.tick.abstain && second.signal.abstain);
}

struct ExhaustedWitness(Digest32, JournalScope, Generation);

impl AnchorWitnessStore for ExhaustedWitness {
    fn verify_context(
        &self,
        scope: JournalScope,
        generation: Generation,
    ) -> Result<(), WitnessStoreError> {
        if (self.1, self.2) != (scope, generation) {
            return Err(WitnessStoreError::ContextMismatch);
        }
        Ok(())
    }

    fn runtime_config_digest(&self) -> Result<Digest32, WitnessStoreError> {
        Ok(self.0)
    }

    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn check_capacity(&self) -> Result<(), WitnessStoreError> {
        Err(WitnessStoreError::Capacity)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        panic!("known exhausted witness must reject before journal mutation")
    }
}

#[test]
fn known_witness_exhaustion_rejects_before_inference_or_journal_mutation() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config.clone(),
        ExhaustedWitness(
            checked(config.semantic_digest()),
            scope(),
            config.generation,
        ),
    ));
    let mut model = FakeModel::new();
    assert_eq!(
        runtime.tick(&mut model, input(1, Digest32::ZERO)),
        Err(NeuronRuntimeError::Witness(WitnessStoreError::Capacity))
    );
    assert_eq!(model.calls, 0);
    assert_eq!(checked(runtime.current_anchor()), None);
}

#[test]
fn early_owner_rollover_rejects_before_initializing_successor_file() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config.clone(),
        MemoryWitness::for_config(&config),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(
        runtime.rollover(fixture.named_file("early"), /*max_records*/ 4),
        Err(NeuronRuntimeError::SegmentNotFull)
    );
    assert_eq!(checked(fs::metadata(fixture.0.join("early"))).len(), 0);
    assert_eq!(
        checked(runtime.current_anchor()),
        Some(JournalAnchor {
            sequence: 1,
            checkpoint_digest: first.tick.checkpoint_after
        })
    );
    checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
}

#[test]
fn full_owner_journal_rejects_before_reinvoking_model() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 1,
        config.clone(),
        MemoryWitness::for_config(&config),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(
        runtime.tick(&mut model, input(2, first.tick.checkpoint_after)),
        Err(NeuronRuntimeError::Journal(JournalError::Capacity))
    );
    assert_eq!(model.calls, 1);
}

#[test]
fn unbound_witness_cannot_initialize_canonical_runtime() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    assert!(matches!(
        NeuronRuntime::bootstrap(
            fixture.file(),
            native,
            scope(),
            /*max_records*/ 4,
            config,
            MemoryWitness::default(),
        ),
        Err(NeuronRuntimeError::Witness(
            WitnessStoreError::UnboundRuntimeConfig
        ))
    ));
    assert_eq!(checked(fs::metadata(fixture.0.join("journal"))).len(), 0);
}

#[test]
fn full_runtime_configuration_drift_rejects_before_recovery_tail_repair() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::for_config(&config);
    let anchor = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 4,
            config.clone(),
            witness.clone(),
        ));
        checked(runtime.tick(&mut FakeModel::new(), input(1, Digest32::ZERO)));
        checked(runtime.current_anchor()).expect("acknowledged anchor")
    };
    let path = fixture.0.join("journal");
    let mut bytes = checked(fs::read(&path));
    bytes.extend_from_slice(b"partial frame");
    checked(fs::write(&path, &bytes));
    let mut other_encoder = config.clone();
    other_encoder.encoder_digest = Digest32::of_bytes(b"different encoder");
    let mut other_weights = config.clone();
    other_weights.weights_digest = Digest32::of_bytes(b"different weights");
    let mut other_calibration = config.clone();
    other_calibration.calibration.maximum_ood_ppm += 1;
    let mut other_resources = config;
    other_resources.resource_envelope.p99_latency_micros += 1;
    for changed in [
        other_encoder,
        other_weights,
        other_calibration,
        other_resources,
    ] {
        assert!(matches!(
            NeuronRuntime::recover(
                fixture.file(),
                native.clone(),
                scope(),
                /*max_records*/ 4,
                changed,
                anchor,
                witness.clone(),
            ),
            Err(NeuronRuntimeError::RecoveryWitnessMismatch)
        ));
        assert_eq!(checked(fs::read(&path)), bytes);
        assert_eq!(checked(witness.current()), Some(anchor));
    }
}

#[test]
fn canonical_runtime_roundtrips_with_durable_configuration_bound_witness() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let config_digest = checked(config.semantic_digest());
    let witness = checked(crate::FileAnchorWitnessStore::open_bound(
        fixture.named_file("witness"),
        scope(),
        native.generation,
        /*max_records*/ 4,
        config_digest,
    ));
    let anchor = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(),
            native.clone(),
            scope(),
            /*max_records*/ 4,
            config.clone(),
            witness,
        ));
        let first = checked(runtime.tick(&mut FakeModel::new(), input(1, Digest32::ZERO)));
        checked(runtime.canonical_checkpoint(&first.tick, 1_900_000_000_000));
        checked(runtime.current_anchor()).expect("first durable anchor")
    };
    let witness = checked(crate::FileAnchorWitnessStore::open_bound(
        fixture.named_file("witness"),
        scope(),
        native.generation,
        /*max_records*/ 4,
        config_digest,
    ));
    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        anchor,
        witness,
    ));
    let second = checked(recovered.tick(&mut FakeModel::new(), input(2, anchor.checkpoint_digest)));
    assert_eq!(second.tick.checkpoint_before, anchor.checkpoint_digest);
    checked(recovered.canonical_checkpoint(&second.tick, 1_900_000_000_000));
}

#[test]
fn canonical_bootstrap_rejects_witness_context_mismatch_before_journal_initialization() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut other_scope = scope();
    other_scope.scope_digest = Digest32::of_bytes(b"other subject scope");
    let mut other_objective = scope();
    other_objective.objective_digest = Digest32::of_bytes(b"other objective scope");
    for (name, enrolled_scope, enrolled_generation) in [
        ("wrong-subject", other_scope, config.generation),
        ("wrong-objective", other_objective, config.generation),
        ("wrong-generation", scope(), checked(Generation::new(2))),
    ] {
        let witness = checked(crate::FileAnchorWitnessStore::open_bound(
            fixture.named_file(name),
            enrolled_scope,
            enrolled_generation,
            /*max_records*/ 4,
            checked(config.semantic_digest()),
        ));
        assert!(matches!(
            NeuronRuntime::bootstrap(
                fixture.file(),
                native.clone(),
                scope(),
                /*max_records*/ 4,
                config.clone(),
                witness,
            ),
            Err(NeuronRuntimeError::Witness(
                WitnessStoreError::ContextMismatch
            ))
        ));
        assert_eq!(checked(fs::metadata(fixture.0.join("journal"))).len(), 0);
    }
}
