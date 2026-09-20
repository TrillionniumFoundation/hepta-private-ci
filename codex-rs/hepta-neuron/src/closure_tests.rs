use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::sync::Mutex;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

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

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn config() -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: id("neuron.config.1"),
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
            p95_latency_micros: 1,
            p99_latency_micros: u64::MAX,
            transient_allocation_bytes: u64::MAX,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
        expires_at_unix_micros: 4_102_444_800_000_000,
    }
}

fn native() -> NativeSparseProfileV1 {
    NativeSparseProfileV1 {
        normalization_digest: digest("normalization"),
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        local_rule_digest: digest("local-rule"),
    }
}

fn scope() -> RuntimeScopeBindingV1 {
    RuntimeScopeBindingV1 {
        subject_id: id("subject.1"),
        scope_digest: digest("principal.run.1"),
        objective_digest: digest("objective.1"),
        body_digest: digest("body.1"),
    }
}

fn input(sequence: u64, checkpoint: Digest32) -> NeuronTickInputV1 {
    let features = vec![Q / 2, Q / 4, Q / 8, 0, -Q / 8];
    NeuronTickInputV1 {
        tick_id: id(&format!("tick.{sequence}")),
        subject_id: scope().subject_id,
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest: checkpoint,
        input_feature_digest: q24_feature_digest(&features),
        feature_vector_q24: features,
        objective_digest: scope().objective_digest,
        ndu_snapshot_digest: digest("ndu.1"),
        body_generation: Some(generation(1)),
        modulator_digest: Some(digest("modulator.1")),
    }
}

fn model_execution() -> BoundModelExecutionV1 {
    let mut execution = BoundModelExecutionV1 {
        runtime_receipt: LocalModelRuntimeReceiptV1 {
            model_id: id("encoder.1"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q4"),
            backend_id: id("test.backend"),
            device_identity_digest: digest("device"),
            latency_micros: 10,
            resident_bytes: 1024,
        },
        head_digest: digest("head"),
        runtime_binary_digest: digest("runtime-binary"),
        sbom_digest: digest("sbom"),
        license_digest: digest("license"),
        ood_detector_digest: digest("ood-detector"),
        drive_q24: vec![Q, Q / 2, Q / 4, 0, -Q / 4],
        prediction_q24: vec![0; 5],
        ood_score_q24: Q / 10,
        transient_allocation_bytes: 2048,
        output_digest: Digest32::ZERO,
    };
    execution.output_digest = checked(execution.calculate_output_digest());
    execution
}

fn calibration_artifact() -> NeuronCalibrationArtifactV1 {
    let config = config();
    let execution = model_execution();
    let mut artifact = NeuronCalibrationArtifactV1 {
        artifact_digest: Digest32::ZERO,
        config_digest: checked(runtime_profile_digest(&config, &native())),
        policy_digest: checked(calibration_policy().digest()),
        model_identity_digest: checked(execution.model_identity_digest()),
        generation: config.generation,
        valid_from_sequence: 1,
        expires_after_sequence: 128,
        measured_ece_ppm: 10_000,
        measured_ood_false_acceptance_ppm: 10_000,
        subgroup_audit_digest: digest("subgroup-audit"),
        detector_digest: digest("ood-detector"),
        support_digest: digest("calibration-support"),
        maximum_in_domain_ood_q24: Q / 2,
        bins: vec![
            CalibrationBinV1 {
                maximum_prediction_error_q24: 2 * Q,
                confidence_ppm: 900_000,
            },
            CalibrationBinV1 {
                maximum_prediction_error_q24: 16 * Q,
                confidence_ppm: 100_000,
            },
        ],
    };
    artifact.artifact_digest = checked(artifact.calculate_digest());
    artifact
}

fn calibration_policy() -> CalibrationPolicyV1 {
    CalibrationPolicyV1 {
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 50_000,
        minimum_confidence_ppm: 500_000,
        saturation_limit: 64,
        maximum_active_fraction_ppm: 200_000,
    }
}

fn selected_model_manifest() -> SelectedNeuronModelManifestV1 {
    let execution = model_execution();
    SelectedNeuronModelManifestV1 {
        encoder_digest: execution.runtime_receipt.weights_digest,
        head_digest: execution.head_digest,
        tokenizer_digest: execution.runtime_receipt.tokenizer_digest,
        preprocessor_digest: execution.runtime_receipt.preprocessor_digest,
        quantization_id: execution.runtime_receipt.quantization_id,
        backend_id: execution.runtime_receipt.backend_id,
        device_identity_digest: execution.runtime_receipt.device_identity_digest,
        runtime_binary_digest: execution.runtime_binary_digest,
        sbom_digest: execution.sbom_digest,
        license_digest: execution.license_digest,
        ood_detector_digest: execution.ood_detector_digest,
    }
}

fn canonical_config_digest() -> Digest32 {
    checked(bound_runtime_profile_digest(
        &config(),
        &native(),
        &selected_model_manifest(),
    ))
}

fn canonical_calibration_artifact() -> NeuronCalibrationArtifactV1 {
    let config = config();
    let execution = model_execution();
    let mut artifact = NeuronCalibrationArtifactV1 {
        artifact_digest: Digest32::ZERO,
        config_digest: canonical_config_digest(),
        policy_digest: checked(calibration_policy().digest()),
        model_identity_digest: checked(execution.model_identity_digest()),
        generation: config.generation,
        valid_from_sequence: 1,
        expires_after_sequence: 128,
        measured_ece_ppm: 10_000,
        measured_ood_false_acceptance_ppm: 10_000,
        subgroup_audit_digest: digest("subgroup-audit"),
        detector_digest: digest("ood-detector"),
        support_digest: digest("calibration-support"),
        maximum_in_domain_ood_q24: Q / 2,
        bins: vec![
            CalibrationBinV1 {
                maximum_prediction_error_q24: 2 * Q,
                confidence_ppm: 900_000,
            },
            CalibrationBinV1 {
                maximum_prediction_error_q24: 16 * Q,
                confidence_ppm: 100_000,
            },
        ],
    };
    artifact.artifact_digest = checked(artifact.calculate_digest());
    artifact
}

fn canonical_request_digest(input: &NeuronTickInputV1) -> Digest32 {
    let encoded = checked(encode_neuron_tick_input_v1(input));
    let mut bytes = b"hepta.neuron.runtime-operation-request.v1".to_vec();
    bytes.extend_from_slice(canonical_config_digest().as_array());
    bytes.extend_from_slice(
        &u32::try_from(encoded.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&encoded);
    Digest32::of_bytes(&bytes)
}

fn plasticity_ancestry() -> PlasticityAncestryV1 {
    PlasticityAncestryV1 {
        selected_artifact_digest: digest("selected-artifact"),
        generation: generation(1),
        parameter_manifest_digest: digest("parameter-manifest"),
        window_digest: digest("plasticity-window"),
        update_rule_digest: digest("local-rule"),
        predecessor_digest: digest("selected-artifact"),
    }
}

fn canonical_required_lineage(input: &NeuronTickInputV1) -> Vec<Digest32> {
    let mut values = checked(selected_model_manifest().lineage_digests());
    values.extend([
        scope().objective_digest,
        scope().body_digest,
        input.input_feature_digest,
        input.objective_digest,
        input.ndu_snapshot_digest,
    ]);
    if let Some(modulator) = input.modulator_digest {
        values.push(modulator);
    }
    let calibration = canonical_calibration_artifact();
    values.extend([
        calibration.artifact_digest,
        calibration.subgroup_audit_digest,
        calibration.detector_digest,
        calibration.support_digest,
    ]);
    values
}

fn canonical_result(
    input: &NeuronTickInputV1,
    previous: Option<&SparseCheckpoint>,
) -> RuntimeTickResultV1 {
    let execution = model_execution();
    let sparse_config = checked(bound_sparse_config(
        &config(),
        &native(),
        &selected_model_manifest(),
    ));
    let sparse_input = input.to_sparse_tick(&scope(), &execution);
    let (checkpoint, sparse_receipt) = checked(sparse_tick(
        &sparse_config,
        &sparse_input,
        previous,
    ));
    let calibration = checked(apply_calibration(
        calibration_policy(),
        Some(&canonical_calibration_artifact()),
        CalibrationObservationV1 {
            config_digest: canonical_config_digest(),
            model_identity_digest: checked(execution.model_identity_digest()),
            ood_detector_digest: execution.ood_detector_digest,
            generation: config().generation,
            sequence: input.logical_sequence,
            prediction_error_q24: sparse_receipt.prediction_error_q24,
            ood_score_q24: execution.ood_score_q24,
            active_fraction_ppm: sparse_receipt.active_fraction_ppm,
            projection_count: sparse_receipt.projection_count,
        },
    ));
    let resources = NeuronResourceReceiptV1 {
        execution_micros: execution.runtime_receipt.latency_micros,
        transient_allocation_bytes: execution.transient_allocation_bytes,
        checkpoint_bytes: u64::try_from(checkpoint.estimated_encoded_bytes()).unwrap_or(u64::MAX),
        saturation_count: sparse_receipt.projection_count,
        queue_age_micros: 0,
    };
    let tick_receipt = NeuronTickReceiptV1 {
        tick_id: input.tick_id.clone(),
        checkpoint_before: sparse_receipt.checkpoint_before,
        checkpoint_after: sparse_receipt.checkpoint_after,
        activation_digest: checkpoint.activation_digest(),
        active_indices: checked(active_indices(&sparse_receipt.activation_q24)),
        sparsity_ppm: sparse_receipt.active_fraction_ppm,
        threshold_digest: checkpoint.threshold_digest(),
        eligibility_digest: checkpoint.eligibility_digest(),
        prediction_error_q24: sparse_receipt.prediction_error_q24,
        confidence_ppm: calibration.confidence_ppm,
        ood_ppm: calibration.ood_ppm,
        abstain: calibration.abstain,
        resource_receipt: resources,
    };
    RuntimeTickResultV1 {
        signal_receipt: NeuronSignalReceiptV1 {
            signal_set_id: input.tick_id.clone(),
            model_runtime_digest: checked(execution.model_runtime_digest()),
            temporal_state_digest: checkpoint.digest(),
            signals_q24: sparse_receipt.activation_q24.clone(),
            activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
            ood_ppm: calibration.ood_ppm,
            abstain: calibration.abstain,
        },
        tick_receipt,
        sparse_receipt,
        model_runtime_receipt: execution.runtime_receipt,
        calibration,
        authority: AuthorityPosture::DENY_ALL,
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-closure-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self { root }
    }

    fn file(&self, name: &str) -> std::fs::File {
        let path = self.root.join(name);
        if !path.exists() {
            checked(OpenOptions::new().write(true).create_new(true).open(&path));
        }
        checked(OpenOptions::new().read(true).write(true).open(path))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn canonical_adapter_binds_config_input_and_exact_model_execution() {
    let config = config();
    let native = native();
    let sparse = checked(config.to_sparse_config(&native));
    assert_eq!(sparse.width, 5);
    assert_eq!(sparse.top_k, 1);

    let input = input(1, Digest32::ZERO);
    checked(input.validate_for(&config, &scope(), None));

    let execution = model_execution();
    checked(execution.validate_for(&config));
    assert_ne!(
        checked(execution.runtime_receipt.identity_digest()),
        checked(execution.runtime_receipt.digest())
    );

    let mut changed_allocation = execution.clone();
    changed_allocation.transient_allocation_bytes += 1;
    assert_ne!(
        checked(changed_allocation.calculate_output_digest()),
        execution.output_digest
    );

    let mut changed = execution;
    changed.head_digest = digest("other-head");
    assert!(matches!(
        changed.validate_for(&config),
        Err(ProtocolError::InvalidModelExecution("head mismatch"))
    ));
}

#[test]
fn exact_runtime_profile_digest_changes_with_native_mechanism_parameters() {
    let config = config();
    let first = checked(runtime_profile_digest(&config, &native()));
    let mut changed = native();
    changed.temporal_decay_q24 += 1;
    let second = checked(runtime_profile_digest(&config, &changed));
    assert_ne!(first, second);
}

#[test]
fn calibration_policy_drift_cannot_reuse_an_old_artifact() {
    let config = config();
    let execution = model_execution();
    let artifact = calibration_artifact();
    let mut policy = calibration_policy();
    policy.minimum_confidence_ppm += 1;
    let calibrated = checked(apply_calibration(
        policy,
        Some(&artifact),
        CalibrationObservationV1 {
            config_digest: checked(runtime_profile_digest(&config, &native())),
            model_identity_digest: checked(execution.model_identity_digest()),
            ood_detector_digest: execution.ood_detector_digest,
            generation: config.generation,
            sequence: 1,
            prediction_error_q24: Q,
            ood_score_q24: Q / 10,
            active_fraction_ppm: 200_000,
            projection_count: 0,
        },
    ));
    assert!(calibrated.abstain);
    assert_eq!(
        calibrated.fallback_reason,
        Some(SignalFallbackReasonV1::CalibrationBindingMismatch)
    );
}

#[test]
fn calibration_is_fail_closed_and_uses_independently_bound_artifacts() {
    let config_digest = checked(runtime_profile_digest(&config(), &native()));
    let execution = model_execution();
    let identity = checked(execution.model_identity_digest());
    let missing = checked(apply_calibration(
        calibration_policy(),
        None,
        CalibrationObservationV1 {
            config_digest,
            model_identity_digest: identity,
            ood_detector_digest: execution.ood_detector_digest,
            generation: generation(1),
            sequence: 1,
            prediction_error_q24: Q,
            ood_score_q24: Q / 10,
            active_fraction_ppm: 200_000,
            projection_count: 0,
        },
    ));
    assert!(missing.abstain);
    assert_eq!(
        missing.fallback_reason,
        Some(SignalFallbackReasonV1::MissingCalibration)
    );

    let artifact = calibration_artifact();
    let qualified = checked(apply_calibration(
        calibration_policy(),
        Some(&artifact),
        CalibrationObservationV1 {
            config_digest,
            model_identity_digest: identity,
            ood_detector_digest: execution.ood_detector_digest,
            generation: generation(1),
            sequence: 1,
            prediction_error_q24: Q,
            ood_score_q24: Q / 10,
            active_fraction_ppm: 200_000,
            projection_count: 0,
        },
    ));
    assert!(!qualified.abstain);
    assert_eq!(qualified.confidence_ppm, 900_000);

    let ood = checked(apply_calibration(
        calibration_policy(),
        Some(&artifact),
        CalibrationObservationV1 {
            config_digest,
            model_identity_digest: identity,
            ood_detector_digest: execution.ood_detector_digest,
            generation: generation(1),
            sequence: 1,
            prediction_error_q24: Q,
            ood_score_q24: Q,
            active_fraction_ppm: 200_000,
            projection_count: 0,
        },
    ));
    assert!(ood.abstain);
    assert_eq!(
        ood.fallback_reason,
        Some(SignalFallbackReasonV1::OutOfDistribution)
    );
}

#[test]
fn plasticity_requires_explicit_parameter_group_broadcast_and_is_deterministic() {
    let sparse_config = checked(config().to_sparse_config(&native()));
    let execution = model_execution();
    let first_tick = input(1, Digest32::ZERO).to_sparse_tick(&scope(), &execution);
    let (first_checkpoint, _) = checked(sparse_tick(&sparse_config, &first_tick, None));
    let second_tick = input(2, first_checkpoint.digest()).to_sparse_tick(&scope(), &execution);
    let (second_checkpoint, _) = checked(sparse_tick(
        &sparse_config,
        &second_tick,
        Some(&first_checkpoint),
    ));
    let history = vec![
        checked(PlasticitySampleV1::from_checkpoint(
            &first_checkpoint,
            vec![Q / 2, Q / 4],
            digest("modulator-evidence.1"),
        )),
        checked(PlasticitySampleV1::from_checkpoint(
            &second_checkpoint,
            vec![Q / 4, Q / 2],
            digest("modulator-evidence.2"),
        )),
    ];
    let groups = vec![
        EligibilityParameterGroupV1 {
            group_id: id("group.a"),
            eligibility_indices: vec![0, 1],
        },
        EligibilityParameterGroupV1 {
            group_id: id("group.b"),
            eligibility_indices: vec![2, 3, 4],
        },
    ];
    let broadcast = vec![
        ModulatorBroadcastRowV1 {
            group_id: id("group.a"),
            weights_q24: vec![Q, 0],
        },
        ModulatorBroadcastRowV1 {
            group_id: id("group.b"),
            weights_q24: vec![0, Q],
        },
    ];
    let trust = PlasticityTrustRegionV1 {
        maximum_group_absolute_q24: Q,
        maximum_total_l1_q24: 2 * Q,
    };
    let first = checked(accumulate_plasticity(&plasticity_ancestry(), &history, &groups, &broadcast, trust));
    let mut shuffled = broadcast.clone();
    shuffled.reverse();
    assert_eq!(
        checked(accumulate_plasticity(&plasticity_ancestry(), &history, &groups, &shuffled, trust)),
        first
    );
    assert_eq!(first.sample_count, 2);
    assert!(!first.statistics_digest.is_zero());
    assert_eq!(
        first.selected_artifact_digest,
        plasticity_ancestry().selected_artifact_digest
    );
    assert_eq!(first.generation, plasticity_ancestry().generation);
    assert_eq!(
        first.parameter_manifest_digest,
        plasticity_ancestry().parameter_manifest_digest
    );
    let mut changed_ancestry = plasticity_ancestry();
    changed_ancestry.window_digest = digest("other-window");
    assert_ne!(
        checked(accumulate_plasticity(
            &changed_ancestry,
            &history,
            &groups,
            &broadcast,
            trust,
        ))
        .statistics_digest,
        first.statistics_digest
    );

    assert_eq!(
        accumulate_plasticity(&plasticity_ancestry(), &history, &groups, &broadcast[..1], trust),
        Err(PlasticityError::BroadcastMismatch)
    );
}

#[test]
fn durable_witness_reopens_exact_acknowledged_anchor() {
    let fixture = Fixture::new();
    let context = digest("witness-context");
    let anchor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: digest("checkpoint"),
    };
    {
        let mut witness = checked(FileRecoveryWitness::open(fixture.file("witness"), context));
        assert_eq!(checked(witness.current_anchor()), None);
        checked(witness.compare_and_store(None, anchor));
        assert_eq!(checked(witness.current_anchor()), Some(anchor));
    }
    let reopened = checked(FileRecoveryWitness::open(fixture.file("witness"), context));
    assert_eq!(checked(reopened.current_anchor()), Some(anchor));
}

#[test]
fn torn_witness_update_preserves_the_previous_durable_anchor() {
    let fixture = Fixture::new();
    let context = digest("witness-tear-context");
    let first = JournalAnchor {
        sequence: 1,
        checkpoint_digest: digest("checkpoint-1"),
    };
    let second = JournalAnchor {
        sequence: 2,
        checkpoint_digest: digest("checkpoint-2"),
    };
    {
        let mut witness = checked(FileRecoveryWitness::open(
            fixture.file("witness-tear"),
            context,
        ));
        checked(witness.compare_and_store(None, first));
        checked(witness.compare_and_store(Some(first), second));
    }

    let path = fixture.root.join("witness-tear");
    let length = checked(fs::metadata(&path)).len();
    assert_eq!(length % 2, 0);
    let mut file = checked(OpenOptions::new().read(true).write(true).open(&path));
    checked(file.seek(SeekFrom::Start(length / 2)));
    checked(file.write_all(b"BROKEN"));
    checked(file.sync_all());
    drop(file);

    let reopened = checked(FileRecoveryWitness::open(
        fixture.file("witness-tear"),
        context,
    ));
    assert_eq!(checked(reopened.current_anchor()), Some(second));
}

#[derive(Clone)]
struct Executor {
    execution: BoundModelExecutionV1,
}

impl FrozenModelExecutor for Executor {
    fn execute(
        &mut self,
        _request: &FrozenModelRequestV1,
    ) -> Result<BoundModelExecutionV1, String> {
        Ok(self.execution.clone())
    }
}

struct FailOnceWitness {
    inner: FileRecoveryWitness,
    fail_sequence: u64,
}

impl RecoveryWitnessStore for FailOnceWitness {
    fn current_anchor(&self) -> Result<Option<JournalAnchor>, WitnessError> {
        self.inner.current_anchor()
    }

    fn compare_and_store(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessError> {
        if next.sequence == self.fail_sequence {
            return Err(WitnessError::Indeterminate);
        }
        self.inner.compare_and_store(expected, next)
    }
}

#[derive(Clone)]
struct Lineage {
    denied: Option<Digest32>,
}

impl LineagePolicy for Lineage {
    fn allows(&mut self, digest: Digest32) -> Result<bool, String> {
        Ok(self.denied != Some(digest))
    }
}

#[test]
fn runtime_executes_model_commits_witness_and_rotates_without_state_reset() {
    let fixture = Fixture::new();
    let runtime_config = config();
    let runtime_scope = scope();
    let config_digest = checked(runtime_profile_digest(&runtime_config, &native()));
    let witness = checked(open_file_witness(
        fixture.file("witness"),
        config_digest,
        &runtime_scope,
    ));
    let mut runtime = checked(LegacyNeuronRuntimeHost::open(
        fixture.file("segment-1"),
        runtime_config,
        native(),
        runtime_scope,
        1,
        Executor {
            execution: model_execution(),
        },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(calibration_artifact()),
        1,
    ));

    let first = checked(runtime.tick(
        input(1, Digest32::ZERO),
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ));
    assert!(!first.tick_receipt.abstain);
    assert!(!first.authority.grants_any());
    assert_eq!(runtime.remaining_records(), 0);

    let checkpoint = first.tick_receipt.checkpoint_after;
    let genesis = checked(runtime.current_checkpoint())
        .cloned()
        .expect("first checkpoint");
    let mut runtime = checked(runtime.rotate(fixture.file("segment-2"), 2));
    let second = checked(runtime.tick(
        input(2, checkpoint),
        RuntimeTickObservationV1 {
            now_unix_micros: 3,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(second.tick_receipt.checkpoint_before, checkpoint);
    assert_ne!(second.tick_receipt.checkpoint_after, checkpoint);
    assert_eq!(
        checked(runtime.current_checkpoint()).map(SparseCheckpoint::sequence),
        Some(2)
    );

    let terminal = second.tick_receipt.checkpoint_after;
    drop(runtime);
    let reopened_witness = checked(open_file_witness(
        fixture.file("witness"),
        config_digest,
        &scope(),
    ));
    let reopened = checked(LegacyNeuronRuntimeHost::open_with_genesis(
        fixture.file("segment-2"),
        config(),
        native(),
        scope(),
        2,
        Executor {
            execution: model_execution(),
        },
        reopened_witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(calibration_artifact()),
        genesis,
        4,
    ));
    assert_eq!(
        checked(reopened.current_checkpoint()).map(SparseCheckpoint::digest),
        Some(terminal)
    );
}

#[test]
fn reopen_reconciles_a_durable_suffix_before_accepting_new_ticks() {
    let fixture = Fixture::new();
    let config = config();
    let scope = scope();
    let config_digest = checked(runtime_profile_digest(&config, &native()));
    let witness = checked(open_file_witness(
        fixture.file("witness-reconcile"),
        config_digest,
        &scope,
    ));
    let mut runtime = checked(LegacyNeuronRuntimeHost::open(
        fixture.file("segment-reconcile"),
        config.clone(),
        native(),
        scope.clone(),
        8,
        Executor {
            execution: model_execution(),
        },
        FailOnceWitness {
            inner: witness,
            fail_sequence: 2,
        },
        Lineage { denied: None },
        calibration_policy(),
        Some(calibration_artifact()),
        1,
    ));

    let first = checked(runtime.tick(
        input(1, Digest32::ZERO),
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ));
    let second_digest = match runtime.tick(
        input(2, first.tick_receipt.checkpoint_after),
        RuntimeTickObservationV1 {
            now_unix_micros: 3,
            queue_age_micros: 0,
        },
    ) {
        Err(RuntimeError::WitnessIndeterminate(checkpoint)) => checkpoint,
        other => panic!("expected witness uncertainty after durable journal commit: {other:?}"),
    };
    drop(runtime);

    let reopened_witness = checked(open_file_witness(
        fixture.file("witness-reconcile"),
        config_digest,
        &scope,
    ));
    let mut reopened = checked(LegacyNeuronRuntimeHost::open(
        fixture.file("segment-reconcile"),
        config,
        native(),
        scope,
        8,
        Executor {
            execution: model_execution(),
        },
        reopened_witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(calibration_artifact()),
        4,
    ));
    assert_eq!(
        checked(reopened.current_checkpoint()).map(SparseCheckpoint::digest),
        Some(second_digest)
    );
    let third = checked(reopened.tick(
        input(3, second_digest),
        RuntimeTickObservationV1 {
            now_unix_micros: 5,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(third.tick_receipt.checkpoint_before, second_digest);
}

#[test]
fn failed_deletion_rebuild_poisoned_partial_state_is_not_reusable() {
    let fixture = Fixture::new();
    let config = config();
    let native = native();
    let scope = scope();
    let sparse_config = checked(config.to_sparse_config(&native));
    let execution = model_execution();
    let first_input = input(1, Digest32::ZERO);
    let first_tick = first_input.to_sparse_tick(&scope, &execution);
    let (first_checkpoint, _) = checked(sparse_tick(&sparse_config, &first_tick, None));

    let mut revoked_input = input(2, first_checkpoint.digest());
    revoked_input.feature_vector_q24[0] += 1;
    revoked_input.input_feature_digest = q24_feature_digest(&revoked_input.feature_vector_q24);
    let denied = revoked_input.input_feature_digest;

    let config_digest = checked(runtime_profile_digest(&config, &native));
    let witness = checked(open_file_witness(
        fixture.file("witness-partial-rebuild"),
        config_digest,
        &scope,
    ));
    let mut runtime = checked(LegacyNeuronRuntimeHost::open(
        fixture.file("partial-rebuild"),
        config,
        native,
        scope,
        8,
        Executor {
            execution: model_execution(),
        },
        witness,
        Lineage {
            denied: Some(denied),
        },
        calibration_policy(),
        Some(calibration_artifact()),
        1,
    ));

    assert_eq!(
        runtime.rebuild_from_ordered_inputs(vec![
            (
                first_input,
                RuntimeTickObservationV1 {
                    now_unix_micros: 2,
                    queue_age_micros: 0,
                },
            ),
            (
                revoked_input,
                RuntimeTickObservationV1 {
                    now_unix_micros: 3,
                    queue_age_micros: 0,
                },
            ),
        ]),
        Err(RuntimeError::RevokedLineage)
    );
    assert_eq!(runtime.current_checkpoint(), Err(RuntimeError::Poisoned));
}

#[test]
fn deletion_rebuild_rechecks_live_lineage_before_model_execution() {
    let fixture = Fixture::new();
    let config = config();
    let scope = scope();
    let config_digest = checked(runtime_profile_digest(&config, &native()));
    let witness = checked(open_file_witness(
        fixture.file("witness"),
        config_digest,
        &scope,
    ));
    let revoked_input = input(1, Digest32::ZERO);
    let denied = revoked_input.input_feature_digest;
    let mut runtime = checked(LegacyNeuronRuntimeHost::open(
        fixture.file("rebuild"),
        config,
        native(),
        scope,
        8,
        Executor {
            execution: model_execution(),
        },
        witness,
        Lineage {
            denied: Some(denied),
        },
        calibration_policy(),
        Some(calibration_artifact()),
        1,
    ));
    assert_eq!(
        runtime.rebuild_from_ordered_inputs(vec![(
            revoked_input,
            RuntimeTickObservationV1 {
                now_unix_micros: 2,
                queue_age_micros: 0,
            },
        )]),
        Err(RuntimeError::RevokedLineage)
    );
    assert!(checked(runtime.current_checkpoint()).is_none());
}

#[test]
fn native_profile_rejects_unimplemented_per_population_competition() {
    let mut config = config();
    config.top_k_policy.per_population_first = true;
    assert_eq!(
        config.to_sparse_config(&native()),
        Err(ProtocolError::InvalidNativeProfile(
            "native Q24 profile does not implement per-population competition"
        ))
    );
}

#[test]
fn runtime_rejects_revoked_calibration_evidence_before_model_execution() {
    let fixture = Fixture::new();
    let config = config();
    let scope = scope();
    let config_digest = checked(runtime_profile_digest(&config, &native()));
    let witness = checked(open_file_witness(
        fixture.file("witness-calibration-lineage"),
        config_digest,
        &scope,
    ));
    let artifact = calibration_artifact();
    let denied = artifact.support_digest;
    let result = LegacyNeuronRuntimeHost::open(
        fixture.file("calibration-lineage"),
        config,
        native(),
        scope,
        8,
        Executor {
            execution: model_execution(),
        },
        witness,
        Lineage {
            denied: Some(denied),
        },
        calibration_policy(),
        Some(artifact),
        1,
    );
    assert!(matches!(result, Err(RuntimeError::RevokedLineage)));
}


#[derive(Clone)]
struct CountingExecutor {
    execution: BoundModelExecutionV1,
    calls: Arc<AtomicU64>,
}

impl FrozenModelExecutor for CountingExecutor {
    fn execute(
        &mut self,
        _request: &FrozenModelRequestV1,
    ) -> Result<BoundModelExecutionV1, String> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        Ok(self.execution.clone())
    }
}

#[derive(Clone)]
struct RevokingExecutor {
    execution: BoundModelExecutionV1,
    denied: Arc<Mutex<Option<Digest32>>>,
    revoke: Digest32,
}

impl FrozenModelExecutor for RevokingExecutor {
    fn execute(
        &mut self,
        _request: &FrozenModelRequestV1,
    ) -> Result<BoundModelExecutionV1, String> {
        let mut denied = self
            .denied
            .lock()
            .map_err(|_| "lineage lock poisoned".to_string())?;
        *denied = Some(self.revoke);
        Ok(self.execution.clone())
    }
}

#[derive(Clone)]
struct SharedLineage {
    denied: Arc<Mutex<Option<Digest32>>>,
}

impl LineagePolicy for SharedLineage {
    fn allows(&mut self, value: Digest32) -> Result<bool, String> {
        let denied = self
            .denied
            .lock()
            .map_err(|_| "lineage lock poisoned".to_string())?;
        Ok(*denied != Some(value))
    }
}

fn prepare_canonical_operation_only(
    fixture: &Fixture,
    operation_name: &str,
    input: &NeuronTickInputV1,
    result: &RuntimeTickResultV1,
) -> crate::operation::PreparedRuntimeOperationV1 {
    let context = witness_context_digest(canonical_config_digest(), &scope());
    let mut operations = checked(crate::operation::FileRuntimeOperationJournal::open(
        fixture.file(operation_name),
        context,
        16,
    ));
    let prepared = checked(crate::operation::PreparedRuntimeOperationV1::new(
        input.tick_id.as_str().to_string(),
        input.logical_sequence,
        canonical_request_digest(input),
        canonical_required_lineage(input),
        result,
    ));
    checked(operations.prepare(prepared.clone()));
    prepared
}

fn commit_canonical_sparse_only(
    fixture: &Fixture,
    journal_name: &str,
    input: &NeuronTickInputV1,
) {
    let config = checked(bound_sparse_config(
        &config(),
        &native(),
        &selected_model_manifest(),
    ));
    let mut journal = checked(SparseJournal::open(
        fixture.file(journal_name),
        config,
        JournalScope {
            scope_digest: scope().scope_digest,
            objective_digest: scope().objective_digest,
        },
        16,
    ));
    let sparse_input = input.to_sparse_tick(&scope(), &model_execution());
    checked(journal.commit(input.checkpoint_digest, &sparse_input));
}

#[test]
fn canonical_prepared_without_state_is_aborted_then_reexecuted() {
    let fixture = Fixture::new();
    let tick = input(1, Digest32::ZERO);
    let expected = canonical_result(&tick, None);
    prepare_canonical_operation_only(&fixture, "operations-pre-state", &tick, &expected);

    let calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-pre-state"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-pre-state"),
        fixture.file("operations-pre-state"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&calls),
        },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    let result = checked(runtime.tick(
        tick,
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(calls.load(Ordering::Relaxed), 1);
    assert_eq!(result.tick_receipt.checkpoint_after, expected.tick_receipt.checkpoint_after);
}

#[test]
fn canonical_post_state_pre_terminal_recovery_returns_exact_result_without_reexecution() {
    let fixture = Fixture::new();
    let tick = input(1, Digest32::ZERO);
    let expected = canonical_result(&tick, None);
    prepare_canonical_operation_only(&fixture, "operations-post-state", &tick, &expected);
    commit_canonical_sparse_only(&fixture, "journal-post-state", &tick);

    let calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-post-state"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-post-state"),
        fixture.file("operations-post-state"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&calls),
        },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    let recovered = checked(runtime.tick(
        tick.clone(),
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ));
    let duplicate = checked(runtime.tick(
        tick,
        RuntimeTickObservationV1 {
            now_unix_micros: 3,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(recovered, expected);
    assert_eq!(duplicate, expected);
    assert_eq!(calls.load(Ordering::Relaxed), 0);
}

#[test]
fn canonical_post_terminal_pre_witness_recovery_advances_first_anchor_and_returns_exact_result() {
    let fixture = Fixture::new();
    let tick = input(1, Digest32::ZERO);
    let expected = canonical_result(&tick, None);
    let prepared =
        prepare_canonical_operation_only(&fixture, "operations-post-terminal", &tick, &expected);
    commit_canonical_sparse_only(&fixture, "journal-post-terminal", &tick);
    let context = witness_context_digest(canonical_config_digest(), &scope());
    let mut operations = checked(crate::operation::FileRuntimeOperationJournal::open(
        fixture.file("operations-post-terminal"),
        context,
        16,
    ));
    checked(operations.mark_committed(
        &prepared.operation_id,
        prepared.request_digest,
        prepared.checkpoint_after,
        prepared.result_digest,
    ));
    drop(operations);

    let calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-post-terminal"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-post-terminal"),
        fixture.file("operations-post-terminal"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&calls),
        },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    let recovered = checked(runtime.tick(
        tick,
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(recovered, expected);
    assert_eq!(calls.load(Ordering::Relaxed), 0);
}

#[test]
fn canonical_ack_loss_reopen_replays_exact_durable_result_without_model_reexecution() {
    let fixture = Fixture::new();
    let calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-ack-loss"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-ack-loss"),
        fixture.file("operations-ack-loss"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&calls),
        },
        FailOnceWitness {
            inner: witness,
            fail_sequence: 1,
        },
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    let tick = input(1, Digest32::ZERO);
    let checkpoint = match runtime.tick(
        tick.clone(),
        RuntimeTickObservationV1 {
            now_unix_micros: 2,
            queue_age_micros: 0,
        },
    ) {
        Err(RuntimeError::WitnessIndeterminate(checkpoint)) => checkpoint,
        other => panic!("expected post-terminal witness uncertainty: {other:?}"),
    };
    assert_eq!(calls.load(Ordering::Relaxed), 1);
    drop(runtime);

    let reopened_calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-ack-loss"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut reopened = checked(NeuronRuntimeHost::open(
        fixture.file("journal-ack-loss"),
        fixture.file("operations-ack-loss"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&reopened_calls),
        },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        3,
    ));
    let first = checked(reopened.tick(
        tick.clone(),
        RuntimeTickObservationV1 {
            now_unix_micros: 4,
            queue_age_micros: 0,
        },
    ));
    let second = checked(reopened.tick(
        tick,
        RuntimeTickObservationV1 {
            now_unix_micros: 5,
            queue_age_micros: 0,
        },
    ));
    assert_eq!(first, second);
    assert_eq!(first.tick_receipt.checkpoint_after, checkpoint);
    assert_eq!(reopened_calls.load(Ordering::Relaxed), 0);
}

#[test]
fn canonical_selected_model_manifest_drift_rejects_before_state_commit() {
    let fixture = Fixture::new();
    let mut drifted = model_execution();
    drifted.runtime_receipt.tokenizer_digest = digest("other-tokenizer");
    drifted.output_digest = checked(drifted.calculate_output_digest());
    let witness = checked(open_file_witness(
        fixture.file("witness-model-drift"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-model-drift"),
        fixture.file("operations-model-drift"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        Executor { execution: drifted },
        witness,
        Lineage { denied: None },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    assert!(matches!(
        runtime.tick(
            input(1, Digest32::ZERO),
            RuntimeTickObservationV1 {
                now_unix_micros: 2,
                queue_age_micros: 0,
            },
        ),
        Err(RuntimeError::Protocol(ProtocolError::InvalidModelExecution(
            "selected model manifest drift"
        )))
    ));
    assert!(checked(runtime.current_checkpoint()).is_none());
}

#[test]
fn canonical_tick_time_revocation_blocks_calibration_support_before_model_execution() {
    let fixture = Fixture::new();
    let denied = Arc::new(Mutex::new(None));
    let calls = Arc::new(AtomicU64::new(0));
    let witness = checked(open_file_witness(
        fixture.file("witness-tick-revocation"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-tick-revocation"),
        fixture.file("operations-tick-revocation"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        CountingExecutor {
            execution: model_execution(),
            calls: Arc::clone(&calls),
        },
        witness,
        SharedLineage {
            denied: Arc::clone(&denied),
        },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    ));
    {
        let mut value = checked(denied.lock());
        *value = Some(canonical_calibration_artifact().support_digest);
    }
    assert_eq!(
        runtime.tick(
            input(1, Digest32::ZERO),
            RuntimeTickObservationV1 {
                now_unix_micros: 2,
                queue_age_micros: 0,
            },
        ),
        Err(RuntimeError::RevokedLineage)
    );
    assert_eq!(calls.load(Ordering::Relaxed), 0);
    assert!(checked(runtime.current_checkpoint()).is_none());
}

#[test]
fn canonical_recovery_rechecks_revocation_before_advancing_witness() {
    let fixture = Fixture::new();
    let tick = input(1, Digest32::ZERO);
    let expected = canonical_result(&tick, None);
    let prepared =
        prepare_canonical_operation_only(&fixture, "operations-revoke-recovery", &tick, &expected);
    commit_canonical_sparse_only(&fixture, "journal-revoke-recovery", &tick);
    let context = witness_context_digest(canonical_config_digest(), &scope());
    let mut operations = checked(crate::operation::FileRuntimeOperationJournal::open(
        fixture.file("operations-revoke-recovery"),
        context,
        16,
    ));
    checked(operations.mark_committed(
        &prepared.operation_id,
        prepared.request_digest,
        prepared.checkpoint_after,
        prepared.result_digest,
    ));
    drop(operations);

    let denied = Arc::new(Mutex::new(Some(
        canonical_calibration_artifact().support_digest,
    )));
    let witness = checked(open_file_witness(
        fixture.file("witness-revoke-recovery"),
        canonical_config_digest(),
        &scope(),
    ));
    let result = NeuronRuntimeHost::open(
        fixture.file("journal-revoke-recovery"),
        fixture.file("operations-revoke-recovery"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        Executor {
            execution: model_execution(),
        },
        witness,
        SharedLineage { denied },
        calibration_policy(),
        Some(canonical_calibration_artifact()),
        1,
    );
    assert!(matches!(result, Err(RuntimeError::RevokedLineage)));

    let witness = checked(open_file_witness(
        fixture.file("witness-revoke-recovery"),
        canonical_config_digest(),
        &scope(),
    ));
    assert_eq!(checked(witness.current_anchor()), None);
}


#[test]
fn canonical_post_model_io_revocation_rejects_before_prepare_or_state_commit() {
    let fixture = Fixture::new();
    let denied = Arc::new(Mutex::new(None));
    let calibration = canonical_calibration_artifact();
    let witness = checked(open_file_witness(
        fixture.file("witness-post-io-revocation"),
        canonical_config_digest(),
        &scope(),
    ));
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("journal-post-io-revocation"),
        fixture.file("operations-post-io-revocation"),
        config(),
        native(),
        selected_model_manifest(),
        scope(),
        16,
        RevokingExecutor {
            execution: model_execution(),
            denied: Arc::clone(&denied),
            revoke: calibration.support_digest,
        },
        witness,
        SharedLineage { denied },
        calibration_policy(),
        Some(calibration),
        1,
    ));
    assert_eq!(
        runtime.tick(
            input(1, Digest32::ZERO),
            RuntimeTickObservationV1 {
                now_unix_micros: 2,
                queue_age_micros: 0,
            },
        ),
        Err(RuntimeError::RevokedLineage)
    );
    assert!(checked(runtime.current_checkpoint()).is_none());

    let context = witness_context_digest(canonical_config_digest(), &scope());
    let operations = checked(crate::operation::FileRuntimeOperationJournal::open(
        fixture.file("operations-post-io-revocation"),
        context,
        16,
    ));
    assert!(operations.record("tick.1").is_none());
}
