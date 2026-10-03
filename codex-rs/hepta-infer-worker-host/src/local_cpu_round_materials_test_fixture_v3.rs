use super::*;
use codex_hepta_agent_components::intelligence::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::plasticity::*;
use codex_hepta_neuron::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("original identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) struct Fixture {
    pub baseline: CpuNeuronGenerationPlanV1,
    pub canonical: CanonicalIterationEnvelopeV1,
    pub execution: IterationEnvelopeV1,
    pub request: ParameterPlasticityProductRequestV1,
    pub blueprint: CpuNeuronRoundMaterialBlueprintV3,
}
fn baseline() -> Result<NeuronGenerationMaterialV2, Box<dyn std::error::Error>> {
    let generation = Generation::new(1)?;
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
    let scope = NeuronTickInputV1::journal_scope_for_subject(
        &id("actual.agent"),
        digest("actual training objective"),
    )?;
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

impl Fixture {
    pub fn new(root: PathBuf) -> Result<Self, Box<dyn std::error::Error>> {
        let baseline = baseline()?;
        let layer = id(validation::PARAMETER_LAYER);
        let parameter = id("threshold_rate_q24");
        let selected = baseline.runtime.model_manifest_digest;
        let window = ProposalWindowV2 {
            window_id: id("original.training.window"),
            window_digest: digest("actual training window"),
        };
        let profile = ParameterGeneratorProfileV3 {
            selected_artifact_digest: selected,
            window: window.clone(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: layer.clone(),
                baseline_squared_l2_raw_q64: validation::norm_denominator(&baseline.native)?,
            }],
            mutation_policy: build_parameter_mutation_policy_v1(
                id("original.parameter.policy"),
                digest("original mutation grammar"),
                selected,
                window.clone(),
                vec![ParameterMutationRuleV1 {
                    parameter_id: parameter.clone(),
                    layer_id: layer.clone(),
                    surface: ParameterMutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-512),
                    maximum_delta: FixedQ32::from_raw(512),
                }],
            )?,
            update_scales: vec![FixedQ32::ONE],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: layer,
                parameter_id: parameter,
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::from_raw(512),
                lower_bound: FixedQ32::from_raw(-512),
                upper_bound: FixedQ32::from_raw(512),
                evidence_digest: digest("original signal source"),
            }],
        };
        let generated = generate_parameter_candidates_v3(profile.clone())?;
        let admission = PlasticityAdmissionEvidenceV1 {
            baseline_id: id("original.selected.baseline"),
            objective_digest: baseline.scope.objective_digest,
            selected_artifact_digest: selected,
            artifact_registry_binding: digest("original registry"),
            artifact_registry_head_digest: digest("original head"),
            qualification_evidence_head_digest: digest("original qualification head"),
            owner_evidence_set_digest: digest("original seven owner evidence"),
            window,
            baseline_generation: baseline.runtime.generation,
            candidate_generation: baseline.runtime.generation.next()?,
            dataset_digest: digest("original data"),
            update_rule_digest: digest("original rule"),
            modulator_digest: digest("original modulator"),
            modulator_broadcast_digest: digest("original broadcast"),
            eligibility_digest: digest("original eligibility"),
            generator_digest: generated.generator_digest,
        };
        // These unverified wire vectors exercise only pure material derivation. The
        // original signed final-use owner would reject them; no fixture grants access.
        let evidence = |role| SignedLearningEvidenceV1 {
            evidence_id: id("unverified.wire.vector"),
            principal_id: id("original.role"),
            role,
            trust_digest: digest("trust"),
            scope_digest: baseline.scope.scope_digest,
            objective_digest: baseline.scope.objective_digest,
            authority_epoch: 1,
            issued_at: 1000,
            expires_at: 100_000,
            payload_digest: digest("payload"),
            signature: [0x39; 64],
        };
        let request = ParameterPlasticityProductRequestV1 {
            proposal_id: id("original.parameter.proposal"),
            generator_profile: profile,
            generated,
            generator_attestation: evidence(LearningEvidenceRoleV1::Generator),
            admission,
            admission_attestation: evidence(LearningEvidenceRoleV1::Observer),
            no_change_attestation: None,
            evaluations: vec![],
            expected_registry_predecessor: Digest32::ZERO,
        };
        let canonical = CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(
            &serde_json::json!({
             "envelopeId":"original.canonical.window","baseCommit":"1".repeat(40),"baseTree":"2".repeat(40),"objectiveDigest":baseline.scope.objective_digest.to_string(),"grammarDigest":digest("original grammar").to_string(),
             "allowedPaths":[policy::CPU_PARAMETER_OPERAND_V1],"deniedAuthorities":["runtime","production_writer","model_invocation","provider_dispatch","external_effect","selection","promotion","release"],
             "maximumFiles":1,"maximumBytes":4096,"maximumCandidates":8,"wallTimeMicros":1_000_000,
             "computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":134_217_728,"maximumProcesses":1},"mandatoryChecks":policy::CPU_PARAMETER_CHECKS_V1,"expiresUnixMs":1_000_000
            }),
        )?)?;
        let execution = IterationEnvelopeV1 {
            envelope_id: id(canonical.policy().envelope_id),
            base_commit: Digest32::of_bytes(canonical.policy().base_commit.as_bytes()),
            base_tree: Digest32::of_bytes(canonical.policy().base_tree.as_bytes()),
            objective_digest: baseline.scope.objective_digest,
            grammar_digest: digest("original grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 4096,
            maximum_candidates: u16::try_from(request.generated.candidates.len())?,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 1000,
        };
        let features = vec![1 << 22, 1 << 20];
        let tick = NeuronTickInputV1 {
            tick_id: id("original.root.canary.input"),
            subject_id: id("actual.agent"),
            logical_sequence: 1,
            monotonic_time_micros: 1000,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: canonical_feature_vector_digest_v1(&features),
            feature_vector_q24: features,
            objective_digest: baseline.scope.objective_digest,
            ndu_snapshot_digest: digest("original protected NDU input"),
            body_generation: Some(1),
            modulator_digest: None,
        };
        let port = CanonicalPortInputV1 {
            run_id: tick.tick_id.clone(),
            snapshot_digest: digest("original port snapshot"),
            objective_digest: tick.objective_digest,
            candidate_set_digest: request.generated.generator_digest,
            predecessor_digest: tick.ndu_snapshot_digest,
            budget_micros: 5000,
            stage: CanonicalStageV1::NeuralSignalCollected,
        };
        Ok(Self {
            baseline,
            canonical,
            execution,
            request,
            blueprint: CpuNeuronRoundMaterialBlueprintV3 {
                generation_root: root,
                test_plan_digest: digest("original test plan"),
                canary_tick: tick,
                canary_port: port,
            },
        })
    }
    pub fn round(
        &self,
        goal: &str,
        ordinal: u64,
    ) -> Result<AgentdSelfIterationRoundV1, Box<dyn std::error::Error>> {
        Ok(serde_json::from_value(
            serde_json::json!({"goal":goal,"ordinal":ordinal,"candidate_admissions":self.execution.maximum_candidates,"policy":self.canonical.digest().to_string(),"execution":self_iteration_envelope_digest_v1(&self.execution).to_string(),"admitted_at_ms":1000,"deadline_ms":100_000}),
        )?)
    }
    pub fn derive(
        &self,
        round: &AgentdSelfIterationRoundV1,
    ) -> Result<CpuNeuronRoundMaterialsV3, AgentdError> {
        derive_cpu_neuron_round_materials_v3(
            round,
            &self.canonical,
            &self.execution,
            &self.baseline,
            &self.request,
            &self.blueprint,
        )
    }
}
