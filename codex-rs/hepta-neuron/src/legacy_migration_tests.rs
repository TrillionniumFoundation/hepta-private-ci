use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::FileAnchorWitnessStore;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronCalibrationProfileV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;
use crate::runtime_types::calibrate;
use crate::runtime_types::digest_model_binding;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-legacy-migration-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(self.0.join(name)),
        )
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

fn generation() -> Generation {
    checked(Generation::new(1))
}

fn native() -> SparseConfig {
    SparseConfig {
        model_digest: digest("head"),
        normalization_digest: digest("normalization"),
        generation: generation(),
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

fn config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("config.1"),
        generation: generation(),
        model_id: id("model.1"),
        model_manifest_digest: digest("manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            generation: generation(),
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 100_000,
            maximum_ood_ppm: 900_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 1,
            maximum_ece_ppm: 2,
            measured_false_acceptance_ppm: 1,
            maximum_false_acceptance_ppm: 2,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000,
            p99_latency_micros: 10_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
    }
}

fn record(native: &SparseConfig, config: &NeuronRuntimeConfigV1) -> NeuronLegacyOperationRecordV1 {
    let input_digest = digest("input");
    let sparse_tick = SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: digest("ndu"),
        body_digest: digest("body"),
        input_digest,
        sequence: 1,
        monotonic_micros: 1_000,
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let (checkpoint, receipt) = checked(crate::sparse_tick(native, &sparse_tick, None));
    let runtime_receipt = LocalModelRuntimeReceiptV1 {
        model_id: config.model_id.clone(),
        model_manifest_digest: config.model_manifest_digest,
        weights_digest: config.weights_digest,
        tokenizer_digest: config.tokenizer_digest,
        preprocessor_digest: config.preprocessor_digest,
        quantization_id: id("q8"),
        quantization_digest: config.quantization_digest,
        backend_id: id("backend"),
        runtime_digest: config.runtime_digest,
        device_identity_digest: config.device_digest,
        latency_micros: 5,
        resident_bytes: 4096,
    };
    let model_output = NeuronModelOutputV1 {
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        output_digest: checked(canonical_model_output_digest_v1(
            &sparse_tick.drive_q24,
            &sparse_tick.prediction_q24,
            &runtime_receipt,
        )),
        drive_q24: sparse_tick.drive_q24.clone(),
        prediction_q24: sparse_tick.prediction_q24.clone(),
        queue_age_micros: 1,
        transient_allocation_bytes: 128,
        runtime_receipt: runtime_receipt.clone(),
    };
    let (confidence_ppm, ood_ppm, calibration_abstain) = checked(calibrate(
        &config.calibration,
        &receipt,
        sparse_tick.sequence,
    ));
    let checkpoint_bytes =
        u64::try_from(checkpoint.bounded_encoded_bytes()).expect("bounded checkpoint bytes");
    let journal_bytes_written =
        u64::try_from(304_usize + 16 * config.state_width).expect("bounded journal bytes");
    let write_amplification_ppm =
        checked(write_amplification(journal_bytes_written, checkpoint_bytes));
    let resource_receipt = NeuronResourceReceiptV1 {
        execution_micros: 10,
        transient_allocation_bytes: model_output.transient_allocation_bytes,
        checkpoint_bytes,
        journal_bytes_written,
        write_amplification_ppm,
        saturation_count: receipt.projection_count,
        queue_age_micros: model_output.queue_age_micros,
    };
    let tick = NeuronTickReceiptV1 {
        tick_id: id("tick.1"),
        checkpoint_before: receipt.checkpoint_before,
        checkpoint_after: receipt.checkpoint_after,
        activation_digest: checkpoint.activation_digest(),
        active_indices: checked(committed_active_indices(&checkpoint)),
        sparsity_ppm: receipt.active_fraction_ppm,
        threshold_digest: checkpoint.threshold_digest(),
        eligibility_digest: checkpoint.eligibility_digest(),
        prediction_error_q24: receipt.prediction_error_q24,
        confidence_ppm,
        ood_ppm,
        abstain: calibration_abstain,
        resource_receipt,
    };
    let signal = NeuronSignalReceiptV1 {
        signal_set_id: tick.tick_id.clone(),
        model_runtime_digest: checked(digest_model_binding(&model_output)),
        temporal_state_digest: checkpoint.temporal_state_digest(),
        signals_q24: receipt.activation_q24,
        activation_sparsity_ppm: tick.sparsity_ppm,
        ood_ppm,
        abstain: tick.abstain,
        authority: AuthorityPosture::DENY_ALL,
    };
    NeuronLegacyOperationRecordV1 {
        input_digest,
        tick_id: tick.tick_id.clone(),
        expected_anchor: None,
        next_anchor: JournalAnchor {
            sequence: 1,
            checkpoint_digest: checkpoint.digest(),
        },
        sparse_tick,
        output: NeuronRuntimeOutputV1 {
            tick,
            signal,
            model_runtime: runtime_receipt,
        },
    }
}

fn trusted_archive_digest(
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
    record: &NeuronLegacyOperationRecordV1,
) -> Digest32 {
    checked(canonical_legacy_operation_archive_digest_v1(
        native,
        scope(),
        config,
        std::slice::from_ref(record),
    ))
}

fn acknowledged_legacy(
    fixture: &Fixture,
) -> (
    SparseConfig,
    NeuronRuntimeConfigV1,
    SparseJournal,
    FileAnchorWitnessStore,
    NeuronLegacyOperationRecordV1,
) {
    let native = native();
    let config = config(&native);
    let record = record(&native, &config);
    let mut journal = checked(SparseJournal::open(
        fixture.file("journal"),
        native.clone(),
        scope(),
        8,
    ));
    let receipt = checked(journal.commit(Digest32::ZERO, &record.sparse_tick));
    assert_eq!(
        receipt.checkpoint_after,
        record.next_anchor.checkpoint_digest
    );
    let mut witness = checked(FileAnchorWitnessStore::open(
        fixture.file("witness"),
        scope(),
        generation(),
        8,
    ));
    checked(witness.compare_and_swap(None, record.next_anchor));
    (native, config, journal, witness, record)
}

include!("legacy_migration_test_cases.rs");
