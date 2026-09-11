use codex_hepta_intelligence::CoherentLaneFSnapshotV1;
use codex_hepta_intelligence::LaneFBudgetV1;
use codex_hepta_intelligence::LaneFRunRequestV1;
use codex_hepta_intelligence::LaneFShadowPortsV1;
use codex_hepta_intelligence::LaneFStageV1;
use codex_hepta_intelligence::PipelineDispositionV1;
use codex_hepta_intelligence::PortDecisionV1;
use codex_hepta_intelligence::PortFailureV1;
use codex_hepta_intelligence::PortInputV1;
use codex_hepta_intelligence::PortReceiptV1;
use codex_hepta_intelligence::run_shadow_pipeline;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::decide_calibrated;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterCandidateRequestV2;
use codex_hepta_plasticity::ParameterDeltaV2;
use codex_hepta_plasticity::ParameterProposalRequestV2;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::propose_v2;
use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_prompt_optimizer::local_shadow::LOCAL_NO_INTERVENTION_ID;
use codex_hepta_prompt_optimizer::local_shadow::LocalNoInterventionBaseline;
use codex_hepta_prompt_optimizer::local_shadow::LocalShadowInput;
use codex_hepta_prompt_optimizer::local_shadow::calculate_local_shadow;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const Q24: i64 = 1 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

#[derive(Clone)]
struct NativeVerticalPorts {
    objective: Digest32,
    legal_set: Digest32,
    neural: Digest32,
    prompt: Digest32,
    intuition: Digest32,
    context: Digest32,
    dispatch: Digest32,
    learning: Digest32,
}

impl NativeVerticalPorts {
    fn receipt(
        input: &PortInputV1,
        producer: &str,
        output_digest: Digest32,
        decision: PortDecisionV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        Ok(PortReceiptV1 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl LaneFShadowPortsV1 for NativeVerticalPorts {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "objective.compiler",
            self.objective,
            PortDecisionV1::Continue,
        )
    }

    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "intelligence.control",
            self.legal_set,
            PortDecisionV1::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "neuron.runtime",
            self.neural,
            PortDecisionV1::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "prompt.optimizer",
            self.prompt,
            PortDecisionV1::Continue,
        )
    }

    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "intuition.policy",
            self.intuition,
            PortDecisionV1::Continue,
        )
    }

    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "context.compiler",
            self.context,
            PortDecisionV1::Continue,
        )
    }

    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "runtime.agentd",
            self.dispatch,
            PortDecisionV1::Continue,
        )
    }

    fn record_learning(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        Self::receipt(
            input,
            "learning.ledger",
            self.learning,
            PortDecisionV1::Continue,
        )
    }
}

#[test]
fn lane_f_native_shadow_vertical_closes_without_effect_authority() {
    let model_digest = digest("model-artifact");
    let objective_digest = digest("objective");
    let scope_digest = digest("scope");
    let body_digest = digest("body");
    let ndu_digest = digest("ndu");

    let neuron_config = SparseConfig {
        model_digest,
        normalization_digest: digest("normalization"),
        generation: generation(7),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: Q24 / 2,
        target_activity_q24: Q24 / 5,
        threshold_rate_q24: Q24 / 10,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let neuron_tick = SparseTick {
        scope_digest,
        objective_digest,
        ndu_digest,
        body_digest,
        input_digest: digest("approved-input"),
        sequence: 1,
        monotonic_micros: 1,
        drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let (neuron_checkpoint, neuron_receipt) = sparse_tick(&neuron_config, &neuron_tick, None)
        .unwrap_or_else(|error| panic!("neuron tick must pass: {error:?}"));
    assert!(neuron_receipt.requires_calibration);
    assert!(!neuron_receipt.authority.grants_any());

    let registry_digest = digest("prompt-registry");
    let prompt_candidate = PromptCandidate {
        candidate_id: id("candidate:prompt:1"),
        factor_id: id("factor:1"),
        realization_id: id("realization:1"),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(100),
        cost: 8,
        registry_digest,
        support_digest: digest("prompt-support"),
    };
    let prompt_proposal = calculate_local_shadow(LocalShadowInput {
        decision_id: id("prompt-decision:1"),
        objective_digest,
        state_digest: neuron_receipt.checkpoint_after,
        registry_snapshot_digest: registry_digest,
        token_budget: 64,
        maximum_selected_factors: 1,
        no_intervention: LocalNoInterventionBaseline {
            arm_id: id(LOCAL_NO_INTERVENTION_ID),
            registry_digest,
            support_reference_digest: digest("no-intervention-support"),
        },
        factor_candidates: vec![prompt_candidate],
        interaction_edges: Vec::new(),
        hard_constraints: Vec::new(),
    })
    .unwrap_or_else(|error| panic!("prompt shadow must pass: {error:?}"));
    assert_eq!(prompt_proposal.selections.len(), 1);
    assert!(!prompt_proposal.authority().grants_any());

    let action_candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("action:read-only-report"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(100),
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("action-support"),
    }];
    let candidate_set_digest = canonical_candidate_set_digest_v1(&action_candidates)
        .unwrap_or_else(|error| panic!("candidate set must digest: {error:?}"));
    let candidate_order_digest = canonical_candidate_order_digest_v1(&action_candidates)
        .unwrap_or_else(|error| panic!("candidate order must digest: {error:?}"));
    let policy_digest = digest("intuition-policy");
    let objective_class_digest = digest("objective-class");
    let intuition_receipt = decide_calibrated(CalibratedDecisionRequestV1 {
        decision_id: id("intuition-decision:1"),
        objective_digest,
        objective_class_digest,
        state_digest: neuron_receipt.checkpoint_after,
        policy_digest,
        policy_generation: 7,
        sequence: 1,
        minimum_confidence: probability(ProbabilityQ32::ONE.raw() / 2),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("candidate-completeness-receipt"),
            generator_digest: digest("candidate-generator"),
            grammar_digest: digest("candidate-grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest,
            canonical_order_digest: candidate_order_digest,
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration-artifact"),
            policy_digest,
            objective_class_digest,
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            measured_ece_ppm: 1_000,
            subgroup_audit_digest: digest("subgroup-audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood-artifact"),
            policy_digest,
            detector_digest: digest("ood-detector"),
            support_digest: digest("ood-support"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            maximum_in_domain_score: probability(ProbabilityQ32::ONE.raw() / 4),
            measured_false_acceptance_ppm: 100,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates: action_candidates,
    })
    .unwrap_or_else(|error| panic!("calibrated intuition must pass: {error:?}"));
    assert_eq!(
        intuition_receipt.disposition,
        CalibratedDispositionV1::Selected(id("action:read-only-report"))
    );
    assert!(!intuition_receipt.authority.grants_any());

    let selected_artifact = model_digest;
    let eligibility_digest = Digest32::of_bytes(
        &neuron_checkpoint
            .eligibility_q24()
            .iter()
            .flat_map(|value| value.to_be_bytes())
            .collect::<Vec<_>>(),
    );
    let plasticity_proposal = propose_v2(ParameterProposalRequestV2 {
        proposal_id: id("plasticity-proposal:1"),
        proposer_id: id("learning.plasticity"),
        evaluator_id: id("learning.eval"),
        selected_artifact_digest: selected_artifact,
        window: ProposalWindowV2 {
            window_id: id("window:1"),
            window_digest: digest("window-digest"),
        },
        baseline_generation: generation(7),
        candidate_generation: generation(8),
        dataset_digest: digest("dataset"),
        update_rule_digest: digest("three-factor-update"),
        modulator_digest: digest("modulator"),
        modulator_broadcast_digest: digest("modulator-broadcast"),
        eligibility_digest,
        evaluation_digest: digest("evaluation"),
        rollback_predecessor_digest: selected_artifact,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:local-head"),
            baseline_squared_l2_raw_q64: 1_000_000,
        }],
        candidates: vec![
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:no-change"),
                kind: ParameterCandidateKindV2::NoChange,
                parameter_deltas: Vec::new(),
            },
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:update"),
                kind: ParameterCandidateKindV2::Update,
                parameter_deltas: vec![ParameterDeltaV2 {
                    layer_id: id("layer:local-head"),
                    parameter_id: id("parameter:0"),
                    delta: FixedQ32::from_raw(2),
                    lower_bound: FixedQ32::from_raw(-10),
                    upper_bound: FixedQ32::from_raw(10),
                    evidence_digest: neuron_receipt.checkpoint_after,
                }],
            },
        ],
    })
    .unwrap_or_else(|error| panic!("plasticity proposal must pass: {error:?}"));
    assert!(!plasticity_proposal.authority.grants_any());

    let snapshot = CoherentLaneFSnapshotV1 {
        objective_revision: 1,
        authority_epoch: 1,
        body_generation: 7,
        model_artifact_digest: model_digest,
        ndu_artifact_digest: ndu_digest,
        neuron_checkpoint_digest: neuron_receipt.checkpoint_after,
        prompt_registry_generation: 1,
        learning_artifact_generation: 7,
        context_schema_revision: 1,
    };
    let context_digest = digest("compiled-context");
    let dispatch_digest = digest("read-only-dispatch-proposal");
    let mut ports = NativeVerticalPorts {
        objective: objective_digest,
        legal_set: candidate_set_digest,
        neural: neuron_receipt.checkpoint_after,
        prompt: prompt_proposal.proposal_digest,
        intuition: intuition_receipt.receipt_digest,
        context: context_digest,
        dispatch: dispatch_digest,
        learning: plasticity_proposal.proposal_digest,
    };
    let receipt = run_shadow_pipeline(
        LaneFRunRequestV1 {
            run_id: id("run:lane-f-native-shadow"),
            request_digest: digest("request"),
            snapshot,
            budget: LaneFBudgetV1 {
                total_micros: 8_000,
                objective_micros: 1_000,
                legal_set_micros: 1_000,
                neural_micros: 1_000,
                prompt_micros: 1_000,
                intuition_micros: 1_000,
                context_micros: 1_000,
                dispatch_micros: 1_000,
                ledger_micros: 1_000,
            },
        },
        &mut ports,
    )
    .unwrap_or_else(|error| panic!("Lane F shadow pipeline must pass: {error:?}"));

    assert_eq!(receipt.disposition, PipelineDispositionV1::DispatchProposed);
    assert_eq!(receipt.stages.len(), 8);
    assert_eq!(receipt.stages[2].stage, LaneFStageV1::NeuralSignalCollected);
    assert_eq!(
        receipt.stages[2].output_digest,
        neuron_receipt.checkpoint_after
    );
    assert_eq!(
        receipt.stages[3].output_digest,
        prompt_proposal.proposal_digest
    );
    assert_eq!(
        receipt.stages[4].output_digest,
        intuition_receipt.receipt_digest
    );
    assert_eq!(
        receipt.stages[7].output_digest,
        plasticity_proposal.proposal_digest
    );
    assert!(!receipt.trace_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

