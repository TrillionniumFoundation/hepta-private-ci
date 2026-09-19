use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".to_string(),
        supervisor_generation: 2,
        agentd_generation: 3,
        configuration_digest: digest('1'),
        ports_digest: digest('2'),
    }
}

fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.1".to_string(),
        request_digest: digest('3'),
        objective_digest: digest('4'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        authority_epoch: 7,
        deadline_ms: 10_000,
    }
}

fn attachment() -> ContextAttachment {
    ContextAttachment {
        run_id: "run.1".to_string(),
        request_digest: digest('3'),
        objective_digest: digest('4'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
    }
}

#[test]
fn freezes_the_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_eq!(
        admitted,
        RunReceipt {
            run_id: "run.1".to_string(),
            revision: 1,
            phase: RunPhase::Admitted,
            context_digest: None,
            terminal_observed: false,
            idempotent: false,
        }
    );

    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(1, attachment())
        .expect("attach context");
    assert_eq!(
        attached,
        RunReceipt {
            run_id: "run.1".to_string(),
            revision: 2,
            phase: RunPhase::ContextAttached,
            context_digest: Some(digest('7')),
            terminal_observed: false,
            idempotent: false,
        }
    );
}

#[test]
fn cancellation_preserves_the_dispatch_boundary() {
    let mut before = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before.cancel_run("run.1", 1).expect("cancel");
    assert_eq!(
        early,
        (
            CancellationDisposition::CancelledBeforeDispatch,
            RunReceipt {
                run_id: "run.1".to_string(),
                revision: 2,
                phase: RunPhase::Cancelled,
                context_digest: None,
                terminal_observed: true,
                idempotent: false,
            },
        )
    );

    let mut after = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(1, attachment())
        .expect("attach context");
    after.mark_dispatched("run.1", 2).expect("dispatch");
    let late = after.cancel_run("run.1", 3).expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_eq!(late.1.phase, RunPhase::Cancelling);
    let terminal = after
        .observe_terminal("run.1", 4, RunPhase::Indeterminate, false)
        .expect("observe unknown terminality");
    assert_eq!(terminal.phase, RunPhase::Indeterminate);
    assert!(!terminal.terminal_observed);
}

#[test]
fn operation_identity_is_idempotent_only_for_equal_semantics() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let original = snapshot();
    coordinator
        .start_run(100, original.clone())
        .expect("admit run");
    let repeated = coordinator.start_run(100, original).expect("repeat");
    assert!(repeated.idempotent);

    let mut changed = snapshot();
    changed.objective_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, changed),
        Err(AgentRunError::Conflict)
    );
}

#[test]
fn terminal_observation_is_idempotent_and_only_closed_runs_can_be_removed() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(1, attachment())
        .expect("attach context");
    coordinator.mark_dispatched("run.1", 2).expect("dispatch");
    let completed = coordinator
        .observe_terminal("run.1", 3, RunPhase::Succeeded, true)
        .expect("complete");
    let repeated = coordinator
        .observe_terminal("run.1", 3, RunPhase::Succeeded, true)
        .expect("repeat terminal observation");
    assert!(repeated.idempotent);
    assert_eq!(repeated.revision, completed.revision);
    let removed = coordinator
        .remove_closed_run("run.1", completed.revision)
        .expect("remove closed run");
    assert_eq!(removed.phase, RunPhase::Succeeded);
    assert_eq!(coordinator.run("run.1"), None);
}

#[test]
fn identical_context_bytes_do_not_hide_a_changed_run_snapshot() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator
        .start_run(/*now_ms*/ 100, snapshot())
        .expect("admit");
    let original = coordinator
        .attach_context(/*expected_revision*/ 1, attachment())
        .expect("attach");
    let mut mixed = attachment();
    mixed.objective_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(/*expected_revision*/ 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );
    let current = coordinator.run("run.1").expect("retained run");
    assert_eq!(current.revision, original.revision);
    assert_eq!(current.phase, original.phase);
}

#[test]
fn indeterminate_outcomes_reconcile_without_redispatch_or_leaked_capacity() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    for _ in 0..MAX_RETAINED_RUNS + 1 {
        coordinator
            .start_run(/*now_ms*/ 100, snapshot())
            .expect("admit");
        coordinator
            .attach_context(/*expected_revision*/ 1, attachment())
            .expect("attach");
        coordinator
            .mark_dispatched("run.1", /*expected_revision*/ 2)
            .expect("dispatch");
        let unknown = coordinator
            .observe_terminal(
                "run.1",
                /*expected_revision*/ 3,
                RunPhase::Indeterminate,
                /*terminal_observed*/ false,
            )
            .expect("unknown outcome");
        assert_eq!(
            coordinator.cancel_run("run.1", unknown.revision),
            Err(AgentRunError::TerminalObservationRequired)
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", unknown.revision),
            Err(AgentRunError::InvalidTransition)
        );
        assert_eq!(
            coordinator.observe_terminal(
                "run.1",
                /*expected_revision*/ 3,
                RunPhase::Succeeded,
                /*terminal_observed*/ true
            ),
            Err(AgentRunError::StaleRevision)
        );
        let observed = coordinator
            .observe_terminal(
                "run.1",
                unknown.revision,
                RunPhase::Succeeded,
                /*terminal_observed*/ true,
            )
            .expect("owner-observed reconciliation");
        assert!(observed.terminal_observed);
        coordinator
            .remove_closed_run("run.1", observed.revision)
            .expect("release capacity");
    }
    assert_eq!(coordinator.run("run.1"), None);
}

#[test]
fn intelligence_envelope_attaches_to_the_named_runtime_run() {
    use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    let id = |value: &str| StableId::new(value).expect("fixture id");
    let d = |value: &str| Digest32::of_bytes(value.as_bytes());
    let envelope = IntelligenceHostEnvelopeV1::new(
        id("run.intelligence.1"),
        d("request"),
        d("snapshot"),
        d("objective"),
        7,
        d("body"),
        d("artifact-set"),
        d("candidate-set"),
        d("utility"),
        d("evaluation"),
        Some(d("neural")),
        Some(d("prompt")),
        d("intuition"),
        d("context"),
        d("pre-handoff"),
        10_000_000,
        10_000,
    )
    .expect("intelligence envelope");

    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator
        .start_run(
            100,
            RunSnapshot {
                run_id: envelope.run_id.to_string(),
                request_digest: d("request").to_string(),
                objective_digest: envelope.objective_digest.to_string(),
                body_digest: d("body").to_string(),
                artifact_set_digest: d("artifact-set").to_string(),
                authority_epoch: 7,
                deadline_ms: 10_000,
            },
        )
        .expect("admit run");

    let attached = coordinator
        .attach_intelligence_envelope(1, &envelope)
        .expect("attach intelligence");
    assert_eq!(attached.phase, RunPhase::ContextAttached);
    assert_eq!(
        attached.context_digest,
        Some(envelope.context_digest.to_string())
    );

    let repeated = coordinator
        .attach_intelligence_envelope(1, &envelope)
        .expect("idempotent attachment");
    assert!(repeated.idempotent);
    assert_eq!(repeated.revision, attached.revision);

    let dispatched = coordinator
        .mark_dispatched(envelope.run_id.as_str(), attached.revision)
        .expect("dispatch through existing runtime");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
}

use codex_hepta_intelligence::CapabilityBindingV2;
use codex_hepta_intelligence::CapabilityNecessityV2;
use codex_hepta_intelligence::CapabilityRequirementV2;
use codex_hepta_intelligence::CapabilitySnapshotRequestV2;
use codex_hepta_intelligence::CapabilitySnapshotV2;
use codex_hepta_intelligence::LaneFBudgetV3;
use codex_hepta_intelligence::LegalActionCandidateV1;
use codex_hepta_intelligence::build_legal_candidates_v1;
use codex_hepta_types::Generation;

fn v3_id(value: &str) -> StableId {
    StableId::new(value).expect("V3 fixture id")
}

fn v3_digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn v3_request() -> LaneFRunRequestV3 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let requirements = pairs
        .iter()
        .map(|(capability, owner)| CapabilityRequirementV2 {
            capability_id: v3_id(capability),
            owner_id: v3_id(owner),
            contract_digest: v3_digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        })
        .collect::<Vec<_>>();
    let bindings = requirements
        .iter()
        .map(|requirement| CapabilityBindingV2 {
            capability_id: requirement.capability_id.clone(),
            owner_id: requirement.owner_id.clone(),
            contract_digest: requirement.contract_digest,
            implementation_digest: v3_digest(&format!(
                "implementation:{}",
                requirement.owner_id.as_str()
            )),
            generation: Generation::new(1).expect("generation"),
        })
        .collect();
    let snapshot = CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: v3_digest("objective-v3"),
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: v3_digest("configuration"),
        revocation_frontier_digest: v3_digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot");
    let legal_candidates = build_legal_candidates_v1(
        v3_id("candidate-set"),
        snapshot.digest(),
        v3_digest("grammar"),
        0,
        vec![LegalActionCandidateV1 {
            candidate_id: v3_id("action.read"),
            action_digest: v3_digest("action.read"),
            support_digest: v3_digest("support"),
            support_ppm: 1_000_000,
        }],
    )
    .expect("legal candidates");
    LaneFRunRequestV3 {
        run_id: v3_id("run.v3.agentd"),
        request_digest: v3_digest("request-v3"),
        body_digest: v3_digest("body-v3"),
        artifact_set_digest: v3_digest("artifact-set-v3"),
        snapshot,
        legal_candidates,
        budget: LaneFBudgetV3 {
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
            host_handoff_micros: 1_000_000,
            ledger_micros: 1_000_000,
        },
        deadline_unix_micros: 4_000_000_000_000_000,
    }
}

#[derive(Default)]
struct RuntimeV3Ports {
    calls: Vec<LaneFStageV3>,
}

impl RuntimeV3Ports {
    fn receipt(
        &mut self,
        input: &PortInputV3,
        producer: &str,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.calls.push(input.stage);
        let output_digest = if input.stage == LaneFStageV3::ObjectiveValidated {
            v3_digest("objective-v3")
        } else {
            v3_digest(&format!("output:{:?}", input.stage))
        };
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: v3_id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl LaneFV3Ports for RuntimeV3Ports {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "objective.compiler")
    }

    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "utility.ndu")
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "learning.eval")
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "neuron.runtime")
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "prompt.optimizer")
    }

    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "intuition.policy")
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "context.compiler")
    }

    fn accept_host_envelope(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        envelope.validate().expect("host envelope");
        self.receipt(input, "runtime.agentd")
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.receipt(input, "learning.ledger")
    }
}

#[test]
fn v3_runtime_attach_completes_before_learning_stage() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let request = v3_request();
    coordinator
        .start_run(
            100,
            RunSnapshot {
                run_id: request.run_id.to_string(),
                request_digest: request.request_digest.to_string(),
                objective_digest: v3_digest("objective-v3").to_string(),
                body_digest: request.body_digest.to_string(),
                artifact_set_digest: request.artifact_set_digest.to_string(),
                authority_epoch: 1,
                deadline_ms: request.deadline_unix_micros / 1_000,
            },
        )
        .expect("start run");
    let mut ports = RuntimeV3Ports::default();
    let receipt = coordinator
        .run_intelligence_v3(1, request, &mut ports)
        .expect("composition");
    assert_eq!(
        receipt.runtime.as_ref().map(|runtime| runtime.phase),
        Some(RunPhase::ContextAttached)
    );
    let host = ports
        .calls
        .iter()
        .position(|stage| *stage == LaneFStageV3::HostHandoffAccepted)
        .expect("host call");
    let learning = ports
        .calls
        .iter()
        .position(|stage| *stage == LaneFStageV3::LearningRecorded)
        .expect("learning call");
    assert!(host < learning);
}

#[test]
fn missing_runtime_run_fails_handoff_before_learning_stage() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let mut ports = RuntimeV3Ports::default();
    let receipt = coordinator
        .run_intelligence_v3(1, v3_request(), &mut ports)
        .expect("terminal composition receipt");
    assert_eq!(
        receipt.composition.disposition,
        codex_hepta_intelligence::PipelineDispositionV3::Failed(PortFailureClassV3::Rejected)
    );
    assert!(receipt.runtime.is_none());
    assert!(!ports.calls.contains(&LaneFStageV3::LearningRecorded));
}
