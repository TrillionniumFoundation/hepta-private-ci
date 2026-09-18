use super::*;
use crate::inhibition_digest;
use crate::q24_feature_digest;

const Q: i64 = 1 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
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

#[test]
fn config_and_tick_roundtrip_through_compact_sorted_canonical_json() {
    let config = config();
    let config_bytes = encode_neuron_runtime_config_v1(&config).expect("encode config");
    assert_eq!(
        decode_neuron_runtime_config_v1(&config_bytes).expect("decode config"),
        config
    );

    let input = input();
    let input_bytes = encode_neuron_tick_input_v1(&input).expect("encode input");
    assert_eq!(
        decode_neuron_tick_input_v1(&input_bytes).expect("decode input"),
        input
    );
}

#[test]
fn decoder_rejects_noncanonical_and_unknown_critical_fields() {
    let bytes = encode_neuron_tick_input_v1(&input()).expect("encode input");
    let mut padded = bytes.clone();
    padded.push(b'\n');
    assert_eq!(
        decode_neuron_tick_input_v1(&padded),
        Err(NeuronWireError::NonCanonical)
    );

    let mut value: Value = serde_json::from_slice(&bytes).expect("json");
    value
        .as_object_mut()
        .expect("object")
        .insert("criticalFutureField".to_string(), json!(true));
    let changed = canonical_json(&value).expect("canonical changed json");
    assert_eq!(
        decode_neuron_tick_input_v1(&changed),
        Err(NeuronWireError::UnknownField(
            "criticalFutureField".to_string()
        ))
    );
}

#[test]
fn canonical_receipts_are_byte_stable() {
    let receipt = NeuronTickReceiptV1 {
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
    };
    let first = encode_neuron_tick_receipt_v1(&receipt).expect("first");
    let second = encode_neuron_tick_receipt_v1(&receipt).expect("second");
    assert_eq!(first, second);
    assert!(!first.ends_with(b"\n"));
}
