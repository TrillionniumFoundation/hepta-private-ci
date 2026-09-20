use super::*;

use codex_hepta_types::Digest32;

use crate::NeuronCalibrationProfileV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronTickReceiptV1;
use crate::SparseConfig;
use crate::SparseTick;
use crate::sparse_tick;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

fn generation(value: u64) -> Generation {
    checked(Generation::new(value))
}

fn native_config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: generation(1),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
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
        config_id: id("neuron.config.protocol"),
        generation: native.generation,
        model_id: id("model.protocol"),
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
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 512 * 1024,
            checkpoint_bytes: 1024 * 1024,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn committed() -> (NeuronRuntimeConfigV1, SparseCheckpoint, NeuronTickReceiptV1) {
    let native = native_config();
    let config = runtime_config(&native);
    let input = SparseTick {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(b"input"),
        sequence: 1,
        monotonic_micros: 10,
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let (checkpoint, receipt) = checked(sparse_tick(&native, &input, None));
    let active_indices = receipt
        .activation_q24
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| checked(u32::try_from(index)))
        .collect();
    let tick = NeuronTickReceiptV1 {
        tick_id: id("tick.protocol.1"),
        checkpoint_before: receipt.checkpoint_before,
        checkpoint_after: receipt.checkpoint_after,
        activation_digest: checkpoint.activation_digest(),
        active_indices,
        sparsity_ppm: receipt.active_fraction_ppm,
        threshold_digest: checkpoint.threshold_digest(),
        eligibility_digest: checkpoint.eligibility_digest(),
        prediction_error_q24: receipt.prediction_error_q24,
        confidence_ppm: 900_000,
        ood_ppm: 100_000,
        abstain: false,
        resource_receipt: NeuronResourceReceiptV1 {
            execution_micros: 100,
            transient_allocation_bytes: 4096,
            checkpoint_bytes: checked(u64::try_from(checkpoint.bounded_encoded_bytes())),
            journal_bytes_written: 384,
            write_amplification_ppm: 1_000_000,
            saturation_count: receipt.projection_count,
            queue_age_micros: 7,
        },
    };
    (config, checkpoint, tick)
}

#[test]
fn canonical_signal_roundtrip_rejects_unknown_fields() {
    let signal = NeuronSignalReceiptV1 {
        signal_set_id: id("signal.protocol.1"),
        model_runtime_digest: Digest32::of_bytes(b"runtime"),
        temporal_state_digest: Digest32::of_bytes(b"temporal"),
        signals_q24: vec![Q, 0, -Q],
        activation_sparsity_ppm: 333_333,
        ood_ppm: 50_000,
        abstain: false,
        authority: AuthorityPosture::DENY_ALL,
    };
    let bytes = checked(encode_neuron_signal_receipt_v1(&signal));
    assert_eq!(checked(decode_neuron_signal_receipt_v1(&bytes)), signal);

    let mut json: serde_json::Value = checked(serde_json::from_slice(&bytes));
    let object = match json.as_object_mut() {
        Some(value) => value,
        None => panic!("signal DTO must be an object"),
    };
    object.insert("unknownCritical".to_owned(), serde_json::Value::Bool(true));
    let changed = checked(serde_json::to_vec(&json));
    assert_eq!(
        decode_neuron_signal_receipt_v1(&changed).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn checkpoint_is_derived_from_committed_state_and_roundtrips() {
    let (config, checkpoint, tick) = committed();
    let value = checked(canonical_checkpoint_v1(
        &config,
        &checkpoint,
        &tick,
        1_900_000_000_000,
    ));
    assert_eq!(value.logical_sequence, 1);
    assert_eq!(value.predecessor_id, None);
    assert_eq!(
        value.temporal_state_digest,
        checkpoint.temporal_state_digest()
    );
    assert_ne!(value.temporal_state_digest, checkpoint.digest());
    let bytes = checked(encode_neuron_checkpoint_v1(&value));
    assert_eq!(checked(decode_neuron_checkpoint_v1(&bytes)), value);

    let mut json: serde_json::Value = checked(serde_json::from_slice(&bytes));
    let object = match json.as_object_mut() {
        Some(value) => value,
        None => panic!("checkpoint DTO must be an object"),
    };
    object.insert("unexpected".to_owned(), serde_json::Value::Bool(true));
    let changed = checked(serde_json::to_vec(&json));
    assert_eq!(
        decode_neuron_checkpoint_v1(&changed).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn checkpoint_publication_rejects_forged_owner_summary() {
    let (config, checkpoint, mut tick) = committed();
    tick.eligibility_digest = Digest32::of_bytes(b"forged");
    assert_eq!(
        canonical_checkpoint_v1(&config, &checkpoint, &tick, 1_900_000_000_000).err(),
        Some(NeuronProtocolError::BindingMismatch(
            "checkpoint summaries"
        ))
    );
}


#[test]
fn canonical_tick_input_roundtrip_rejects_unknown_fields() {
    let value = crate::NeuronTickInputV1 {
        tick_id: id("tick.input.protocol.1"),
        subject_id: id("subject.protocol.1"),
        logical_sequence: 1,
        monotonic_time_micros: 42,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: crate::canonical_feature_vector_digest_v1(&[Q, 0, -Q]),
        feature_vector_q24: vec![Q, 0, -Q],
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: Some(7),
        modulator_digest: Some(Digest32::of_bytes(b"modulator")),
    };
    let bytes = checked(encode_neuron_tick_input_v1(&value));
    assert_eq!(checked(decode_neuron_tick_input_v1(&bytes)), value);

    let mut json: serde_json::Value = checked(serde_json::from_slice(&bytes));
    let object = match json.as_object_mut() {
        Some(value) => value,
        None => panic!("tick input DTO must be an object"),
    };
    object.insert("unknownCritical".to_owned(), serde_json::Value::Bool(true));
    let changed = checked(serde_json::to_vec(&json));
    assert_eq!(
        decode_neuron_tick_input_v1(&changed).err(),
        Some(NeuronProtocolError::Json)
    );
}

#[test]
fn canonical_tick_receipt_projects_only_registered_resource_fields() {
    let (_, _, tick) = committed();
    let wire = checked(canonical_tick_receipt_v1(&tick));
    assert_eq!(
        wire.execution_micros,
        tick.resource_receipt.execution_micros
    );
    let bytes = checked(encode_neuron_tick_receipt_v1(&wire));
    let text = match std::str::from_utf8(&bytes) {
        Ok(value) => value,
        Err(error) => panic!("canonical JSON must be UTF-8: {error:?}"),
    };
    assert!(!text.contains("journalBytesWritten"));
    assert!(!text.contains("writeAmplificationPpm"));
    assert_eq!(checked(decode_neuron_tick_receipt_v1(&bytes)), wire);

    let mut json: serde_json::Value = checked(serde_json::from_slice(&bytes));
    let resource = match json
        .get_mut("resourceReceipt")
        .and_then(serde_json::Value::as_object_mut)
    {
        Some(value) => value,
        None => panic!("resourceReceipt must be an object"),
    };
    resource.insert("writeAmplificationPpm".to_owned(), serde_json::json!(1));
    let changed = checked(serde_json::to_vec(&json));
    assert_eq!(
        decode_neuron_tick_receipt_v1(&changed).err(),
        Some(NeuronProtocolError::Json)
    );
}
