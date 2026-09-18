use super::*;

use codex_hepta_neuron::CalibratedSignalV1;
use codex_hepta_neuron::BoundModelExecutionV1;
use codex_hepta_neuron::CalibrationPolicyV1;
use codex_hepta_neuron::FixedPointRoundingV1;
use codex_hepta_neuron::FixedPointScaleV1;
use codex_hepta_neuron::FrozenModelExecutor;
use codex_hepta_neuron::FrozenModelRequestV1;
use codex_hepta_neuron::LineagePolicy;
use codex_hepta_neuron::NativeSparseProfileV1;
use codex_hepta_neuron::NeuronEligibilityProfileV1;
use codex_hepta_neuron::NeuronFixedPointProfileV1;
use codex_hepta_neuron::NeuronHomeostasisProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeHost;
use codex_hepta_neuron::NeuronStateDimensionsV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::NeuronTopKPolicyV1;
use codex_hepta_neuron::RuntimeScopeBindingV1;
use codex_hepta_neuron::RuntimeTickObservationV1;
use codex_hepta_neuron::TopKTieBreakV1;
use codex_hepta_neuron::inhibition_digest;
use codex_hepta_neuron::open_file_witness;
use codex_hepta_neuron::q24_feature_digest;
use codex_hepta_neuron::runtime_profile_digest;
use codex_hepta_types::Generation;
use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronResourceReceiptV1;
use codex_hepta_neuron::NeuronSignalReceiptV1;
use codex_hepta_neuron::NeuronTickReceiptV1;
use codex_hepta_neuron::SparseSignalReceipt;
use codex_hepta_types::AuthorityPosture;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn result(abstain: bool) -> RuntimeTickResultV1 {
    let tick_id = id("tick.1");
    let checkpoint = digest("checkpoint");
    RuntimeTickResultV1 {
        tick_receipt: NeuronTickReceiptV1 {
            tick_id: tick_id.clone(),
            checkpoint_before: Digest32::ZERO,
            checkpoint_after: checkpoint,
            activation_digest: digest("activation"),
            active_indices: vec![0],
            sparsity_ppm: 200_000,
            threshold_digest: digest("threshold"),
            eligibility_digest: digest("eligibility"),
            prediction_error_q24: 1,
            confidence_ppm: if abstain { 0 } else { 900_000 },
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
            resource_receipt: NeuronResourceReceiptV1 {
                execution_micros: 10,
                transient_allocation_bytes: 128,
                checkpoint_bytes: 512,
                saturation_count: 0,
                queue_age_micros: 0,
            },
        },
        signal_receipt: NeuronSignalReceiptV1 {
            signal_set_id: tick_id,
            model_runtime_digest: digest("model-runtime"),
            temporal_state_digest: checkpoint,
            signals_q24: vec![1],
            activation_sparsity_ppm: 200_000,
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
        },
        sparse_receipt: SparseSignalReceipt {
            config_digest: digest("config"),
            input_digest: digest("input"),
            checkpoint_before: Digest32::ZERO,
            checkpoint_after: checkpoint,
            activation_q24: vec![1],
            active_fraction_ppm: 200_000,
            prediction_error_q24: 1,
            projection_count: 0,
            requires_calibration: false,
            authority: AuthorityPosture::DENY_ALL,
        },
        model_runtime_receipt: LocalModelRuntimeReceiptV1 {
            model_id: id("model.1"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q4"),
            backend_id: id("backend.1"),
            device_identity_digest: digest("device"),
            latency_micros: 10,
            resident_bytes: 1024,
        },
        calibration: CalibratedSignalV1 {
            confidence_ppm: if abstain { 0 } else { 900_000 },
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
            calibration_artifact_digest: Some(digest("calibration")),
            fallback_reason: None,
        },
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn calibrated_neuron_signal_remains_advisory_and_authority_free() {
    let receipt = convert_runtime_result(id("tick.1"), result(false)).expect("consumer receipt");
    assert_eq!(
        receipt.disposition,
        NeuronConsumerDispositionV1::AdvisorySignal
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.receipt_digest.is_zero());
}

#[test]
fn neuron_abstention_forces_intelligence_slow_path() {
    let receipt = convert_runtime_result(id("tick.1"), result(true)).expect("consumer receipt");
    assert_eq!(receipt.disposition, NeuronConsumerDispositionV1::SlowPath);
}

#[test]
fn mismatched_tick_or_authority_is_never_normalized_into_success() {
    assert_eq!(
        convert_runtime_result(id("different"), result(false)),
        Err(NeuronConsumerErrorV1::ReceiptMismatch)
    );

    let mut value = result(false);
    value.authority = AuthorityPosture {
        runtime: true,
        ..AuthorityPosture::DENY_ALL
    };
    assert_eq!(
        convert_runtime_result(id("tick.1"), value),
        Err(NeuronConsumerErrorV1::AuthorityViolation)
    );
}


#[derive(Clone)]
struct ProductExecutor {
    execution: BoundModelExecutionV1,
}

impl FrozenModelExecutor for ProductExecutor {
    fn execute(
        &mut self,
        _request: &FrozenModelRequestV1,
    ) -> Result<BoundModelExecutionV1, String> {
        Ok(self.execution.clone())
    }
}

struct AllowAllLineage;

impl LineagePolicy for AllowAllLineage {
    fn allows(&mut self, _digest: Digest32) -> Result<bool, String> {
        Ok(true)
    }
}

#[test]
fn named_product_consumer_executes_the_owner_runtime_boundary() {
    const Q: i64 = 1 << 24;
    let generation = Generation::new(1).expect("generation");
    let config = NeuronRuntimeConfigV1 {
        config_id: id("neuron.config.consumer"),
        generation,
        encoder_digest: digest("weights"),
        head_digest: digest("head"),
        state_dimensions: NeuronStateDimensionsV1 {
            temporal_state: 5,
            activation: 5,
            modulators: 1,
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
            p95_latency_micros: u64::MAX,
            p99_latency_micros: u64::MAX,
            transient_allocation_bytes: u64::MAX,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
        expires_at_unix_micros: 4_102_444_800_000_000,
    };
    let native = NativeSparseProfileV1 {
        normalization_digest: digest("normalization"),
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        local_rule_digest: digest("local-rule"),
    };
    let scope = RuntimeScopeBindingV1 {
        subject_id: id("subject.consumer"),
        scope_digest: digest("scope.consumer"),
        objective_digest: digest("objective.consumer"),
        body_digest: digest("body.consumer"),
    };
    let mut execution = BoundModelExecutionV1 {
        runtime_receipt: LocalModelRuntimeReceiptV1 {
            model_id: id("encoder.consumer"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q4"),
            backend_id: id("fixture.backend"),
            device_identity_digest: digest("device"),
            latency_micros: 10,
            resident_bytes: 1024,
        },
        head_digest: digest("head"),
        runtime_binary_digest: digest("runtime-binary"),
        sbom_digest: digest("sbom"),
        license_digest: digest("license"),
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
        ood_score_q24: 0,
        transient_allocation_bytes: 1024,
        output_digest: Digest32::ZERO,
    };
    execution.output_digest = execution.calculate_output_digest().expect("model digest");
    let profile_digest = runtime_profile_digest(&config, &native).expect("profile digest");
    let journal = tempfile::tempfile().expect("journal");
    let witness_file = tempfile::tempfile().expect("witness");
    let witness = open_file_witness(witness_file, profile_digest, &scope).expect("witness");
    let mut runtime = NeuronRuntimeHost::open(
        journal,
        config,
        native,
        scope.clone(),
        8,
        ProductExecutor { execution },
        witness,
        AllowAllLineage,
        CalibrationPolicyV1 {
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 50_000,
            minimum_confidence_ppm: 500_000,
            saturation_limit: 64,
            maximum_active_fraction_ppm: 200_000,
        },
        None,
        1,
    )
    .expect("runtime");
    let features = vec![Q / 2, Q / 4, 0, 0, 0];
    let receipt = consume_neuron_tick(
        &mut runtime,
        NeuronTickInputV1 {
            tick_id: id("tick.consumer.1"),
            subject_id: scope.subject_id,
            logical_sequence: 1,
            monotonic_time_micros: 1_000,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: q24_feature_digest(&features),
            feature_vector_q24: features,
            objective_digest: scope.objective_digest,
            ndu_snapshot_digest: digest("ndu.consumer"),
            body_generation: Some(generation),
            modulator_digest: None,
        },
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    )
    .expect("consumer");
    assert_eq!(receipt.tick_id, id("tick.consumer.1"));
    assert_eq!(receipt.disposition, NeuronConsumerDispositionV1::SlowPath);
    assert!(!receipt.checkpoint_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}
