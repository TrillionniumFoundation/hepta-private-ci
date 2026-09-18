use super::*;
use crate::inhibition_digest;
use crate::q24_feature_digest;
use std::fmt;

const Q: i64 = 1 << 24;

fn checked<T, E: fmt::Debug>(result: Result<T, E>, context: &str) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("{context}: {error:?}"),
    }
}

fn required<T>(value: Option<T>, context: &str) -> T {
    match value {
        Some(value) => value,
        None => panic!("{context}"),
    }
}

fn id(value: &str) -> StableId {
    checked(StableId::new(value), "valid id")
}

fn generation(value: u64) -> Generation {
    checked(Generation::new(value), "valid generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn config() -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("wire.config.1"),
        generation: generation(1),
        encoder_digest: digest("weights"),
        head_digest: digest("head"),
        state_dimensions: NeuronStateDimensionsV1 {
            temporal_state: 5,
            activation: 5,
            modulators: 2,
            inhibition_edges: 0,
        },
        fixed_point_profile: NeuronFixedPointProfileV1 {
            state_scale: FixedPointScaleV1::Q24,
            rounding: FixedPointRoundingV1::NearestTiesEven,
            state_minimum_q24: -8 * Q,
            state_maximum_q24: 8 * Q,
            checked_wide_intermediates: true,
        },
        top_k_policy: NeuronTopKPolicyV1 {
            minimum_ratio_ppm: 200_000,
            maximum_ratio_ppm: 200_000,
            tie_break: TopKTieBreakV1::CanonicalUnitId,
            per_population_first: false,
        },
        inhibition_digest: inhibition_digest(&[]),
        homeostasis_profile: NeuronHomeostasisProfileV1 {
            moving_average_alpha_q24: Q / 2,
            threshold_step_q24: Q / 8,
            threshold_minimum_q24: -Q,
            threshold_maximum_q24: Q,
            saturation_limit: 64,
        },
        eligibility_profile: NeuronEligibilityProfileV1 {
            trace_dimension: 5,
            maximum_norm_q24: 4 * Q,
            decay_q24: Q / 2,
            local_rule_digest: digest("local-rule"),
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 512 * 1024,
            checkpoint_bytes: 1024 * 1024,
            write_amplification_ppm: 4_000_000,
        },
        expires_at_unix_micros: 4_102_444_800_000_000,
    }
}

fn input() -> NeuronTickInputV1 {
    let features = vec![Q / 2, Q / 4, 0, 0, 0];
    NeuronTickInputV1 {
        tick_id: id("tick.1"),
        subject_id: id("subject.1"),
        logical_sequence: 1,
        monotonic_time_micros: 1_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: q24_feature_digest(&features),
        feature_vector_q24: features,
        objective_digest: digest("objective"),
        ndu_snapshot_digest: digest("ndu"),
        body_generation: Some(generation(1)),
        modulator_digest: Some(digest("modulator")),
    }
}

fn tick_receipt() -> NeuronTickReceiptV1 {
    NeuronTickReceiptV1 {
        tick_id: id("tick.1"),
        checkpoint_before: Digest32::ZERO,
        checkpoint_after: digest("after"),
        activation_digest: digest("activation"),
        active_indices: vec![0, 3],
        sparsity_ppm: 200_000,
        threshold_digest: digest("threshold"),
        eligibility_digest: digest("eligibility"),
        prediction_error_q24: Q,
        confidence_ppm: 900_000,
        ood_ppm: 10_000,
        abstain: false,
        resource_receipt: crate::NeuronResourceReceiptV1 {
            execution_micros: 100,
            transient_allocation_bytes: 1024,
            checkpoint_bytes: 4096,
            saturation_count: 0,
            queue_age_micros: 5,
        },
    }
}

fn signal_receipt() -> NeuronSignalReceiptV1 {
    NeuronSignalReceiptV1 {
        signal_set_id: id("signal.1"),
        model_runtime_digest: digest("model-runtime"),
        temporal_state_digest: digest("state"),
        signals_q24: vec![Q, 0, 0, 0, 0],
        activation_sparsity_ppm: 200_000,
        ood_ppm: 10_000,
        abstain: false,
    }
}

fn model_receipt() -> LocalModelRuntimeReceiptV1 {
    LocalModelRuntimeReceiptV1 {
        model_id: id("model.1"),
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_id: id("q4"),
        backend_id: id("backend"),
        device_identity_digest: digest("device"),
        latency_micros: 100,
        resident_bytes: 4096,
    }
}

#[test]
fn config_and_tick_roundtrip_through_compact_sorted_canonical_json() {
    let config = config();
    let config_bytes = checked(encode_neuron_runtime_config_v1(&config), "encode config");
    assert_eq!(
        checked(
            decode_neuron_runtime_config_v1(&config_bytes),
            "decode config",
        ),
        config
    );

    let input = input();
    let input_bytes = checked(encode_neuron_tick_input_v1(&input), "encode input");
    assert_eq!(
        checked(decode_neuron_tick_input_v1(&input_bytes), "decode input"),
        input
    );
}

#[test]
fn decoder_rejects_noncanonical_unknown_and_oversize_vectors() {
    let bytes = checked(encode_neuron_tick_input_v1(&input()), "encode input");
    let mut padded = bytes.clone();
    padded.push(b'\n');
    assert_eq!(
        decode_neuron_tick_input_v1(&padded),
        Err(NeuronWireError::NonCanonical)
    );

    let mut value: Value = checked(serde_json::from_slice(&bytes), "json");
    required(value.as_object_mut(), "object").insert(
        "criticalFutureField".to_string(),
        json!(true),
    );
    let changed = checked(canonical_json(&value), "canonical changed json");
    assert_eq!(
        decode_neuron_tick_input_v1(&changed),
        Err(NeuronWireError::UnknownField(
            "criticalFutureField".to_string()
        ))
    );

    let mut value: Value = checked(serde_json::from_slice(&bytes), "json");
    required(value.as_object_mut(), "object").insert(
        "featureVectorQ24".to_string(),
        json!(vec![0_i64; 513]),
    );
    let changed = checked(canonical_json(&value), "oversize feature vector");
    assert_eq!(
        decode_neuron_tick_input_v1(&changed),
        Err(NeuronWireError::InvalidValue("featureVectorQ24 length"))
    );
}

#[test]
fn produced_receipts_roundtrip_through_strict_consumable_wire_adapters() {
    let tick = tick_receipt();
    let tick_bytes = checked(encode_neuron_tick_receipt_v1(&tick), "encode tick receipt");
    assert_eq!(
        checked(
            decode_neuron_tick_receipt_v1(&tick_bytes),
            "decode tick receipt",
        ),
        tick
    );

    let signal = signal_receipt();
    let signal_bytes = checked(
        encode_neuron_signal_receipt_v1(&signal),
        "encode signal receipt",
    );
    assert_eq!(
        checked(
            decode_neuron_signal_receipt_v1(&signal_bytes),
            "decode signal receipt",
        ),
        signal
    );

    let model = model_receipt();
    let model_bytes = checked(
        encode_local_model_runtime_receipt_v1(&model),
        "encode model receipt",
    );
    assert_eq!(
        checked(
            decode_local_model_runtime_receipt_v1(&model_bytes),
            "decode model receipt",
        ),
        model
    );
}

#[test]
fn receipt_decoder_rejects_nested_unknown_duplicate_indices_and_invalid_ppm() {
    let bytes = checked(
        encode_neuron_tick_receipt_v1(&tick_receipt()),
        "encode tick receipt",
    );
    let mut value: Value = checked(serde_json::from_slice(&bytes), "json");
    let object = required(value.as_object_mut(), "tick object");
    let resources = required(
        required(object.get_mut("resourceReceipt"), "resource receipt").as_object_mut(),
        "resource object",
    );
    resources.insert("criticalFutureField".to_string(), json!(true));
    let changed = checked(canonical_json(&value), "canonical nested unknown");
    assert_eq!(
        decode_neuron_tick_receipt_v1(&changed),
        Err(NeuronWireError::UnknownField(
            "criticalFutureField".to_string()
        ))
    );

    let mut value: Value = checked(serde_json::from_slice(&bytes), "json");
    required(value.as_object_mut(), "tick object").insert(
        "activeIndices".to_string(),
        json!([0, 0]),
    );
    let changed = checked(canonical_json(&value), "duplicate active indices");
    assert_eq!(
        decode_neuron_tick_receipt_v1(&changed),
        Err(NeuronWireError::InvalidValue("activeIndices unique"))
    );

    let mut value: Value = checked(serde_json::from_slice(&bytes), "json");
    required(value.as_object_mut(), "tick object").insert(
        "confidencePpm".to_string(),
        json!(1_000_001_u32),
    );
    let changed = checked(canonical_json(&value), "invalid ppm");
    assert_eq!(
        decode_neuron_tick_receipt_v1(&changed),
        Err(NeuronWireError::InvalidValue("confidencePpm"))
    );
}

#[test]
fn canonical_receipts_are_byte_stable() {
    let receipt = tick_receipt();
    let first = checked(encode_neuron_tick_receipt_v1(&receipt), "first");
    let second = checked(encode_neuron_tick_receipt_v1(&receipt), "second");
    assert_eq!(first, second);
    assert!(!first.ends_with(b"\n"));
}
