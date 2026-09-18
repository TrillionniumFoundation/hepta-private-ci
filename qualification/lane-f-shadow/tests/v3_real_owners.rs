use std::fs;
use std::fs::OpenOptions;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_agentd::AgentRunCoordinator;
use codex_hepta_agentd::ContextAttachment;
use codex_hepta_agentd::RunSnapshot;
use codex_hepta_agentd::RuntimeComposition;
use codex_hepta_agentd::prepare_intelligence_dispatch_v1;
use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_context_compiler::compile as compile_context;
use codex_hepta_intelligence::*;
use codex_hepta_intelligence_eval::EvaluationDirection;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::MetricDelta;
use codex_hepta_intelligence_eval::evaluate as evaluate_candidate;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates;
use codex_hepta_objective::ActionClass;
use codex_hepta_objective::Comparator;
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::PredicateTerminality;
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::SoftPreference;
use codex_hepta_objective::SourceTrust;
use codex_hepta_objective::SuccessPredicate;
use codex_hepta_objective::compile as compile_objective;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use lane_f_shadow::LaneFShadowReceipt;
use lane_f_shadow::run_lane_f_shadow_for_objective;

static NEXT_LEDGER: AtomicU64 = AtomicU64::new(1);

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn objective_envelope() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        revision: Revision::new(1).expect("revision"),
        principal_scope_digest: digest("principal"),
        success_predicates: vec![SuccessPredicate {
            predicate_id: id("success"),
            evidence_source: id("observer"),
            comparator: Comparator::GreaterThanOrEqual,
            threshold: FixedQ32::ONE,
            terminality: PredicateTerminality::RequiredBeforeSuccess,
        }],
        terminal_conditions: Vec::new(),
        hard_constraints: Vec::new(),
        allowed_action_classes: vec![ActionClass {
            action_id: id("action:prompt:1"),
            requires_confirmation: false,
        }],
        forbidden_action_classes: Vec::new(),
        soft_preferences: vec![SoftPreference {
            dimension: id("quality"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
        source_trust: SourceTrust::Trusted,
        source_digest: digest("objective-source"),
    }
}

fn capabilities(objective_digest: Digest32) -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler", CapabilityNecessityV2::Required),
        ("legal.actions", "intelligence.control", CapabilityNecessityV2::Required),
        ("utility.evaluation", "utility.ndu", CapabilityNecessityV2::Required),
        ("learning.evaluation", "learning.eval", CapabilityNecessityV2::Required),
        ("neural.signal", "neuron.runtime", CapabilityNecessityV2::Optional),
        ("prompt.portfolio", "prompt.optimizer", CapabilityNecessityV2::Optional),
        ("intuition.decision", "intuition.policy", CapabilityNecessityV2::Required),
        ("context.compilation", "context.compiler", CapabilityNecessityV2::Required),
        ("host.envelope", "intelligence.control", CapabilityNecessityV2::Required),
        ("dispatch.proposal", "runtime.agentd", CapabilityNecessityV2::Required),
        ("learning.record", "learning.ledger", CapabilityNecessityV2::Required),
    ];
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements: pairs
            .iter()
            .map(|(capability, owner, necessity)| CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: digest(&format!("contract:{capability}")),
                necessity: *necessity,
            })
            .collect(),
        bindings: pairs
            .iter()
            .map(|(capability, owner, _)| CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: digest(&format!("contract:{capability}")),
                implementation_digest: digest(&format!("implementation:{owner}")),
                generation: Generation::new(1).expect("generation"),
            })
            .collect(),
    })
    .expect("capability snapshot")
}

fn context_request(snapshot: Digest32, objective: Digest32) -> CompilationRequest {
    CompilationRequest {
        compilation_id: id("context.v3.real"),
        run_snapshot_digest: snapshot,
        objective_digest: objective,
        token_budget: 16,
        items: vec![ContextItem {
            item_id: id("context.instruction"),
            role: ContextRole::TrustedInstruction,
            content_digest: digest("inspect-before-mutate"),
            source_digest: digest("prompt-registry"),
            token_count: 4,
            contains_secret: false,
        }],
    }
}

fn agentd(
    request_digest: Digest32,
    objective_digest: Digest32,
    context_digest: Digest32,
) -> (AgentRunCoordinator, ContextAttachment) {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.v3.real".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("agentd-config").to_string(),
        ports_digest: digest("agentd-ports").to_string(),
    })
    .expect("agentd runtime");
    coordinator
        .start_run(
            1,
            RunSnapshot {
                run_id: "run.v3.real".to_string(),
                request_digest: request_digest.to_string(),
                objective_digest: objective_digest.to_string(),
                body_digest: digest("body").to_string(),
                artifact_set_digest: digest("artifact-set").to_string(),
                authority_epoch: 1,
                deadline_ms: 10_000,
            },
        )
        .expect("start run");
    let attachment = ContextAttachment {
        run_id: "run.v3.real".to_string(),
        request_digest: request_digest.to_string(),
        objective_digest: objective_digest.to_string(),
        body_digest: digest("body").to_string(),
        artifact_set_digest: digest("artifact-set").to_string(),
        context_digest: context_digest.to_string(),
        compilation_receipt_digest: context_digest.to_string(),
    };
    coordinator
        .attach_context(1, attachment.clone())
        .expect("attach context");
    (coordinator, attachment)
}

fn ledger() -> (DurableLedger, std::path::PathBuf) {
    let suffix = NEXT_LEDGER.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-v3-real-owner-{}-{suffix}.ledger",
        std::process::id()
    ));
    let _ = fs::remove_file(&path);
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("ledger file");
    (
        DurableLedger::create(file, digest("v3-real-owner-ledger"), 8).expect("ledger"),
        path,
    )
}

struct RealPorts {
    objective: ObjectiveSourceEnvelope,
    objective_digest: Digest32,
    utility_digest: Option<Digest32>,
    lane_f: Option<LaneFShadowReceipt>,
    context: CompilationRequest,
    agentd: AgentRunCoordinator,
    attachment: ContextAttachment,
    ledger: DurableLedger,
    ledger_head: Digest32,
}

impl RealPorts {
    fn receipt(
        input: &PortInputV3,
        owner: &str,
        output_digest: Digest32,
        decision: PortDecisionV1,
    ) -> PortReceiptV3 {
        PortReceiptV3 {
            stage: input.stage,
            producer: id(owner),
            snapshot_digest: input.snapshot_digest,
            candidate_set_digest: input.candidate_set_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn failure(input: &PortInputV3) -> PortFailureV3 {
        PortFailureV3 {
            class: PortFailureClassV1::Rejected,
            evidence_digest: digest(&format!("real-owner-failure:{:?}", input.stage)),
        }
    }
}

impl LaneFCompositionPortsV3 for RealPorts {
    fn validate_objective(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let receipt = compile_objective(self.objective.clone()).map_err(|_| Self::failure(input))?;
        if receipt.objective.semantic_digest != self.objective_digest {
            return Err(Self::failure(input));
        }
        Ok(Self::receipt(
            input,
            "objective.compiler",
            receipt.objective.semantic_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn evaluate_utility(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let generation = Generation::new(1).map_err(|_| Self::failure(input))?;
        let receipt = evaluate_candidates(
            ContributionSet {
                objective_digest: self.objective_digest,
                generation,
                contributions: vec![UtilityContribution {
                    candidate_id: id("action:prompt:1"),
                    organ_id: id("organ:planner"),
                    objective_digest: self.objective_digest,
                    generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ONE,
                    }],
                    risk: Vec::new(),
                    resource: Vec::new(),
                    uncertainty: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest("ndu-support"),
                }],
            },
            UtilityProfile {
                profile_id: id("utility.v3.real"),
                dimensions: vec![(id("quality"), AxisDirection::Maximize)],
                risk_ceilings: Vec::new(),
                resource_ceilings: Vec::new(),
                required_organs: RequiredOrganSet {
                    organ_ids: vec![id("organ:planner")],
                },
            },
            None,
        )
        .map_err(|_| Self::failure(input))?;
        self.utility_digest = Some(receipt.evaluation_digest);
        Ok(Self::receipt(
            input,
            "utility.ndu",
            receipt.evaluation_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn admit_evaluation(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let utility = self.utility_digest.ok_or_else(|| Self::failure(input))?;
        let receipt = evaluate_candidate(EvaluationRequest {
            evaluation_id: id("evaluation.v3.real"),
            candidate_artifact_digest: utility,
            baseline_artifact_digest: digest("baseline"),
            dataset_digest: digest("dataset"),
            metrics: vec![MetricDelta {
                metric_id: id("quality"),
                baseline: FixedQ32::ZERO,
                candidate: FixedQ32::ONE,
                direction: EvaluationDirection::HigherIsBetter,
                support_digest: digest("eval-support"),
            }],
            minimum_effect: FixedQ32::ZERO,
            support_complete: true,
        })
        .map_err(|_| Self::failure(input))?;
        Ok(Self::receipt(
            input,
            "learning.eval",
            receipt.evidence_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let receipt =
            run_lane_f_shadow_for_objective(self.objective_digest).map_err(|_| Self::failure(input))?;
        let output = receipt.neuron.receipt_digest;
        self.lane_f = Some(receipt);
        Ok(Self::receipt(
            input,
            "neuron.runtime",
            output,
            PortDecisionV1::Continue,
        ))
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let receipt = self.lane_f.as_ref().ok_or_else(|| Self::failure(input))?;
        Ok(Self::receipt(
            input,
            "prompt.optimizer",
            receipt.prompt.proposal_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn decide_intuition(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let receipt = self.lane_f.as_ref().ok_or_else(|| Self::failure(input))?;
        Ok(Self::receipt(
            input,
            "intuition.policy",
            receipt.intuition.receipt_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn compile_context(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let receipt = compile_context(self.context.clone()).map_err(|_| Self::failure(input))?;
        Ok(Self::receipt(
            input,
            "context.compiler",
            receipt.context_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn propose_dispatch(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let proposal = prepare_intelligence_dispatch_v1(
            &mut self.agentd,
            2,
            &self.attachment,
            envelope,
        )
        .map_err(|_| Self::failure(input))?;
        Ok(Self::receipt(
            input,
            "runtime.agentd",
            proposal.proposal_digest,
            PortDecisionV1::Continue,
        ))
    }

    fn record_learning(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let append = self
            .ledger
            .append(
                self.ledger_head,
                LedgerEvent::Decision(EpisodeDecision {
                    record_id: id("decision.v3.real"),
                    episode_id: id("episode.v3.real"),
                    objective_digest: self.objective_digest,
                    policy_id: id("policy.v3.real"),
                    candidate_ids: vec![id("action:prompt:1")],
                    selected_candidate_id: id("action:prompt:1"),
                    selected_propensity: ProbabilityQ32::ONE,
                    completeness: CandidateSetCompleteness::Complete,
                    support_digest: input.predecessor_digest,
                }),
            )
            .map_err(|_| Self::failure(input))?;
        self.ledger_head = append.chain_digest;
        Ok(Self::receipt(
            input,
            "learning.ledger",
            append.chain_digest,
            PortDecisionV1::Continue,
        ))
    }
}

#[test]
fn v3_traverses_real_owner_receipts_and_agentd_without_fake_stage_digests() {
    let objective = objective_envelope();
    let objective_receipt = compile_objective(objective.clone()).expect("objective");
    let objective_digest = objective_receipt.objective.semantic_digest;
    let snapshot = capabilities(objective_digest);
    let request_digest = digest("v3-request");
    let context = context_request(snapshot.digest(), objective_digest);
    let context_receipt = compile_context(context.clone()).expect("context");
    let (agentd, attachment) =
        agentd(request_digest, objective_digest, context_receipt.context_digest);
    let (ledger, ledger_path) = ledger();

    let legal_candidates =
        LegalActionCandidateSetV1::new(LegalActionCandidateSetInputV1 {
            candidate_set_id: id("candidate-set.v3.real"),
            state_digest: snapshot.digest(),
            generator_id: id("intelligence.control"),
            grammar_digest: digest("grammar"),
            candidates: vec![LegalActionCandidateV1 {
                candidate_id: id("action:prompt:1"),
                action_digest: digest("action:prompt:1"),
                support_digest: digest("candidate-support"),
            }],
            support_floor_ppm: 1,
        })
        .expect("candidate set");

    let mut ports = RealPorts {
        objective,
        objective_digest,
        utility_digest: None,
        lane_f: None,
        context,
        agentd,
        attachment,
        ledger,
        ledger_head: Digest32::ZERO,
    };
    let receipt = run_composition_v3(
        LaneFCompositionRequestV3 {
            run_id: id("run.v3.real"),
            request_digest,
            snapshot,
            legal_candidates,
            budget: LaneFCompositionBudgetV3 {
                total_micros: 11_000_000,
                objective_micros: 1_000_000,
                legal_set_micros: 1_000_000,
                utility_micros: 1_000_000,
                evaluation_micros: 1_000_000,
                neural_micros: 1_000_000,
                prompt_micros: 1_000_000,
                intuition_micros: 1_000_000,
                context_micros: 1_000_000,
                envelope_micros: 1_000_000,
                dispatch_micros: 1_000_000,
                ledger_micros: 1_000_000,
            },
        },
        &mut ports,
        &mut SystemCompositionClockV3::default(),
        &NeverCancelledV3,
    )
    .expect("real-owner V3 composition");

    assert_eq!(receipt.disposition, CompositionDispositionV3::DispatchProposed);
    assert_eq!(receipt.stages.len(), 11);
    assert_eq!(ports.ledger.records().expect("ledger records").len(), 1);
    assert!(!receipt.authority.grants_any());
    receipt.validate().expect("V3 receipt");
    assert_eq!(
        ports
            .agentd
            .run("run.v3.real")
            .expect("agentd run")
            .phase,
        codex_hepta_agentd::RunPhase::ContextAttached
    );

    drop(ports);
    let _ = fs::remove_file(ledger_path);
}
