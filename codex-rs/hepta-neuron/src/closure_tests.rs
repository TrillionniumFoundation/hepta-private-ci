use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

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
            checked(
                OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&path),
            );
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

    let mut changed = execution.clone();
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
        checked(runtime_profile_digest(&config, &native())),
        checked(execution.model_identity_digest()),
        config.generation,
        1,
        Q,
        Q / 10,
        200_000,
        0,
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
        config_digest,
        identity,
        generation(1),
        1,
        Q,
        Q / 10,
        200_000,
        0,
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
        config_digest,
        identity,
        generation(1),
        1,
        Q,
        Q / 10,
        200_000,
        0,
    ));
    assert!(!qualified.abstain);
    assert_eq!(qualified.confidence_ppm, 900_000);

    let ood = checked(apply_calibration(
        calibration_policy(),
        Some(&artifact),
        config_digest,
        identity,
        generation(1),
        1,
        Q,
        Q,
        200_000,
        0,
    ));
    assert!(ood.abstain);
    assert_eq!(
        ood.fallback_reason,
        Some(SignalFallbackReasonV1::OutOfDistribution)
    );
}

#[test]
fn plasticity_requires_explicit_parameter_group_broadcast_and_is_deterministic() {
    let history = vec![
        PlasticitySampleV1 {
            checkpoint_digest: digest("checkpoint.1"),
            eligibility_q24: vec![Q, Q / 2, 0, 0, 0],
            independent_modulator_q24: vec![Q / 2, Q / 4],
        },
        PlasticitySampleV1 {
            checkpoint_digest: digest("checkpoint.2"),
            eligibility_q24: vec![Q / 2, Q / 4, Q / 4, 0, 0],
            independent_modulator_q24: vec![Q / 4, Q / 2],
        },
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
    let first = checked(accumulate_plasticity(&history, &groups, &broadcast, trust));
    let mut shuffled = broadcast.clone();
    shuffled.reverse();
    assert_eq!(
        checked(accumulate_plasticity(&history, &groups, &shuffled, trust)),
        first
    );
    assert_eq!(first.sample_count, 2);
    assert!(!first.statistics_digest.is_zero());

    assert_eq!(
        accumulate_plasticity(&history, &groups, &broadcast[..1], trust),
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
        let mut witness = checked(FileRecoveryWitness::open(
            fixture.file("witness"),
            context,
        ));
        assert_eq!(checked(witness.current_anchor()), None);
        checked(witness.compare_and_store(None, anchor));
        assert_eq!(checked(witness.current_anchor()), Some(anchor));
    }
    let reopened = checked(FileRecoveryWitness::open(
        fixture.file("witness"),
        context,
    ));
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
    let mut runtime = checked(NeuronRuntimeHost::open(
        fixture.file("segment-1"),
        runtime_config.clone(),
        native(),
        runtime_scope.clone(),
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
    let reopened = checked(NeuronRuntimeHost::open_with_genesis(
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
    let mut runtime = checked(NeuronRuntimeHost::open(
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
    let mut reopened = checked(NeuronRuntimeHost::open(
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
    let mut runtime = checked(NeuronRuntimeHost::open(
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
    let mut runtime = checked(NeuronRuntimeHost::open(
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
    let result = NeuronRuntimeHost::open(
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
