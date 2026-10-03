#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use codex_hepta_neuron::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
type TestResult = Result<(), Box<dyn std::error::Error>>;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn baseline() -> Result<NeuronGenerationMaterialV2, Box<dyn std::error::Error>> {
    let generation = Generation::new(2)?;
    let native = SparseConfig {
        model_digest: digest("fixed heads"),
        normalization_digest: digest("normalization"),
        generation,
        width: 10,
        top_k: 1,
        temporal_decay_q24: 1 << 23,
        inhibition_gain_q24: 0,
        inhibition: vec![InhibitoryEdge {
            source: 1,
            target: 2,
            weight_q24: 1 << 20,
        }],
        activity_decay_q24: 1 << 23,
        target_activity_q24: 1 << 20,
        threshold_rate_q24: 1 << 10,
        threshold_min_q24: 0,
        threshold_max_q24: 1 << 24,
        eligibility_decay_q24: 1 << 23,
    };
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id("actual.full.cpu"),
        generation,
        model_id: id("original.model"),
        model_manifest_digest: digest("original manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: 2,
        state_width: 10,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("independent E calibration"),
            ood_artifact_digest: digest("independent E OOD"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            zero_confidence_error_q24: 1 << 24,
            maximum_in_domain_error_q24: 1 << 24,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 100,
            measured_ece_ppm: 7,
            maximum_ece_ppm: 100_000,
            measured_false_acceptance_ppm: 9,
            maximum_false_acceptance_ppm: 100_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 1_000_000,
        },
    };
    let body = NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body manifest"),
        body_generation: generation,
        base_bundle_digest: digest("base bundle"),
        organ_id: id("neuron.organ"),
        organ_bundle_digest: digest("organ"),
        cell_slot_id: Some(id("cell.slot")),
        cell_bundle_digest: Some(digest("cell")),
        effective_parameter_digest: runtime.execution_profile_digest_v1()?,
        source_revision_digest: digest("immutable source"),
    };
    let scope = JournalScope {
        scope_digest: digest("original subject"),
        objective_digest: digest("actual training objective"),
    };
    let runtime_config_digest = runtime.semantic_digest()?;
    let body_bundle_digest = body.semantic_digest()?;
    Ok(NeuronGenerationMaterialV2 {
        model_manifest: "/protected/model.json".into(),
        model_manifest_digest: runtime.model_manifest_digest,
        generation_store: "/private/current/generation".into(),
        runtime_index: "/private/current/index".into(),
        witness: "/private/current/witness".into(),
        native,
        scope,
        runtime,
        body,
        store_context: NeuronGenerationStoreContextV2 {
            generation,
            scope,
            runtime_config_digest,
            body_bundle_digest,
            max_records: 16,
            max_pending_witness: 16,
            max_checkpoint_bytes: 256 * 1024,
            max_full_receipt_bytes: 256 * 1024,
            max_file_bytes: 8 * 1024 * 1024,
            max_startup_replay_bytes: 8 * 1024 * 1024,
        },
        index_context: NeuronRuntimeIndexContextV2 {
            generation,
            scope,
            runtime_config_digest,
            body_bundle_digest,
            max_records: 16,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        },
        witness_context: NeuronWitnessContextV2 {
            generation,
            scope,
            key_epoch: 3,
            deletion_epoch: 5,
            max_records: 16,
        },
    })
}

fn inputs(baseline: &NeuronGenerationMaterialV2) -> TestResultInputs {
    let layer = id("neuron.sparse.rates.q24.v1");
    let parameter = id("temporal_decay_q24");
    let window = ProposalWindowV2 {
        window_id: id("actual.window"),
        window_digest: digest("actual window"),
    };
    let profile = ParameterGeneratorProfileV3 {
        selected_artifact_digest: baseline.native.model_digest,
        window: window.clone(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: layer.clone(),
            baseline_squared_l2_raw_q64: 1 << 64,
        }],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("original.policy"),
            digest("allowed grammar"),
            baseline.native.model_digest,
            window.clone(),
            vec![ParameterMutationRuleV1 {
                layer_id: layer.clone(),
                parameter_id: parameter.clone(),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-1 << 20),
                maximum_delta: FixedQ32::from_raw(1 << 20),
            }],
        )?,
        update_scales: vec![FixedQ32::ONE],
        signals: vec![ParameterPlasticitySignalV3 {
            layer_id: layer,
            parameter_id: parameter,
            eligibility: FixedQ32::ONE,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(1 << 20),
            lower_bound: FixedQ32::from_raw(-1 << 20),
            upper_bound: FixedQ32::from_raw(1 << 20),
            evidence_digest: digest("actual eligibility"),
        }],
    };
    let generated = generate_parameter_candidates_v3(profile)?;
    let admission = PlasticityAdmissionEvidenceV1 {
        baseline_id: id("separate.artifact.registry.model"),
        objective_digest: baseline.scope.objective_digest,
        selected_artifact_digest: baseline.native.model_digest,
        artifact_registry_binding: digest("actual registry"),
        artifact_registry_head_digest: digest("current head"),
        qualification_evidence_head_digest: digest("actual qualification"),
        owner_evidence_set_digest: digest("actual original owner facts"),
        window,
        baseline_generation: baseline.native.generation,
        candidate_generation: baseline.native.generation.next()?,
        dataset_digest: digest("actual dataset"),
        update_rule_digest: digest("actual update"),
        modulator_digest: digest("modulator"),
        modulator_broadcast_digest: digest("actual broadcast"),
        eligibility_digest: digest("actual eligibility"),
        generator_digest: generated.generator_digest,
    };
    Ok((generated, admission))
}
type TestResultInputs = Result<
    (
        GeneratedParameterCandidateSetV3,
        PlasticityAdmissionEvidenceV1,
    ),
    Box<dyn std::error::Error>,
>;
fn prospective(
    baseline: &NeuronGenerationMaterialV2,
    native: SparseConfig,
) -> Result<NeuronGenerationMaterialV2, Box<dyn std::error::Error>> {
    let mut plan = baseline.clone();
    let generation = native.generation;
    plan.runtime.config_id = id("round.original.prospective");
    plan.native = native;
    plan.runtime.generation = generation;
    plan.runtime.native_config_digest = plan.native.digest()?;
    plan.runtime.calibration.generation = generation;
    plan.body.body_generation = generation;
    plan.store_context.generation = generation;
    plan.index_context.generation = generation;
    plan.witness_context.generation = generation;
    plan.generation_store = "/private/round/generation".into();
    plan.runtime_index = "/private/round/index".into();
    plan.witness = "/private/round/witness".into();
    finalize_parameter_pre_registration_material_v1(&plan, 17, 19)
}
#[test]
fn actual_sparse_successor_and_exact_rollback_freeze_fresh_non_circular_calibration() -> TestResult
{
    let baseline = baseline()?;
    let (generated, admission) = inputs(&baseline)?;
    let candidate = generated
        .candidates
        .iter()
        .find(|c| c.kind == ParameterCandidateKindV2::Update)
        .ok_or("update")?;
    let native = apply_sparse_parameter_deltas_v1(
        &baseline.native,
        admission.candidate_generation,
        &candidate.parameter_deltas,
    )?;
    let plan = prospective(&baseline, native)?;
    validate_parameter_pre_registration_material_v1(
        &baseline,
        &plan,
        &generated,
        &admission,
        &candidate.candidate_id,
        ParameterPreRegistrationPurposeV1::Candidate,
    )?;
    assert_ne!(
        plan.runtime.calibration.calibration_artifact_digest,
        baseline.runtime.calibration.calibration_artifact_digest
    );
    assert_eq!(
        plan.runtime.calibration.calibration_artifact_digest,
        Digest32::of_bytes(&plan.runtime.calibration_evidence_payload_v1()?)
    );
    assert_eq!(
        plan.runtime.calibration.ood_artifact_digest,
        Digest32::of_bytes(&plan.runtime.ood_evidence_payload_v1()?)
    );
    assert_ne!(
        plan.runtime.calibration.calibration_artifact_digest,
        plan.runtime.calibration.ood_artifact_digest
    );
    let bytes = encode_neuron_generation_material_v2(&plan)?;
    assert_eq!(
        encode_neuron_generation_material_v2(&decode_neuron_generation_material_v2(&bytes)?)?,
        bytes
    );
    let mut original = baseline.native.clone();
    original.generation = admission.candidate_generation.next()?;
    let rollback = prospective(&baseline, original)?;
    validate_parameter_pre_registration_material_v1(
        &baseline,
        &rollback,
        &generated,
        &admission,
        &candidate.candidate_id,
        ParameterPreRegistrationPurposeV1::ExactRollback,
    )?;
    assert!(
        validate_parameter_pre_registration_material_v1(
            &baseline,
            &rollback,
            &generated,
            &admission,
            &candidate.candidate_id,
            ParameterPreRegistrationPurposeV1::Candidate
        )
        .is_err()
    );
    Ok(())
}
#[test]
fn fully_valid_material_cannot_change_delta_numeric_head_policy_or_reuse_current_stores()
-> TestResult {
    let baseline = baseline()?;
    let (generated, admission) = inputs(&baseline)?;
    let candidate = generated
        .candidates
        .iter()
        .find(|c| c.kind == ParameterCandidateKindV2::Update)
        .ok_or("update")?;
    let native = apply_sparse_parameter_deltas_v1(
        &baseline.native,
        admission.candidate_generation,
        &candidate.parameter_deltas,
    )?;
    let valid = prospective(&baseline, native)?;
    let check = |plan: &NeuronGenerationMaterialV2| {
        validate_parameter_pre_registration_material_v1(
            &baseline,
            plan,
            &generated,
            &admission,
            &candidate.candidate_id,
            ParameterPreRegistrationPurposeV1::Candidate,
        )
    };
    let mut wrong_delta = valid.native.clone();
    wrong_delta.temporal_decay_q24 += 1;
    assert!(check(&prospective(&baseline, wrong_delta)?).is_err());
    let mut wrong_head = valid.clone();
    wrong_head.runtime.weights_digest = digest("different numeric weights");
    assert!(
        check(&finalize_parameter_pre_registration_material_v1(
            &wrong_head,
            17,
            19
        )?)
        .is_err()
    );
    let mut weakened = valid.clone();
    weakened.runtime.calibration.maximum_ece_ppm += 1;
    assert!(
        check(&finalize_parameter_pre_registration_material_v1(
            &weakened, 17, 19
        )?)
        .is_err()
    );
    let mut reused = valid;
    reused.generation_store = baseline.generation_store.clone();
    validate_neuron_generation_material_v2(&reused)?;
    assert!(check(&reused).is_err());
    assert!(finalize_parameter_pre_registration_material_v1(&reused, 1_000_000, 19).is_err());
    Ok(())
}
