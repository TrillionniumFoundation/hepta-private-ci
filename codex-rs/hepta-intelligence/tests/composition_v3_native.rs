use codex_hepta_context_compiler::{
    CompilationRequest, ContextItem, ContextRole, compile as compile_context,
};
use codex_hepta_intelligence::{
    CapabilityBindingV2, CapabilityNecessityV2, CapabilityRequirementV2,
    CapabilitySnapshotRequestV2, CapabilitySnapshotV2, CompositionBudgetV3,
    CompositionControlV3, CompositionDispositionV3, CompositionPortDecisionV3,
    CompositionPortFailureV3, CompositionPortInputV3, CompositionPortReceiptV3,
    CompositionPortsV3, CompositionRunRequestV3, CompositionStageV3,
    LegalActionCandidateSetRequestV1, LegalActionCandidateV1, build_legal_candidates,
    prepare_intelligence_run_v3,
};
use codex_hepta_intelligence_eval::{
    Direction as EvalDirection, Disposition as EvalDisposition, EvaluationRequest,
    MetricComparison, evaluate as evaluate_independently,
};
use codex_hepta_intuition::{
    AssignmentModeV1, CalibratedActionCandidateV1, CalibratedDecisionRequestV1,
    CalibratedDispositionV1, CalibrationArtifactV1, CandidateSetCompletenessBindingV1,
    OodArtifactV1, RiskClass, canonical_candidate_order_digest_v1,
    canonical_candidate_set_digest_v1, decide_calibrated,
};
use codex_hepta_ndu::{
    AxisDirection, AxisValue, ContributionSet, EvaluationDisposition as NduDisposition,
    FeasibilityPosture, RequiredOrganSet, ScalarizationProfile, UtilityContribution,
    UtilityProfile, evaluate_candidates,
};
use codex_hepta_neuron::{SparseConfig, SparseTick, sparse_tick};
use codex_hepta_objective::{
    ActionClass, CompileDisposition, ConfirmationPolicy, Constraint, ConstraintClass,
    ConstraintRelation, ObjectiveSourceEnvelope, SoftDirection, SoftPreference, SourceTrust,
    SuccessPredicate, PredicateTerminality, compile as compile_objective,
};
use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_prompt_optimizer::local_shadow::{
    LOCAL_NO_INTERVENTION_ID, LocalNoInterventionBaseline, LocalShadowInput,
    calculate_local_shadow,
};
use codex_hepta_types::{
    AuthorityPosture, Digest32, FixedQ32, Generation, ProbabilityQ32, Revision, StableId,
};

const Q24: i64 = 1 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn action(value: &str) -> ActionClass {
    ActionClass {
        id: id(value),
        confirmation: ConfirmationPolicy::NotRequired,
    }
}

fn objective_source() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        request_id: id("native-v3-objective"),
        principal_scope: id("principal:native-v3"),
        revision: revision(1),
        source_trust: SourceTrust::PrincipalStructured,
        source_digest: digest("objective-source"),
        schema_digest: digest("objective-schema"),
        constraints: vec![Constraint {
            id: id("latency-ceiling"),
            class: ConstraintClass::Task,
            axis: id("latency"),
            relation: ConstraintRelation::AtMost,
            bound: FixedQ32::from_raw(100_i64 << 32),
            evidence_source: id("native-v3-request"),
        }],
        success_predicates: vec![SuccessPredicate {
            id: id("answer-produced"),
            axis: id("answer-count"),
            relation: ConstraintRelation::AtLeast,
            bound: FixedQ32::ONE,
            evidence_source: id("native-v3-observer"),
            terminality: PredicateTerminality::Terminal,
        }],
        allowed_actions: vec![action("action:report")],
        forbidden_actions: Vec::new(),
        soft_preferences: vec![SoftPreference {
            dimension: id("quality"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
    }
}

fn utility_contribution(
    candidate: &str,
    objective_digest: Digest32,
    value: FixedQ32,
) -> UtilityContribution {
    UtilityContribution {
        candidate_id: id(candidate),
        organ_id: id("planner"),
        objective_digest,
        generation: generation(1),
        feasibility: FeasibilityPosture::Feasible,
        utility: vec![AxisValue {
            axis: id("quality"),
            value,
        }],
        risk: Vec::new(),
        resource: Vec::new(),
        uncertainty: vec![AxisValue {
            axis: id("quality"),
            value: FixedQ32::ZERO,
        }],
        support_digest: digest(&format!("utility:{candidate}")),
    }
}

#[derive(Clone)]
struct NativeFixtures {
    objective: ObjectiveSourceEnvelope,
    objective_digest: Digest32,
    ndu_set: ContributionSet,
    ndu_profile: UtilityProfile,
    ndu_scalarization: ScalarizationProfile,
    eval: EvaluationRequest,
    neuron_config: SparseConfig,
    neuron_tick: SparseTick,
    prompt: LocalShadowInput,
    intuition: CalibratedDecisionRequestV1,
    context: CompilationRequest,
}

impl NativeFixtures {
    fn new(snapshot_digest: Digest32, objective: ObjectiveSourceEnvelope) -> Self {
        let objective_receipt = compile_objective(objective.clone())
            .expect("objective input")
            .expect("objective conflict-free");
        assert_eq!(objective_receipt.disposition, CompileDisposition::Compiled);
        let objective_digest = objective_receipt.objective.semantic_digest;

        let ndu_set = ContributionSet {
            objective_digest,
            generation: generation(1),
            contributions: vec![
                utility_contribution("abstain", objective_digest, FixedQ32::ZERO),
                utility_contribution("action:report", objective_digest, FixedQ32::ONE),
            ],
        };
        let ndu_profile = UtilityProfile {
            profile_id: id("native-v3-utility"),
            dimensions: vec![(id("quality"), AxisDirection::Maximize)],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        };
        let ndu_scalarization = ScalarizationProfile {
            profile_id: id("native-v3-scalarization"),
            weights: vec![AxisValue {
                axis: id("quality"),
                value: FixedQ32::ONE,
            }],
        };
        let ndu_receipt = evaluate_candidates(
            ndu_set.clone(),
            ndu_profile.clone(),
            Some(ndu_scalarization.clone()),
        )
        .expect("NDU");
        assert_eq!(
            ndu_receipt.disposition,
            NduDisposition::ScalarizedRecommendation
        );

        let eval = EvaluationRequest {
            evaluation_id: id("native-v3-evaluation"),
            evaluator_id: id("learning.eval"),
            candidate_id: id("action:report"),
            candidate_producer_id: id("intelligence.control"),
            baseline_id: id("abstain"),
            objective_digest,
            comparisons: vec![MetricComparison {
                metric_id: id("quality"),
                direction: EvalDirection::Maximize,
                candidate: FixedQ32::ONE,
                baseline: FixedQ32::ZERO,
                minimum_delta: FixedQ32::ZERO,
                hard: true,
                support_digest: ndu_receipt.evaluation_digest,
            }],
        };
        let eval_receipt = evaluate_independently(eval.clone()).expect("evaluation");
        assert_eq!(
            eval_receipt.disposition,
            EvalDisposition::EligibleForFurtherReview
        );

        let model_digest = digest("native-v3-model");
        let neuron_config = SparseConfig {
            model_digest,
            normalization_digest: digest("native-v3-normalization"),
            generation: generation(1),
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
            scope_digest: digest("native-v3-scope"),
            objective_digest,
            ndu_digest: ndu_receipt.evaluation_digest,
            body_digest: digest("native-v3-body"),
            input_digest: eval_receipt.evidence_digest,
            sequence: 1,
            monotonic_micros: 1,
            drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
            prediction_q24: vec![0; 5],
        };
        let (_, neuron_receipt) =
            sparse_tick(&neuron_config, &neuron_tick, None).expect("neuron");
        assert!(neuron_receipt.requires_calibration);

        let registry_digest = digest("native-v3-prompt-registry");
        let prompt = LocalShadowInput {
            decision_id: id("native-v3-prompt-decision"),
            objective_digest,
            state_digest: neuron_receipt.checkpoint_after,
            registry_snapshot_digest: registry_digest,
            token_budget: 64,
            maximum_selected_factors: 1,
            no_intervention: LocalNoInterventionBaseline {
                arm_id: id(LOCAL_NO_INTERVENTION_ID),
                registry_digest,
                support_reference_digest: digest("native-v3-no-intervention"),
            },
            factor_candidates: vec![PromptCandidate {
                candidate_id: id("native-v3-prompt-candidate"),
                factor_id: id("native-v3-prompt-factor"),
                realization_id: id("native-v3-prompt-realization"),
                admitted: true,
                legal: true,
                expected_gain: FixedQ32::ONE,
                cost: 8,
                registry_digest,
                support_digest: eval_receipt.evidence_digest,
            }],
            interaction_edges: Vec::new(),
            hard_constraints: Vec::new(),
        };
        let prompt_receipt = calculate_local_shadow(prompt.clone()).expect("prompt");

        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("action:report"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: prompt_receipt.proposal_digest,
        }];
        let candidate_set_digest =
            canonical_candidate_set_digest_v1(&candidates).expect("candidate set");
        let canonical_order_digest =
            canonical_candidate_order_digest_v1(&candidates).expect("candidate order");
        let policy_digest = digest("native-v3-intuition-policy");
        let objective_class_digest = digest("native-v3-objective-class");
        let intuition = CalibratedDecisionRequestV1 {
            decision_id: id("native-v3-intuition"),
            objective_digest,
            objective_class_digest,
            state_digest: neuron_receipt.checkpoint_after,
            policy_digest,
            policy_generation: 1,
            sequence: 1,
            minimum_confidence: probability(ProbabilityQ32::ONE.raw() / 2),
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: digest("native-v3-completeness"),
                generator_digest: digest("native-v3-generator"),
                grammar_digest: digest("native-v3-grammar"),
                hard_filter_digest: digest("native-v3-hard-filter"),
                truncation_digest: digest("native-v3-truncation"),
                candidate_set_digest,
                canonical_order_digest,
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: digest("native-v3-calibration"),
                policy_digest,
                objective_class_digest,
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 10,
                measured_ece_ppm: 1_000,
                subgroup_audit_digest: digest("native-v3-subgroup"),
            },
            ood: OodArtifactV1 {
                artifact_digest: digest("native-v3-ood"),
                policy_digest,
                detector_digest: digest("native-v3-ood-detector"),
                support_digest: eval_receipt.evidence_digest,
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 10,
                maximum_in_domain_score: probability(ProbabilityQ32::ONE.raw() / 4),
                measured_false_acceptance_ppm: 100,
            },
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        let intuition_receipt = decide_calibrated(intuition.clone()).expect("intuition");
        assert!(matches!(
            intuition_receipt.disposition,
            CalibratedDispositionV1::Selected(_)
        ));

        let context = CompilationRequest {
            compilation_id: id("native-v3-context"),
            run_snapshot_digest: snapshot_digest,
            objective_digest,
            token_budget: 16,
            items: vec![
                ContextItem {
                    item_id: id("native-v3-instruction"),
                    role: ContextRole::TrustedInstruction,
                    content_digest: digest("native-v3-instruction-content"),
                    source_digest: digest("native-v3-instruction-source"),
                    token_count: 2,
                    contains_secret: false,
                },
                ContextItem {
                    item_id: id("native-v3-intuition-evidence"),
                    role: ContextRole::UntrustedEvidence,
                    content_digest: intuition_receipt.receipt_digest,
                    source_digest: eval_receipt.evidence_digest,
                    token_count: 2,
                    contains_secret: false,
                },
            ],
        };
        let context_receipt = compile_context(context.clone()).expect("context");
        assert!(!context_receipt.context_digest.is_zero());

        Self {
            objective,
            objective_digest,
            ndu_set,
            ndu_profile,
            ndu_scalarization,
            eval,
            neuron_config,
            neuron_tick,
            prompt,
            intuition,
            context,
        }
    }
}

struct NativeOwnerPorts {
    fixtures: NativeFixtures,
    calls: Vec<CompositionStageV3>,
}

impl NativeOwnerPorts {
    fn receipt(
        input: &CompositionPortInputV3,
        producer: &str,
        output_digest: Digest32,
        evidence_digest: Digest32,
        decision: CompositionPortDecisionV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Ok(CompositionPortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            evidence_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl CompositionPortsV3 for NativeOwnerPorts {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = compile_objective(self.fixtures.objective.clone())
            .expect("objective input")
            .expect("objective conflict-free");
        assert_eq!(receipt.disposition, CompileDisposition::Compiled);
        Self::receipt(
            input,
            "objective.compiler",
            receipt.objective.semantic_digest,
            receipt.receipt_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = evaluate_candidates(
            self.fixtures.ndu_set.clone(),
            self.fixtures.ndu_profile.clone(),
            Some(self.fixtures.ndu_scalarization.clone()),
        )
        .expect("NDU");
        Self::receipt(
            input,
            "utility.ndu",
            receipt.evaluation_digest,
            receipt.utility_profile_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = evaluate_independently(self.fixtures.eval.clone()).expect("evaluation");
        assert_eq!(
            receipt.disposition,
            EvalDisposition::EligibleForFurtherReview
        );
        Self::receipt(
            input,
            "learning.eval",
            receipt.evidence_digest,
            receipt.evidence_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let (_, receipt) =
            sparse_tick(&self.fixtures.neuron_config, &self.fixtures.neuron_tick, None)
                .expect("neuron");
        assert!(receipt.requires_calibration);
        assert!(!receipt.authority.grants_any());
        Self::receipt(
            input,
            "neuron.runtime",
            receipt.checkpoint_after,
            receipt.signal_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = calculate_local_shadow(self.fixtures.prompt.clone()).expect("prompt");
        assert!(!receipt.authority().grants_any());
        Self::receipt(
            input,
            "prompt.optimizer",
            receipt.proposal_digest,
            receipt.proposal_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = decide_calibrated(self.fixtures.intuition.clone()).expect("intuition");
        assert!(!receipt.authority.grants_any());
        let decision = match receipt.disposition {
            CalibratedDispositionV1::Selected(_) => CompositionPortDecisionV3::Continue,
            CalibratedDispositionV1::Abstained(_) => CompositionPortDecisionV3::Abstain,
            CalibratedDispositionV1::SlowPath(_) => CompositionPortDecisionV3::SlowPath,
        };
        Self::receipt(
            input,
            "intuition.policy",
            receipt.receipt_digest,
            receipt.receipt_digest,
            decision,
        )
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        self.calls.push(input.stage);
        let receipt = compile_context(self.fixtures.context.clone()).expect("context");
        assert!(!receipt.authority.grants_any());
        Self::receipt(
            input,
            "context.compiler",
            receipt.context_digest,
            receipt.context_digest,
            CompositionPortDecisionV3::Continue,
        )
    }
}

struct Control;

impl CompositionControlV3 for Control {
    fn now_unix_micros(&self) -> u64 {
        1_000
    }

    fn is_cancelled(&self, _: &StableId) -> bool {
        false
    }
}

#[test]
fn v3_composes_real_native_owner_algorithms_in_one_trace() {
    let objective = objective_source();
    let objective_receipt = compile_objective(objective.clone())
        .expect("objective")
        .expect("no conflict");
    let objective_digest = objective_receipt.objective.semantic_digest;
    let capabilities = [
        ("objective.validation", "objective.compiler", CapabilityNecessityV2::Required),
        ("utility.evaluation", "utility.ndu", CapabilityNecessityV2::Required),
        ("evaluation.admission", "learning.eval", CapabilityNecessityV2::Required),
        ("neural.signal", "neuron.runtime", CapabilityNecessityV2::Optional),
        ("prompt.portfolio", "prompt.optimizer", CapabilityNecessityV2::Optional),
        ("intuition.decision", "intuition.policy", CapabilityNecessityV2::Required),
        ("context.compilation", "context.compiler", CapabilityNecessityV2::Required),
    ];
    let requirements = capabilities
        .iter()
        .map(|(capability, owner, necessity)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: *necessity,
        })
        .collect::<Vec<_>>();
    let bindings = capabilities
        .iter()
        .map(|(capability, owner, _)| CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: generation(1),
        })
        .collect::<Vec<_>>();
    let snapshot = CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 9,
        body_generation: generation(1),
        configuration_digest: digest("native-v3-configuration"),
        revocation_frontier_digest: digest("native-v3-revocations"),
        requirements,
        bindings,
    })
    .expect("snapshot");

    let fixtures = NativeFixtures::new(snapshot.digest(), objective);
    assert_eq!(fixtures.objective_digest, objective_digest);
    let legal_candidates = build_legal_candidates(LegalActionCandidateSetRequestV1 {
        candidate_set_id: id("native-v3-legal-set"),
        state_digest: snapshot.digest(),
        grammar_digest: digest("native-v3-action-grammar"),
        candidates: vec![LegalActionCandidateV1 {
            candidate_id: id("action:report"),
            action_digest: digest("native-v3-action-report"),
            support_digest: digest("native-v3-action-support"),
            support_ppm: 1_000_000,
        }],
        support_floor_ppm: 900_000,
    })
    .expect("legal candidates");
    let mut ports = NativeOwnerPorts {
        fixtures,
        calls: Vec::new(),
    };

    let receipt = prepare_intelligence_run_v3(
        CompositionRunRequestV3 {
            run_id: id("native-v3-run"),
            request_digest: digest("native-v3-request"),
            body_digest: digest("native-v3-body"),
            artifact_set_digest: digest("native-v3-artifact-set"),
            snapshot,
            legal_candidates,
            budget: CompositionBudgetV3 {
                total_micros: 8_000,
                objective_micros: 1_000,
                legal_set_micros: 1_000,
                utility_micros: 1_000,
                evaluation_micros: 1_000,
                neural_micros: 1_000,
                prompt_micros: 1_000,
                intuition_micros: 1_000,
                context_micros: 1_000,
            },
            deadline_unix_micros: 100_000,
        },
        &mut ports,
        &Control,
    )
    .expect("V3 native composition");

    assert_eq!(
        receipt.disposition,
        CompositionDispositionV3::HostEnvelopePrepared
    );
    assert_eq!(
        ports.calls,
        vec![
            CompositionStageV3::ObjectiveValidated,
            CompositionStageV3::UtilityEvaluated,
            CompositionStageV3::EvaluationAdmitted,
            CompositionStageV3::NeuralSignalCollected,
            CompositionStageV3::PromptPortfolioBuilt,
            CompositionStageV3::IntuitionDecided,
            CompositionStageV3::ContextCompiled,
        ]
    );
    let envelope = receipt.envelope.expect("host envelope");
    assert_eq!(envelope.objective_digest, objective_digest);
    assert_eq!(envelope.authority_epoch, 9);
    assert!(!envelope.envelope_digest.is_zero());
    assert!(!envelope.authority.grants_any());
}
