use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Debug)]
struct FakeModel;

#[derive(Clone, Debug, Eq, PartialEq)]
struct FakeError;

impl std::fmt::Display for FakeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "fake")
    }
}

impl std::error::Error for FakeError {}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error:?}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("fixture generation: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn config(edges: &[InhibitoryEdge]) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("runtime:1"),
        generation: generation(1),
        encoder_digest: digest(b"encoder"),
        head_digest: digest(b"head"),
        state_dimensions: crate::NeuronStateDimensionsV1 {
            temporal_state: 5,
            activation: 5,
            modulators: 4,
            inhibition_edges: u32::try_from(edges.len())
                .unwrap_or_else(|error| panic!("edge count: {error:?}")),
        },
        fixed_point_profile: crate::FixedPointProfileV1 {
            state_scale: crate::FixedPointScaleV1::Q24,
            rounding: crate::FixedPointRoundingV1::NearestTiesEven,
            state_minimum_q24: -Q24_STATE_LIMIT,
            state_maximum_q24: Q24_STATE_LIMIT,
            checked_wide_intermediates: true,
        },
        top_k_policy: crate::TopKPolicyV1 {
            minimum_ratio_ppm: 10_000,
            maximum_ratio_ppm: 200_000,
            tie_break: crate::TopKTieBreakV1::CanonicalUnitId,
            per_population_first: false,
        },
        inhibition_digest: inhibition_digest(edges)
            .unwrap_or_else(|error| panic!("inhibition digest: {error:?}")),
        homeostasis_profile: crate::HomeostasisProfileV1 {
            moving_average_alpha_q24: Q24_ONE / 2,
            threshold_step_q24: Q24_ONE / 8,
            threshold_minimum_q24: -Q24_ONE,
            threshold_maximum_q24: Q24_ONE,
            saturation_limit: 32,
        },
        eligibility_profile: crate::EligibilityProfileV1 {
            trace_dimension: 5,
            maximum_norm_q24: crate::Q24_ELIGIBILITY_LIMIT,
            decay_q24: Q24_ONE / 2,
            local_rule_digest: digest(b"eligibility"),
        },
        resource_envelope: crate::NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 512 * 1024,
            checkpoint_bytes: 1024 * 1024,
            write_amplification_ppm: 4_000_000,
        },
        expiry: "2026-09-19T00:00:00Z".to_string(),
    }
}

fn profile(edges: Vec<InhibitoryEdge>) -> SparseNativeProfileV1 {
    SparseNativeProfileV1 {
        normalization_digest: digest(b"normalization"),
        body_digest: digest(b"body"),
        body_generation: 1,
        temporal_decay_q24: Q24_ONE / 2,
        inhibition_gain_q24: Q24_ONE,
        inhibition: edges,
        target_activity_q24: Q24_ONE / 8,
        selected_top_k: 1,
    }
}

fn input(sequence: u64, predecessor: Digest32) -> NeuronTickInputV1 {
    NeuronTickInputV1 {
        tick_id: id(&format!("tick:{sequence}")),
        subject_id: id("subject:1"),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest: predecessor,
        input_feature_digest: digest(format!("features:{sequence}").as_bytes()),
        feature_vector_q24: vec![Q24_ONE, Q24_ONE / 2, 0, 0, 0],
        objective_digest: digest(b"objective"),
        ndu_snapshot_digest: digest(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

fn model_receipt(config: &NeuronRuntimeConfigV1) -> LocalModelRuntimeReceiptV1 {
    let mut receipt = LocalModelRuntimeReceiptV1 {
        model_id: id("encoder-head:1"),
        weights_digest: config.encoder_digest,
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_id: id("q4"),
        backend_id: id("fixture-backend"),
        device_identity_digest: digest(b"device"),
        latency_micros: 100,
        resident_bytes: 4096,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt
        .calculate_digest()
        .unwrap_or_else(|error| panic!("model receipt: {error:?}"));
    receipt
}

impl FrozenNeuronModel for FakeModel {
    type Error = FakeError;

    fn execute(
        &mut self,
        request: &FrozenModelRequestV1,
    ) -> Result<FrozenModelExecutionV1, Self::Error> {
        let cfg = config(&[]);
        let runtime_receipt = model_receipt(&cfg);
        let request_digest =
            model_request_digest(request).unwrap_or_else(|error| panic!("request digest: {error:?}"));
        let drive_q24 = request.feature_vector_q24.clone();
        let prediction_q24 = vec![0; drive_q24.len()];
        let output_digest = frozen_model_output_digest(
            request_digest,
            runtime_receipt.receipt_digest,
            request.head_digest,
            &drive_q24,
            &prediction_q24,
        )
        .unwrap_or_else(|error| panic!("output digest: {error:?}"));
        Ok(FrozenModelExecutionV1 {
            runtime_receipt,
            head_digest: request.head_digest,
            request_digest,
            output_digest,
            drive_q24,
            prediction_q24,
        })
    }
}

fn calibration(
    config: &NeuronRuntimeConfigV1,
    runtime_digest: Digest32,
) -> NeuronCalibrationArtifactV1 {
    NeuronCalibrationArtifactV1 {
        artifact_digest: digest(b"calibration"),
        runtime_config_digest: config
            .semantic_digest()
            .unwrap_or_else(|error| panic!("config digest: {error:?}")),
        model_runtime_digest: runtime_digest,
        generation: config.generation.get(),
        valid_from_sequence: 1,
        expires_after_sequence: 128,
        maximum_in_domain_error_q24: 2 * Q24_ONE,
        confidence_floor_ppm: 100_000,
        maximum_ood_ppm: 900_000,
    }
}

#[test]
fn canonical_tick_binds_model_calibration_and_sparse_state() {
    let edges = vec![];
    let cfg = config(&edges);
    let native = profile(edges);
    let mut model = FakeModel;
    let runtime_digest = model_receipt(&cfg).receipt_digest;
    let tick = input(1, Digest32::ZERO);
    let pending = prepare_tick(
        &cfg,
        &native,
        &mut model,
        &tick,
        None,
        &calibration(&cfg, runtime_digest),
    )
    .unwrap_or_else(|error| panic!("prepare: {error:?}"));
    assert_eq!(pending.sparse_receipt.checkpoint_before, Digest32::ZERO);
    assert!(!pending.model_runtime_receipt.receipt_digest.is_zero());
    let saturation_count = pending.sparse_receipt.projection_count;
    let output = finalize_tick(
        &cfg,
        &tick,
        pending,
        NeuronResourceReceiptV1 {
            execution_micros: 200,
            transient_allocation_bytes: 4096,
            checkpoint_bytes: 2048,
            saturation_count,
            queue_age_micros: 0,
        },
    )
    .unwrap_or_else(|error| panic!("finalize: {error:?}"));
    assert!(!output.tick_receipt.receipt_digest.is_zero());
    assert!(!output.signal_receipt.receipt_digest.is_zero());
    assert_eq!(output.tick_receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(output.signal_receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn mismatched_predecessor_fails_before_model_execution() {
    let edges = vec![];
    let cfg = config(&edges);
    let native = profile(edges);
    let mut model = FakeModel;
    let tick = input(1, digest(b"not-zero"));
    let runtime_digest = model_receipt(&cfg).receipt_digest;
    assert!(matches!(
        prepare_tick(
            &cfg,
            &native,
            &mut model,
            &tick,
            None,
            &calibration(&cfg, runtime_digest),
        ),
        Err(RuntimeError::Protocol(crate::ProtocolError::InvalidCheckpointBinding))
    ));
}

#[test]
fn resource_overrun_is_not_reported_as_success() {
    let edges = vec![];
    let cfg = config(&edges);
    let native = profile(edges);
    let mut model = FakeModel;
    let tick = input(1, Digest32::ZERO);
    let runtime_digest = model_receipt(&cfg).receipt_digest;
    let pending = prepare_tick(
        &cfg,
        &native,
        &mut model,
        &tick,
        None,
        &calibration(&cfg, runtime_digest),
    )
    .unwrap_or_else(|error| panic!("prepare: {error:?}"));
    let saturation_count = pending.sparse_receipt.projection_count;
    assert_eq!(
        finalize_tick(
            &cfg,
            &tick,
            pending,
            NeuronResourceReceiptV1 {
                execution_micros: 8_001,
                transient_allocation_bytes: 1,
                checkpoint_bytes: 1,
                saturation_count,
                queue_age_micros: 0,
            },
        ),
        Err(RuntimeError::ResourceCeiling("execution latency"))
    );
}


#[test]
fn runtime_health_orders_temporal_fallbacks_without_granting_authority() {
    let cfg = config(&[]);
    let receipt = SparseSignalReceipt {
        config_digest: digest(b"config"),
        input_digest: digest(b"input"),
        checkpoint_before: Digest32::ZERO,
        checkpoint_after: digest(b"checkpoint"),
        activation_q24: vec![0; 5],
        active_fraction_ppm: 0,
        prediction_error_q24: 0,
        projection_count: 0,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    let dead = assess_runtime_health(
        &cfg,
        &receipt,
        &[],
        CalibratedSignalV1 {
            confidence_ppm: 900_000,
            ood_ppm: 100_000,
            abstain: false,
        },
    );
    assert_eq!(
        dead.disposition,
        RuntimeFallbackDispositionV1::StatelessSelectedHead
    );
    assert_eq!(dead.authority, AuthorityPosture::DENY_ALL);

    let abstain = assess_runtime_health(
        &cfg,
        &receipt,
        &[0],
        CalibratedSignalV1 {
            confidence_ppm: 0,
            ood_ppm: 1_000_000,
            abstain: true,
        },
    );
    assert_eq!(
        abstain.disposition,
        RuntimeFallbackDispositionV1::SlowPathAbstain
    );
}
