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
        max_active_runs: 2,
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
        authority_epoch: 7,
        deadline_ms: 10_000,
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
    }
}

fn assert_receipt(
    receipt: &RunReceipt,
    revision: u64,
    phase: RunPhase,
    cancel_reason: Option<&str>,
) {
    assert_eq!(receipt.run_id, "run.1");
    assert_eq!(receipt.revision, revision);
    assert_eq!(receipt.phase, phase);
    assert_eq!(receipt.authority_epoch, 7);
    assert_eq!(receipt.deadline_ms, 10_000);
    assert_eq!(receipt.cancel_reason.as_deref(), cancel_reason);
}

#[test]
fn freezes_the_complete_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_receipt(&admitted, 1, RunPhase::Admitted, None);

    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(200, 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut wrong_authority = attachment();
    wrong_authority.authority_epoch = 8;
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_authority),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut wrong_deadline = attachment();
    wrong_deadline.deadline_ms += 1;
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_deadline),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(200, 1, attachment())
        .expect("attach context");
    assert_receipt(&attached, 2, RunPhase::ContextAttached, None);
    assert_eq!(attached.context_digest, Some(digest('7')));
}

#[test]
fn cancellation_preserves_the_dispatch_boundary_and_reason() {
    let mut before = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before
        .cancel_run(200, "run.1", 1, "operator_request")
        .expect("cancel");
    assert_eq!(early.0, CancellationDisposition::CancelledBeforeDispatch);
    assert_receipt(&early.1, 2, RunPhase::Cancelled, Some("operator_request"));
    assert!(early.1.terminal_observed);

    let mut after = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(200, 1, attachment())
        .expect("attach context");
    after.mark_dispatched(300, "run.1", 2).expect("dispatch");
    let late = after
        .cancel_run(400, "run.1", 3, "operator_request")
        .expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_receipt(&late.1, 4, RunPhase::Cancelling, Some("operator_request"));
    assert_eq!(late.1.cancel_ack_deadline_ms, Some(3_400));

    let repeated = after
        .cancel_run(450, "run.1", 4, "operator_request")
        .expect("idempotent cancel");
    assert!(repeated.1.idempotent);
    assert_eq!(
        after.cancel_run(450, "run.1", 4, "different_reason"),
        Err(AgentRunError::Conflict)
    );

    let terminal = after
        .observe_terminal("run.1", 4, RunPhase::Indeterminate, false)
        .expect("observe unknown terminality");
    assert_receipt(
        &terminal,
        5,
        RunPhase::Indeterminate,
        Some("operator_request"),
    );
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
    coordinator.close_admissions();
    let repeated = coordinator.start_run(100, original).expect("repeat");
    assert!(repeated.idempotent);

    let mut changed = snapshot();
    changed.objective_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, changed),
        Err(AgentRunError::Conflict)
    );

    let mut new = snapshot();
    new.run_id = "run.2".to_string();
    assert_eq!(
        coordinator.start_run(100, new),
        Err(AgentRunError::AdmissionClosed)
    );
}

#[test]
fn active_run_capacity_is_bound_by_runtime_composition() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("first");

    let mut second = snapshot();
    second.run_id = "run.2".to_string();
    coordinator.start_run(100, second).expect("second");

    let mut third = snapshot();
    third.run_id = "run.3".to_string();
    assert_eq!(
        coordinator.start_run(100, third),
        Err(AgentRunError::CapacityExceeded)
    );
}

#[test]
fn lifecycle_deadline_is_enforced_after_admission() {
    let mut pre = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let mut pre_snapshot = snapshot();
    pre_snapshot.deadline_ms = 200;
    pre.start_run(100, pre_snapshot).expect("start");
    assert_eq!(
        pre.attach_context(
            200,
            1,
            ContextAttachment {
                deadline_ms: 200,
                ..attachment()
            }
        ),
        Err(AgentRunError::DeadlineElapsed)
    );
    assert_eq!(pre.expire_deadlines(200).expect("expire"), 1);
    let expired = pre.run("run.1").expect("retained");
    assert_eq!(expired.phase, RunPhase::Cancelled);
    assert_eq!(expired.cancel_reason.as_deref(), Some("deadline_elapsed"));

    let mut post = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let mut post_snapshot = snapshot();
    post_snapshot.deadline_ms = 300;
    post.start_run(100, post_snapshot).expect("start");
    post.attach_context(
        150,
        1,
        ContextAttachment {
            deadline_ms: 300,
            ..attachment()
        },
    )
    .expect("attach");
    post.mark_dispatched(200, "run.1", 2).expect("dispatch");
    assert_eq!(post.expire_deadlines(300).expect("expire"), 1);
    let expired = post.run("run.1").expect("retained");
    assert_eq!(expired.phase, RunPhase::Cancelling);
    assert_eq!(expired.cancel_reason.as_deref(), Some("deadline_elapsed"));
    assert_eq!(expired.cancel_ack_deadline_ms, Some(3_300));
    assert!(!expired.terminal_observed);
    assert_eq!(post.expire_deadlines(3_300).expect("ack timeout"), 1);
    let indeterminate = post.run("run.1").expect("retained");
    assert_eq!(indeterminate.phase, RunPhase::Indeterminate);
    assert_eq!(indeterminate.cancel_ack_deadline_ms, None);
}

#[test]
fn drain_closes_admission_and_preserves_dispatch_uncertainty() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(300, "run.1", 2)
        .expect("dispatch");

    assert_eq!(
        coordinator
            .begin_drain(400, "agentd_draining")
            .expect("begin drain"),
        1
    );
    assert!(!coordinator.admissions_open());
    let draining = coordinator.run("run.1").expect("run");
    assert_eq!(draining.phase, RunPhase::Cancelling);
    assert_eq!(draining.cancel_reason.as_deref(), Some("agentd_draining"));

    assert_eq!(
        coordinator
            .mark_unresolved_indeterminate("shutdown_drain_timeout")
            .expect("mark unknown"),
        1
    );
    let unknown = coordinator.run("run.1").expect("run");
    assert_eq!(unknown.phase, RunPhase::Indeterminate);
    assert_eq!(coordinator.unresolved_run_count(), 1);
}

#[test]
fn recovery_rehydrates_only_an_indeterminate_non_redispatchable_run() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.close_admissions();
    let recovery = RunRecovery {
        snapshot: snapshot(),
        revision: 9,
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
        cancel_reason: Some("process_restart".to_string()),
    };
    let recovered = coordinator
        .recover_indeterminate(recovery.clone())
        .expect("recover");
    assert_receipt(
        &recovered,
        9,
        RunPhase::Indeterminate,
        Some("process_restart"),
    );
    let repeated = coordinator
        .recover_indeterminate(recovery)
        .expect("repeat recovery");
    assert!(repeated.idempotent);
    assert_eq!(
        coordinator.mark_dispatched(200, "run.1", 9),
        Err(AgentRunError::InvalidTransition)
    );

    let observed = coordinator
        .observe_terminal("run.1", 9, RunPhase::Succeeded, true)
        .expect("terminal reconciliation");
    assert_receipt(&observed, 10, RunPhase::Succeeded, Some("process_restart"));
    assert!(observed.terminal_observed);
}

#[test]
fn terminal_observation_is_idempotent_and_only_closed_runs_can_be_removed() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach context");
    coordinator
        .mark_dispatched(300, "run.1", 2)
        .expect("dispatch");
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
fn indeterminate_outcomes_reconcile_without_redispatch_or_leaked_capacity() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    for _ in 0..MAX_RETAINED_RUNS + 1 {
        coordinator
            .start_run(/*now_ms*/ 100, snapshot())
            .expect("admit");
        coordinator
            .attach_context(
                /*now_ms*/ 200,
                /*expected_revision*/ 1,
                attachment(),
            )
            .expect("attach");
        coordinator
            .mark_dispatched(/*now_ms*/ 300, "run.1", /*expected_revision*/ 2)
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
            coordinator.cancel_run(400, "run.1", unknown.revision, "operator_request"),
            Err(AgentRunError::TerminalObservationRequired)
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", unknown.revision),
            Err(AgentRunError::InvalidTransition)
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
use codex_hepta_intelligence::CurrentCapabilitySnapshotErrorV3;
use codex_hepta_intelligence::CurrentCapabilitySnapshotProviderV3;
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

#[test]
fn terminal_learning_closure_is_bound_to_the_exact_run_decision() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    let binding = LearningDecisionBindingV3 {
        episode_id: v3_id("episode:run.1"),
        event_digest: v3_digest("decision-event:run.1"),
        chain_digest: v3_digest("decision-chain:run.1"),
    };
    coordinator
        .bind_learning_decision("run.1", binding.clone())
        .expect("bind durable decision");

    assert_eq!(
        coordinator.require_learning_closure_binding(
            "run.1",
            &v3_id("episode:other"),
            binding.chain_digest,
        ),
        Err(AgentRunError::LearningDecisionBindingMismatch)
    );
    assert_eq!(
        coordinator.require_learning_closure_binding(
            "run.1",
            &binding.episode_id,
            v3_digest("different-decision-chain"),
        ),
        Err(AgentRunError::LearningDecisionBindingMismatch)
    );
    coordinator
        .require_learning_closure_binding(
            "run.1",
            &binding.episode_id,
            binding.chain_digest,
        )
        .expect("exact binding");
}

fn v3_snapshot(revocation_frontier: &str) -> CapabilitySnapshotV2 {
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
        revocation_frontier_digest: v3_digest(revocation_frontier),
        requirements,
        bindings,
    })
    .expect("capability snapshot");
    snapshot
}

fn v3_request() -> LaneFRunRequestV3 {
    let snapshot = v3_snapshot("revocations");
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


struct StaticCurrentSnapshotProvider {
    snapshot: CapabilitySnapshotV2,
    calls: usize,
}

impl CurrentCapabilitySnapshotProviderV3 for StaticCurrentSnapshotProvider {
    fn current_snapshot(
        &mut self,
    ) -> Result<CapabilitySnapshotV2, CurrentCapabilitySnapshotErrorV3> {
        self.calls += 1;
        Ok(self.snapshot.clone())
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
            capability_id: input.capability_id.clone(),
            implementation_digest: input.implementation_digest,
            capability_generation: input.capability_generation,
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
fn final_use_capability_snapshot_is_revalidated_before_agentd_handoff() {
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
    let mut provider = StaticCurrentSnapshotProvider {
        snapshot: request.snapshot.clone(),
        calls: 0,
    };
    let mut ports = RuntimeV3Ports::default();
    let receipt = coordinator
        .run_intelligence_v3_with_control_and_currentness(
            1,
            request,
            &mut ports,
            &NeverCancelledV3,
            Some(&mut provider),
        )
        .expect("fresh composition");
    assert_eq!(provider.calls, 1);
    assert_eq!(
        receipt.runtime.as_ref().map(|runtime| runtime.phase),
        Some(RunPhase::ContextAttached)
    );
}

#[test]
fn stale_final_use_capability_snapshot_fails_before_handoff_and_learning() {
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
    let mut provider = StaticCurrentSnapshotProvider {
        snapshot: v3_snapshot("revocations:advanced"),
        calls: 0,
    };
    let mut ports = RuntimeV3Ports::default();
    let receipt = coordinator
        .run_intelligence_v3_with_control_and_currentness(
            1,
            request,
            &mut ports,
            &NeverCancelledV3,
            Some(&mut provider),
        )
        .expect("terminal stale receipt");
    assert_eq!(provider.calls, 1);
    assert_eq!(
        receipt.composition.disposition,
        codex_hepta_intelligence::PipelineDispositionV3::Failed(PortFailureClassV3::Rejected)
    );
    assert!(receipt.runtime.is_none());
    assert!(!ports.calls.contains(&LaneFStageV3::HostHandoffAccepted));
    assert!(!ports.calls.contains(&LaneFStageV3::LearningRecorded));
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
