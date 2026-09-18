use codex_hepta_intelligence::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot(include_optional: bool) -> CapabilitySnapshotV2 {
    let mut pairs = vec![
        ("objective.validation", "objective.compiler", CapabilityNecessityV2::Required),
        ("legal.actions", "intelligence.control", CapabilityNecessityV2::Required),
        ("utility.evaluation", "utility.ndu", CapabilityNecessityV2::Required),
        ("learning.evaluation", "learning.eval", CapabilityNecessityV2::Required),
        ("intuition.decision", "intuition.policy", CapabilityNecessityV2::Required),
        ("context.compilation", "context.compiler", CapabilityNecessityV2::Required),
        ("host.envelope", "intelligence.control", CapabilityNecessityV2::Required),
        ("dispatch.proposal", "runtime.agentd", CapabilityNecessityV2::Required),
        ("learning.record", "learning.ledger", CapabilityNecessityV2::Required),
    ];
    if include_optional {
        pairs.extend([
            ("neural.signal", "neuron.runtime", CapabilityNecessityV2::Optional),
            ("prompt.portfolio", "prompt.optimizer", CapabilityNecessityV2::Optional),
        ]);
    }
    let requirements = pairs
        .iter()
        .map(|(capability, owner, necessity)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: *necessity,
        })
        .collect::<Vec<_>>();
    let bindings = pairs
        .iter()
        .map(|(capability, owner, _)| CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("impl:{owner}")),
            generation: Generation::new(1).expect("generation"),
        })
        .collect();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("snapshot")
}

fn request(include_optional: bool) -> LaneFCompositionRequestV3 {
    let snapshot = snapshot(include_optional);
    let legal_candidates = LegalActionCandidateSetV1::new(LegalActionCandidateSetInputV1 {
        candidate_set_id: id("candidate-set"),
        state_digest: snapshot.digest(),
        generator_id: id("intelligence.control"),
        grammar_digest: digest("grammar"),
        candidates: vec![LegalActionCandidateV1 {
            candidate_id: id("action.read"),
            action_digest: digest("action.read"),
            support_digest: digest("support"),
        }],
        support_floor_ppm: 1,
    })
    .expect("candidate set");
    LaneFCompositionRequestV3 {
        run_id: id("run.v3"),
        request_digest: digest("request"),
        snapshot,
        legal_candidates,
        budget: LaneFCompositionBudgetV3 {
            total_micros: 1_100,
            objective_micros: 100,
            legal_set_micros: 100,
            utility_micros: 100,
            evaluation_micros: 100,
            neural_micros: 100,
            prompt_micros: 100,
            intuition_micros: 100,
            context_micros: 100,
            envelope_micros: 100,
            dispatch_micros: 100,
            ledger_micros: 100,
        },
    }
}

#[derive(Default)]
struct Clock {
    now: u64,
    step: u64,
}

impl CompositionClockV3 for Clock {
    fn now_micros(&mut self) -> u64 {
        let value = self.now;
        self.now = self.now.saturating_add(self.step);
        value
    }
}

#[derive(Default)]
struct Cancel(bool);

impl CompositionCancellationV3 for Cancel {
    fn is_cancelled(&self) -> bool {
        self.0
    }
}

#[derive(Default)]
struct Ports {
    calls: Vec<LaneFStageV3>,
    decision: Option<PortDecisionV1>,
    dispatch_envelope: Option<Digest32>,
}

impl Ports {
    fn call(&mut self, input: &PortInputV3, owner: &str) -> Result<PortReceiptV3, PortFailureV3> {
        self.calls.push(input.stage);
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id(owner),
            snapshot_digest: input.snapshot_digest,
            candidate_set_digest: input.candidate_set_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(&format!("{owner}:{:?}", input.stage)),
            decision: if input.stage == LaneFStageV3::IntuitionDecided {
                self.decision.unwrap_or(PortDecisionV1::Continue)
            } else {
                PortDecisionV1::Continue
            },
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

macro_rules! port {
    ($name:ident, $owner:literal) => {
        fn $name(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
            self.call(input, $owner)
        }
    };
}

impl LaneFCompositionPortsV3 for Ports {
    port!(validate_objective, "objective.compiler");
    port!(evaluate_utility, "utility.ndu");
    port!(admit_evaluation, "learning.eval");
    port!(collect_neural_signal, "neuron.runtime");
    port!(build_prompt_portfolio, "prompt.optimizer");
    port!(decide_intuition, "intuition.policy");
    port!(compile_context, "context.compiler");
    fn propose_dispatch(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        assert_eq!(envelope.run_id, input.run_id);
        assert_eq!(envelope.snapshot_digest, input.snapshot_digest);
        assert_eq!(
            envelope.legal_candidate_set_digest,
            input.candidate_set_digest
        );
        self.dispatch_envelope = Some(envelope.envelope_digest);
        self.call(input, "runtime.agentd")
    }
    port!(record_learning, "learning.ledger");
}

#[test]
fn full_graph_binds_utility_evaluation_and_host_envelope() {
    let mut ports = Ports::default();
    let receipt = run_composition_v3(
        request(true),
        &mut ports,
        &mut Clock::default(),
        &Cancel::default(),
    )
    .expect("composition");
    assert_eq!(receipt.disposition, CompositionDispositionV3::DispatchProposed);
    assert_eq!(receipt.stages[2].stage, LaneFStageV3::UtilityEvaluated);
    assert_eq!(receipt.stages[3].stage, LaneFStageV3::EvaluationAdmitted);
    let envelope = receipt.host_envelope.as_ref().expect("host envelope");
    assert_eq!(ports.dispatch_envelope, Some(envelope.envelope_digest));
    receipt.validate().expect("receipt validation");
}

#[test]
fn absent_optional_capabilities_fallback_and_abstain_skips_dispatch() {
    let mut ports = Ports {
        decision: Some(PortDecisionV1::Abstain),
        ..Ports::default()
    };
    let receipt = run_composition_v3(
        request(false),
        &mut ports,
        &mut Clock::default(),
        &Cancel::default(),
    )
    .expect("abstention");
    assert_eq!(receipt.disposition, CompositionDispositionV3::Abstained);
    assert_eq!(
        receipt.stages[4].outcome,
        StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    );
    assert_eq!(
        receipt.stages[5].outcome,
        StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable)
    );
    assert!(!ports.calls.contains(&LaneFStageV3::ContextCompiled));
    assert!(!ports.calls.contains(&LaneFStageV3::DispatchProposed));
    assert_eq!(ports.calls.last(), Some(&LaneFStageV3::LearningRecorded));
}

#[test]
fn cancellation_and_stage_timeout_are_terminal_receipts() {
    let mut ports = Ports::default();
    let cancelled = run_composition_v3(
        request(true),
        &mut ports,
        &mut Clock::default(),
        &Cancel(true),
    )
    .expect("cancelled receipt");
    assert_eq!(cancelled.disposition, CompositionDispositionV3::Cancelled);
    assert!(ports.calls.is_empty());

    let timed_out = run_composition_v3(
        request(true),
        &mut Ports::default(),
        &mut Clock { now: 0, step: 200 },
        &Cancel::default(),
    )
    .expect("timeout receipt");
    assert_eq!(
        timed_out.disposition,
        CompositionDispositionV3::Failed(PortFailureClassV1::TimedOut)
    );
    assert_eq!(timed_out.stages.len(), 1);
}
