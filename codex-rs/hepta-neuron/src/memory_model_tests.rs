use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::FileAnchorWitnessStore;
use crate::JournalScope;
use crate::NeuronCalibrationProfileV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronRuntime;
use crate::NeuronRuntimeError;
use crate::NeuronTickInputV1;
use crate::SparseConfig;
use crate::canonical_feature_vector_digest_v1;

static SERIAL: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("memory model fixture: {error:?}"),
    }
}

fn encoded(d: u16, hidden: u16, bits: u16, weights: &[i16]) -> Vec<u8> {
    let mut bytes = b"HMCELL3\0".to_vec();
    for value in [1, d, hidden, bits] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes.extend_from_slice(&4_096_u32.to_le_bytes());
    bytes.extend_from_slice(&(weights.len() as u32).to_le_bytes());
    for value in weights {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

fn artifact_bytes() -> Vec<u8> {
    encoded(
        2,
        2,
        2,
        &[4_096, 0, 0, 4_096, 0, 0, 4_096, -4_096, 0, 4_096, -2_048, 0],
    )
}

fn configurations(
    artifact: &MemoryCellArtifactV1,
) -> (SparseConfig, NeuronRuntimeConfigV1, Vec<u8>) {
    let generation = checked(Generation::new(1));
    let encoder = Digest32::of_bytes(b"fixture.numeric.encoder");
    let preprocessing = Digest32::of_bytes(b"fixture.numeric.preprocessing");
    let manifest = checked(serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.memory.native-model.v1", "model_id":"memory.fixture",
        "generation":1, "weights_sha256":artifact.digest().to_string(),
        "encoder_sha256":encoder.to_string(), "preprocessor_sha256":preprocessing.to_string(),
        "source_set_sha256":Digest32::of_bytes(b"fixture.source-cut").to_string(),
        "input_dimension":artifact.input_dimension(), "hidden_width":artifact.hidden_width(),
        "output_bits":artifact.output_bits()
    })));
    let native = SparseConfig {
        model_digest: artifact.head_digest(),
        normalization_digest: preprocessing,
        generation,
        width: artifact.output_width(),
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: 0,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("memory.config")),
        generation,
        model_id: checked(StableId::new("memory.fixture")),
        model_manifest_digest: Digest32::of_bytes(&manifest),
        encoder_digest: encoder,
        head_digest: artifact.head_digest(),
        weights_digest: artifact.digest(),
        tokenizer_digest: Digest32::of_bytes(b"fixture.no-tokenizer"),
        preprocessor_digest: preprocessing,
        quantization_digest: Digest32::of_bytes(MEMORY_CELL_Q12_PROFILE_V1),
        runtime_digest: Digest32::of_bytes(b"fixture.runtime"),
        device_digest: Digest32::of_bytes(b"fixture.device"),
        normalization_digest: preprocessing,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: artifact.input_dimension(),
        state_width: native.width,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"fixture.always-abstain"),
            ood_artifact_digest: Digest32::of_bytes(b"fixture.always-abstain"),
            generation,
            // Every integration tick is before this profile's valid window.
            valid_from_sequence: 100,
            expires_after_sequence: 101,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 16 * Q24,
            minimum_confidence_ppm: 1_000_000,
            maximum_ood_ppm: 0,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 256,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 0,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 0,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    (native, config, manifest)
}

#[test]
fn exact_integer_bits_and_negative_half_rounding() {
    let artifact = checked(MemoryCellArtifactV1::from_bytes(&artifact_bytes()));
    assert_eq!(
        checked(artifact.predict_q12(&[4_096, 0])),
        MemoryCellReadoutV1 {
            value: 1,
            logits_q24: vec![8_388_608, -16_777_216],
        }
    );
    assert_eq!(checked(artifact.predict_q12(&[0, 4_096])).value, 2);
    let half = checked(MemoryCellArtifactV1::from_bytes(&encoded(
        1,
        1,
        1,
        &[2_048, 0, 1, 0],
    )));
    assert_eq!(
        checked(half.predict_q12(&[-1])),
        MemoryCellReadoutV1 {
            value: 1,
            logits_q24: vec![0]
        }
    );
    assert_eq!(
        checked(half.predict_q12(&[1])),
        MemoryCellReadoutV1 {
            value: 1,
            logits_q24: vec![1]
        }
    );
}

#[test]
fn malformed_shapes_trailing_payload_and_out_of_range_features_are_rejected() {
    let bytes = artifact_bytes();
    let mut trailing = bytes.clone();
    trailing.push(0);
    let mut inconsistent = bytes.clone();
    inconsistent[20] = 1;
    for payload in [&bytes[..23], trailing.as_slice(), inconsistent.as_slice()] {
        assert!(matches!(
            MemoryCellArtifactV1::from_bytes(payload),
            Err(MemoryCellModelError::InvalidArtifact)
        ));
    }
    let artifact = checked(MemoryCellArtifactV1::from_bytes(&bytes));
    assert_eq!(
        artifact.predict_q12(&[4_097, 0]),
        Err(MemoryCellModelError::InvalidInput)
    );
    assert_eq!(
        artifact.predict_q12(&[0]),
        Err(MemoryCellModelError::InvalidInput)
    );
    let wide = checked(MemoryCellArtifactV1::from_bytes(&encoded(
        1, 1, 32, &[0; 66],
    )));
    assert_eq!(checked(wide.predict_q12(&[0])).value, u32::MAX);
}

#[test]
fn manifest_and_tensor_drift_do_not_bind_to_selected_model() {
    let bytes = artifact_bytes();
    let artifact = checked(MemoryCellArtifactV1::from_bytes(&bytes));
    let (_, config, manifest) = configurations(&artifact);
    let mut changed = bytes.clone();
    changed[24] ^= 1;
    assert!(matches!(
        MemoryCellModelPortV1::from_bytes(&changed, &manifest, &config),
        Err(MemoryCellModelError::BindingMismatch)
    ));
    let mut changed_manifest = manifest;
    changed_manifest.push(b' ');
    assert!(matches!(
        MemoryCellModelPortV1::from_bytes(&bytes, &changed_manifest, &config),
        Err(MemoryCellModelError::BindingMismatch)
    ));
}

struct Files(PathBuf);

impl Files {
    fn new() -> Self {
        let serial = SERIAL.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-memory-native-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&path));
        Self(path)
    }

    fn open(&self, name: &str) -> File {
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

impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn input(sequence: u64, checkpoint: Digest32, x: [i64; 2]) -> NeuronTickInputV1 {
    NeuronTickInputV1 {
        tick_id: checked(StableId::new(format!("memory.tick.{sequence}"))),
        subject_id: checked(StableId::new("memory.subject")),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest: checkpoint,
        input_feature_digest: canonical_feature_vector_digest_v1(&x),
        feature_vector_q24: x.to_vec(),
        objective_digest: Digest32::of_bytes(b"memory.objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"memory.ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn actual_memory_port_commits_and_recovers_with_durable_independent_witness() {
    let files = Files::new();
    let bytes = artifact_bytes();
    let artifact = checked(MemoryCellArtifactV1::from_bytes(&bytes));
    let (native, config, manifest) = configurations(&artifact);
    let scope = JournalScope {
        scope_digest: checked(crate::runtime_types::subject_scope_digest(&checked(
            StableId::new("memory.subject"),
        ))),
        objective_digest: Digest32::of_bytes(b"memory.objective"),
    };
    let mut port = checked(MemoryCellModelPortV1::from_bytes(
        &bytes, &manifest, &config,
    ));
    let witness = checked(FileAnchorWitnessStore::open(
        files.open("witness"),
        scope,
        native.generation,
        /*max_records*/ 8,
    ));
    let mut owner = checked(NeuronRuntime::bootstrap(
        files.open("journal"),
        native.clone(),
        scope,
        /*max_records*/ 8,
        config.clone(),
        witness,
    ));
    let first = checked(owner.tick(&mut port, input(1, Digest32::ZERO, [Q24, 0])));
    assert_eq!(first.model_runtime.weights_digest, artifact.digest());
    assert!(first.tick.abstain);
    assert!(!first.signal.authority.grants_any());
    let anchor = checked(checked(owner.current_anchor()).ok_or("committed model read"));
    drop(owner);
    drop(port);
    let witness = checked(FileAnchorWitnessStore::open(
        files.open("witness"),
        scope,
        native.generation,
        /*max_records*/ 8,
    ));
    let mut owner = checked(NeuronRuntime::recover(
        files.open("journal"),
        native,
        scope,
        /*max_records*/ 8,
        config.clone(),
        anchor,
        witness,
    ));
    let mut port = checked(MemoryCellModelPortV1::from_bytes(
        &bytes, &manifest, &config,
    ));
    let second = checked(owner.tick(&mut port, input(2, anchor.checkpoint_digest, [0, Q24])));
    assert_eq!(second.tick.checkpoint_before, anchor.checkpoint_digest);
    assert_ne!(second.tick.checkpoint_after, anchor.checkpoint_digest);
    assert_eq!(
        checked(checked(owner.current_anchor()).ok_or("second model read")).sequence,
        2
    );
    let mut stale =
        checked(owner.model_request(&input(3, second.tick.checkpoint_after, [Q24, Q24])));
    stale.generation = checked(Generation::new(2));
    assert_eq!(port.execute(&stale), Err(NeuronModelError::Rejected));
    let invalid = input(3, second.tick.checkpoint_after, [2 * Q24, 0]);
    assert_eq!(
        owner.tick(&mut port, invalid),
        Err(NeuronRuntimeError::Model(NeuronModelError::Rejected))
    );
    assert_eq!(
        checked(checked(owner.current_anchor()).ok_or("unchanged anchor")).sequence,
        2
    );
}
