use super::*;
use crate::calibration::CalibrationAssessmentV1;
use crate::fallback::RuntimePathV1;
use crate::model::FrozenHeadOutputV1;
use crate::model::LocalModelRuntimeReceiptV1;
use crate::sparse_tick;
use pretty_assertions::assert_eq;

fn must<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation() -> Generation {
    must(Generation::new(/*value*/ 3))
}

fn native() -> NativeNeuronProfileV1 {
    NativeNeuronProfileV1 {
        normalization_digest: digest(b"normalization"),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        target_activity_q24: Q / 8,
        local_rule_digest: digest(b"eligibility-local-rule"),
        inhibition: vec![InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q / 2,
        }],
    }
}

fn config() -> NeuronRuntimeConfigV1 {
    let native = native();
    NeuronRuntimeConfigV1 {
        config_id: id("neuron-runtime:3"),
        generation: generation(),
        encoder_digest: digest(b"encoder"),
        head_digest: digest(b"head"),
        state_dimensions: RuntimeStateDimensionsV1 {
            temporal_state: 5,
            activation: 5,
            modulators: 2,
            inhibition_edges: 1,
        },
        fixed_point_profile: FixedPointProfileV1 {
            state_scale: StateScaleV1::Q24,
            rounding: RoundingV1::NearestTiesEven,
            state_minimum_q24: -H,
            state_maximum_q24: H,
            checked_wide_intermediates: true,
        },
        top_k_policy: TopKPolicyV1 {
            minimum_ratio_ppm: 10_000,
            maximum_ratio_ppm: 200_000,
            tie_break: TieBreakV1::CanonicalUnitId,
            per_population_first: true,
        },
        inhibition_digest: must(digest_inhibition(native.width, &native.inhibition)),
        homeostasis_profile: HomeostasisProfileV1 {
            moving_average_alpha_q24: Q,
            threshold_step_q24: Q / 8,
            threshold_minimum_q24: -Q,
            threshold_maximum_q24: Q,
            saturation_limit: 16,
        },
        eligibility_profile: EligibilityProfileV1 {
            trace_dimension: 5,
            maximum_norm_q24: ELIGIBILITY_L1,
            decay_q24: Q / 2,
            local_rule_digest: native.local_rule_digest,
        },
        resource_envelope: RuntimeResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 512 * 1024,
            checkpoint_bytes: 1024 * 1024,
            write_amplification_ppm: 4_000_000,
        },
        expiry_unix_micros: 10_000,
    }
}

fn input(checkpoint_digest: Digest32) -> NeuronTickInputV1 {
    NeuronTickInputV1 {
        tick_id: id("tick:1"),
        subject_id: id("subject:1"),
        logical_sequence: 1,
        monotonic_time_micros: 100,
        checkpoint_digest,
        input_feature_digest: digest(b"approved-features"),
        feature_vector_q24: vec![Q, 0, -Q],
        objective_digest: digest(b"objective"),
        ndu_snapshot_digest: digest(b"ndu"),
        body_generation: Some(9),
        modulator_digest: None,
    }
}

fn bindings() -> RuntimeBindingsV1 {
    RuntimeBindingsV1 {
        scope_digest: digest(b"principal/run"),
        body_digest: digest(b"body"),
        body_generation: Some(9),
    }
}

fn output() -> FrozenHeadOutputV1 {
    FrozenHeadOutputV1 {
        drive_q24: vec![Q, Q, 0, 0, 0],
        prediction_q24: vec![0; 5],
        ood_score_q24: Q / 8,
    }
}

fn model_receipt() -> LocalModelRuntimeReceiptV1 {
    LocalModelRuntimeReceiptV1 {
        request_id: id("model-request:1"),
        manifest_digest: digest(b"manifest"),
        input_digest: digest(b"model-input"),
        output_digest: digest(b"model-output"),
        runtime_digest: digest(b"runtime"),
        device_digest: digest(b"device"),
        execution_micros: 100,
        observed_memory_bytes: 4096,
        terminal_observed: true,
        succeeded: true,
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn canonical_config_and_tick_project_into_the_native_kernel() {
    let sparse_config = must(bind_sparse_config(&config(), &native(), /*now_unix_micros*/ 1));
    assert_eq!(sparse_config.width, 5);
    assert_eq!(sparse_config.top_k, 1);
    assert_eq!(sparse_config.activity_decay_q24, 0);
    assert_eq!(sparse_config.model_digest, config().head_digest);

    let input = input(Digest32::ZERO);
    let tick = must(build_sparse_tick(&input, bindings(), &output(), sparse_config.width));
    assert_eq!(tick.input_digest, must(input.semantic_digest()));
    let (checkpoint, signal) = must(sparse_tick(&sparse_config, &tick, /*previous*/ None));
    let calibration = CalibrationAssessmentV1 {
        profile_digest: digest(b"calibration-profile"),
        prediction_error_q24: signal.prediction_error_q24,
        ood_score_q24: Q / 8,
        confidence_ppm: 900_000,
        ood_ppm: 125_000,
        abstain: false,
        assessment_digest: digest(b"assessment"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let outcome = must(compose_tick_outcome(
        &config(),
        &input,
        &checkpoint,
        &signal,
        model_receipt(),
        calibration,
        RuntimePathV1::TemporalCheckpoint,
        RuntimeResourceReceiptV1 {
            execution_micros: 500,
            transient_allocation_bytes: 4096,
            checkpoint_bytes: 8192,
            saturation_count: signal.projection_count,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(outcome.receipt.checkpoint_after, checkpoint.digest());
    assert_eq!(outcome.receipt.active_indices, vec![0]);
    assert_eq!(outcome.receipt.sparsity_ppm, 200_000);
    assert_eq!(outcome.receipt.confidence_ppm, 900_000);
    assert!(!outcome.receipt.abstain);
    assert!(!outcome.receipt.receipt_digest.is_zero());
    assert_eq!(outcome.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn body_and_predecessor_bindings_fail_closed() {
    let mut wrong_body = input(Digest32::ZERO);
    wrong_body.body_generation = Some(10);
    assert_eq!(
        build_sparse_tick(&wrong_body, bindings(), &output(), /*expected_width*/ 5),
        Err(ProtocolError::BodyMismatch)
    );

    let sparse_config = must(bind_sparse_config(&config(), &native(), /*now_unix_micros*/ 1));
    let input = input(digest(b"wrong-predecessor"));
    let tick = must(build_sparse_tick(&input, bindings(), &output(), sparse_config.width));
    let (checkpoint, signal) = must(sparse_tick(&sparse_config, &tick, /*previous*/ None));
    let calibration = CalibrationAssessmentV1 {
        profile_digest: digest(b"profile"),
        prediction_error_q24: signal.prediction_error_q24,
        ood_score_q24: 0,
        confidence_ppm: 1_000_000,
        ood_ppm: 0,
        abstain: false,
        assessment_digest: digest(b"assessment"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        compose_tick_outcome(
            &config(),
            &input,
            &checkpoint,
            &signal,
            model_receipt(),
            calibration,
            RuntimePathV1::TemporalCheckpoint,
            RuntimeResourceReceiptV1 {
                execution_micros: 1,
                transient_allocation_bytes: 0,
                checkpoint_bytes: 1,
                saturation_count: signal.projection_count,
                queue_age_micros: 0,
            },
        ),
        Err(ProtocolError::CheckpointMismatch)
    );
}

#[test]
fn native_graph_and_local_rule_must_match_the_canonical_config() {
    let mut graph_mismatch = native();
    graph_mismatch.inhibition[0].weight_q24 += 1;
    assert_eq!(
        bind_sparse_config(&config(), &graph_mismatch, /*now_unix_micros*/ 1),
        Err(ProtocolError::InhibitionMismatch)
    );

    let mut rule_mismatch = native();
    rule_mismatch.local_rule_digest = digest(b"other-rule");
    assert_eq!(
        bind_sparse_config(&config(), &rule_mismatch, /*now_unix_micros*/ 1),
        Err(ProtocolError::LocalRuleMismatch)
    );
}

#[test]
fn expired_and_oversized_profiles_reject_before_kernel_construction() {
    assert_eq!(
        bind_sparse_config(&config(), &native(), /*now_unix_micros*/ 10_000),
        Err(ProtocolError::ExpiredConfig)
    );
    let mut oversized = config();
    oversized.resource_envelope.checkpoint_bytes = MAX_CHECKPOINT_BYTES + 1;
    assert_eq!(
        bind_sparse_config(&oversized, &native(), /*now_unix_micros*/ 1),
        Err(ProtocolError::InvalidConfig)
    );
}
