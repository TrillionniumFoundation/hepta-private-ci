use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("invalid fixture id: {error:?}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("invalid fixture generation: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn config() -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("neuron-config:1"),
        generation: generation(1),
        encoder_digest: digest(b"encoder"),
        head_digest: digest(b"head"),
        state_dimensions: NeuronStateDimensionsV1 {
            temporal_state: 32,
            activation: 32,
            modulators: 4,
            inhibition_edges: 8,
        },
        fixed_point_profile: FixedPointProfileV1 {
            state_scale: FixedPointScaleV1::Q24,
            rounding: FixedPointRoundingV1::NearestTiesEven,
            state_minimum_q24: -Q24_STATE_LIMIT,
            state_maximum_q24: Q24_STATE_LIMIT,
            checked_wide_intermediates: true,
        },
        top_k_policy: TopKPolicyV1 {
            minimum_ratio_ppm: MIN_TOP_K_PPM,
            maximum_ratio_ppm: MAX_TOP_K_PPM,
            tie_break: TopKTieBreakV1::CanonicalUnitId,
            per_population_first: false,
        },
        inhibition_digest: digest(b"inhibition"),
        homeostasis_profile: HomeostasisProfileV1 {
            moving_average_alpha_q24: Q24_ONE / 2,
            threshold_step_q24: Q24_ONE / 8,
            threshold_minimum_q24: -Q24_ONE,
            threshold_maximum_q24: Q24_ONE,
            saturation_limit: 16,
        },
        eligibility_profile: EligibilityProfileV1 {
            trace_dimension: 32,
            maximum_norm_q24: Q24_ELIGIBILITY_LIMIT,
            decay_q24: Q24_ONE / 2,
            local_rule_digest: digest(b"eligibility-rule"),
        },
        expiry: "2026-09-19T00:00:00Z".to_string(),
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 512 * 1024,
            checkpoint_bytes: 1024 * 1024,
            write_amplification_ppm: 4_000_000,
        },
    }
}

#[test]
fn canonical_config_digest_is_stable_and_sensitive() {
    let original = config();
    let first = original
        .semantic_digest()
        .unwrap_or_else(|error| panic!("fixture config rejected: {error:?}"));
    assert_eq!(
        first,
        original
            .semantic_digest()
            .unwrap_or_else(|error| panic!("fixture config rejected: {error:?}"))
    );
    let mut changed = original;
    changed.head_digest = digest(b"different-head");
    assert_ne!(
        first,
        changed
            .semantic_digest()
            .unwrap_or_else(|error| panic!("changed config rejected: {error:?}"))
    );
}

#[test]
fn tick_requires_zero_predecessor_only_at_sequence_one() {
    let mut tick = NeuronTickInputV1 {
        tick_id: id("tick:1"),
        subject_id: id("subject:1"),
        logical_sequence: 1,
        monotonic_time_micros: 10,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: digest(b"features"),
        feature_vector_q24: vec![Q24_ONE; 5],
        objective_digest: digest(b"objective"),
        ndu_snapshot_digest: digest(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    };
    assert!(tick.validate().is_ok());
    tick.logical_sequence = 2;
    assert_eq!(tick.validate(), Err(ProtocolError::InvalidCheckpointBinding));
    tick.checkpoint_digest = digest(b"checkpoint");
    assert!(tick.validate().is_ok());
}

#[test]
fn local_model_receipt_binds_exact_runtime_identity() {
    let mut receipt = LocalModelRuntimeReceiptV1 {
        model_id: id("model:1"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_id: id("q4"),
        backend_id: id("native"),
        device_identity_digest: digest(b"device"),
        latency_micros: 10,
        resident_bytes: 1024,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt
        .calculate_digest()
        .unwrap_or_else(|error| panic!("fixture receipt rejected: {error:?}"));
    assert!(receipt.validate().is_ok());
    receipt.resident_bytes += 1;
    assert_eq!(
        receipt.validate(),
        Err(ProtocolError::DigestMismatch("local model runtime"))
    );
}
