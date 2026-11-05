use super::*;

use pretty_assertions::assert_eq;

use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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
        generation: 3,
        fence_digest: digest('9'),
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
        generation: 3,
        fence_digest: digest('9'),
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
    assert_eq!(receipt.generation, 3);
    assert_eq!(receipt.fence_digest, digest('9'));
    assert_eq!(receipt.deadline_ms, 10_000);
    assert_eq!(receipt.cancel_reason.as_deref(), cancel_reason);
}

#[test]
fn freezes_the_complete_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_receipt(&admitted, 1, RunPhase::Admitted, None);
    assert_eq!(admitted.compilation_receipt_digest, None);

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

    let mut wrong_generation = attachment();
    wrong_generation.generation += 1;
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_generation),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut wrong_fence = attachment();
    wrong_fence.fence_digest = digest('a');
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_fence),
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
    assert_eq!(attached.compilation_receipt_digest, Some(digest('8')));
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
fn revalidated_durable_run_start_uses_admitted_source_identity_and_exact_fence() {
    let id = |value: &str| StableId::new(value).expect("stable id");
    let d = |value: &str| Digest32::of_bytes(value.as_bytes());
    let record = RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.1"),
            key_epoch: 2,
            message_id: id("message.1"),
            sequence: 3,
            expires_at_ms: 20_000,
            scope_digest: d("scope"),
            signed_body_digest: d("signed-body"),
            signature: [1; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.1"),
            profile_revision: 4,
            profile_digest: d("profile"),
            supplied_source_digest: d("supplied-source"),
            intent_digest: d("intent"),
            admitted_source_digest: d("admitted-source"),
            observed_at_unix_micros: 100_000,
            deadline_unix_micros: 10_000_001,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: id("run.durable"),
            objective_digest: d("objective"),
            hard_constraint_digest: d("hard"),
            preference_state_digest: d("preference"),
            model_tuple_digest: d("model"),
            prompt_registry_digest: d("prompt"),
            artifact_set_digest: d("artifacts"),
            authority_epoch: 7,
            generation: 3,
            fence_digest: d("fence"),
        },
        runtime_body_digest: d("body"),
        objective_semantic_bytes: vec![1],
        objective_function_v1_digest: d("objective-v1"),
        objective_function_v1_bytes: vec![2],
    };
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let receipt = coordinator
        .start_revalidated_run_start(100, &record)
        .expect("admit durable run start");
    let retained = coordinator.run("run.durable").expect("retained run");
    assert_eq!(receipt, retained);
    let current = coordinator.runs.get("run.durable").expect("record");
    assert_eq!(
        current.snapshot.request_digest,
        record.admission.admitted_source_digest.to_string()
    );
    assert_eq!(
        current.snapshot.fence_digest,
        record.snapshot.fence_digest.to_string()
    );
    assert_eq!(current.snapshot.deadline_ms, 10_001);
}

#[test]
fn revalidated_durable_explicit_abstain_never_enters_runtime_admission() {
    let id = |value: &str| StableId::new(value).expect("stable id");
    let d = |value: &str| Digest32::of_bytes(value.as_bytes());
    let record = RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.1"),
            key_epoch: 2,
            message_id: id("message.2"),
            sequence: 4,
            expires_at_ms: 20_000,
            scope_digest: d("scope"),
            signed_body_digest: d("signed-body"),
            signature: [1; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.1"),
            profile_revision: 4,
            profile_digest: d("profile"),
            supplied_source_digest: d("supplied-source"),
            intent_digest: d("intent"),
            admitted_source_digest: d("admitted-source"),
            observed_at_unix_micros: 100_000,
            deadline_unix_micros: 10_000_001,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::ExplicitAbstain,
        snapshot: RunStartSnapshotV1 {
            run_id: id("run.abstain"),
            objective_digest: d("objective"),
            hard_constraint_digest: d("hard"),
            preference_state_digest: d("preference"),
            model_tuple_digest: d("model"),
            prompt_registry_digest: d("prompt"),
            artifact_set_digest: d("artifacts"),
            authority_epoch: 7,
            generation: 3,
            fence_digest: d("fence"),
        },
        runtime_body_digest: d("body"),
        objective_semantic_bytes: vec![1],
        objective_function_v1_digest: d("objective-v1"),
        objective_function_v1_bytes: vec![2],
    };
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    assert_eq!(
        coordinator.start_revalidated_run_start(100, &record),
        Err(AgentRunError::InvalidRunStart("objective disposition"))
    );
    assert_eq!(coordinator.run("run.abstain"), None);
}

#[test]
fn rejected_terminal_observation_preserves_recovered_uncertainty() {
    for phase in [RunPhase::Cancelled, RunPhase::Succeeded, RunPhase::Failed] {
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
        let recovered = coordinator
            .recover_indeterminate(RunRecovery {
                snapshot: snapshot(),
                revision: u64::MAX,
                context_digest: digest('7'),
                compilation_receipt_digest: digest('8'),
                cancel_reason: Some("process_restart".to_string()),
            })
            .expect("retain unresolved recovery");

        for _ in 0..2 {
            assert_eq!(
                coordinator.observe_terminal(
                    "run.1",
                    u64::MAX,
                    phase,
                    /*terminal_observed*/ true,
                ),
                Err(AgentRunError::ArithmeticOverflow)
            );
            assert_eq!(coordinator.run("run.1"), Some(recovered.clone()));
            assert_eq!(coordinator.active_run_count(), 1);
            assert_eq!(coordinator.unresolved_run_count(), 1);
            assert_eq!(
                coordinator.remove_closed_run("run.1", u64::MAX),
                Err(AgentRunError::InvalidTransition)
            );
            assert_eq!(
                coordinator.mark_dispatched(/*now_ms*/ 100, "run.1", u64::MAX),
                Err(AgentRunError::InvalidTransition)
            );
        }
    }
}

#[test]
fn last_available_revision_accepts_terminal_observation_once() {
    for phase in [RunPhase::Cancelled, RunPhase::Succeeded, RunPhase::Failed] {
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
        let recovered = coordinator
            .recover_indeterminate(RunRecovery {
                snapshot: snapshot(),
                revision: u64::MAX - 1,
                context_digest: digest('7'),
                compilation_receipt_digest: digest('8'),
                cancel_reason: Some("process_restart".to_string()),
            })
            .expect("retain unresolved recovery");
        let terminal = coordinator
            .observe_terminal(
                "run.1",
                recovered.revision,
                phase,
                /*terminal_observed*/ true,
            )
            .expect("observe terminal with final revision");
        let mut expected = recovered;
        expected.revision = u64::MAX;
        expected.phase = phase;
        expected.terminal_observed = true;
        assert_eq!(terminal, expected);
        assert_eq!(coordinator.active_run_count(), 0);
        assert_eq!(coordinator.unresolved_run_count(), 0);

        let repeated = coordinator
            .observe_terminal(
                "run.1",
                u64::MAX - 1,
                phase,
                /*terminal_observed*/ true,
            )
            .expect("reconcile exact repeated observation without another revision");
        expected.idempotent = true;
        assert_eq!(repeated, expected);
        assert_eq!(
            coordinator
                .remove_closed_run("run.1", u64::MAX)
                .expect("release actual closed run"),
            terminal
        );
    }
}

fn dispatched_coordinator_with_deadline(deadline_ms: u64) -> AgentRunCoordinator {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let mut run = snapshot();
    run.deadline_ms = deadline_ms;
    coordinator.start_run(/*now_ms*/ 100, run).expect("admit run");
    let mut context = attachment();
    context.deadline_ms = deadline_ms;
    coordinator
        .attach_context(/*now_ms*/ 200, /*expected_revision*/ 1, context)
        .expect("attach context");
    coordinator
        .mark_dispatched(/*now_ms*/ 300, "run.1", /*expected_revision*/ 2)
        .expect("dispatch");
    coordinator
}

#[test]
fn cancellation_deadline_overflow_preserves_dispatched_run() {
    let mut coordinator = dispatched_coordinator_with_deadline(u64::MAX);
    let before = coordinator.run("run.1");
    let now_ms = u64::MAX - CANCEL_ACK_TIMEOUT_MS + 1;
    assert_eq!(
        coordinator.cancel_run(now_ms, "run.1", /*expected_revision*/ 3, "operator_request"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(coordinator.run("run.1"), before);
    assert_eq!(
        coordinator.begin_drain(now_ms, "agentd_draining"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert!(!coordinator.admissions_open());
    assert_eq!(coordinator.run("run.1"), before);
    assert_eq!(
        coordinator.expire_deadlines(u64::MAX),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(coordinator.run("run.1"), before);
    assert_eq!(coordinator.active_run_count(), 1);
    assert_eq!(coordinator.unresolved_run_count(), 1);
}

#[test]
fn last_representable_cancel_deadline_remains_reconcilable() {
    let mut coordinator = dispatched_coordinator_with_deadline(u64::MAX);
    let now_ms = u64::MAX - CANCEL_ACK_TIMEOUT_MS;
    let mut expected = coordinator.run("run.1").expect("dispatched run");
    expected.revision += 1;
    expected.phase = RunPhase::Cancelling;
    expected.cancel_reason = Some("operator_request".to_string());
    expected.cancel_ack_deadline_ms = Some(u64::MAX);
    assert_eq!(
        coordinator.cancel_run(now_ms, "run.1", /*expected_revision*/ 3, "operator_request"),
        Ok((CancellationDisposition::CancellingAfterDispatch, expected.clone()))
    );
    assert_eq!(coordinator.expire_deadlines(u64::MAX), Ok(1));
    expected.revision += 1;
    expected.phase = RunPhase::Indeterminate;
    expected.cancel_ack_deadline_ms = None;
    assert_eq!(coordinator.run("run.1"), Some(expected));
    assert_eq!(coordinator.active_run_count(), 1);
    assert_eq!(coordinator.unresolved_run_count(), 1);
}

#[test]
fn revision_overflow_preserves_pre_dispatch_state() {
    for phase in [RunPhase::Admitted, RunPhase::ContextAttached] {
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
        coordinator
            .start_run(/*now_ms*/ 100, snapshot())
            .expect("admit run");
        if phase == RunPhase::ContextAttached {
            coordinator
                .attach_context(/*now_ms*/ 200, /*expected_revision*/ 1, attachment())
                .expect("attach context");
        }
        // Earlier phases do not have a public recovery constructor. Inject
        // revision exhaustion only to exercise their checked transition boundary.
        coordinator.runs.get_mut("run.1").expect("run").revision = u64::MAX;
        let before = coordinator.run("run.1");
        let result = if phase == RunPhase::Admitted {
            coordinator.attach_context(/*now_ms*/ 300, u64::MAX, attachment())
        } else {
            coordinator.mark_dispatched(/*now_ms*/ 300, "run.1", u64::MAX)
        };
        assert_eq!(result, Err(AgentRunError::ArithmeticOverflow));
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.cancel_run(/*now_ms*/ 400, "run.1", u64::MAX, "operator_request"),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.expire_deadlines(/*now_ms*/ 10_000),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.begin_drain(/*now_ms*/ 400, "agentd_draining"),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert!(!coordinator.admissions_open());
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(coordinator.active_run_count(), 1);
        assert_eq!(coordinator.unresolved_run_count(), 0);
    }
}

#[test]
fn revision_overflow_preserves_dispatched_and_cancelling_state() {
    for phase in [RunPhase::Dispatched, RunPhase::Cancelling] {
        let mut coordinator = dispatched_coordinator_with_deadline(/*deadline_ms*/ 10_000);
        if phase == RunPhase::Cancelling {
            coordinator
                .cancel_run(/*now_ms*/ 400, "run.1", /*expected_revision*/ 3, "operator_request")
                .expect("cancel after dispatch");
        }
        coordinator.runs.get_mut("run.1").expect("run").revision = u64::MAX;
        let before = coordinator.run("run.1");
        let now_ms = if phase == RunPhase::Cancelling { 3_400 } else { 500 };
        assert_eq!(
            coordinator.cancel_run(now_ms, "run.1", u64::MAX, "operator_request"),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.observe_terminal(
                "run.1",
                u64::MAX,
                RunPhase::Indeterminate,
                /*terminal_observed*/ false,
            ),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.expire_deadlines(/*now_ms*/ 10_000),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.begin_drain(/*now_ms*/ 500, "agentd_draining"),
            if phase == RunPhase::Dispatched {
                Err(AgentRunError::ArithmeticOverflow)
            } else {
                Ok(1)
            }
        );
        assert!(!coordinator.admissions_open());
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(
            coordinator.mark_unresolved_indeterminate("process_lost"),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run("run.1"), before);
        assert_eq!(coordinator.active_run_count(), 1);
        assert_eq!(coordinator.unresolved_run_count(), 1);
    }
}

#[test]
fn bulk_deadline_error_retains_completed_prefix_and_failed_record() {
    for drain in [false, true] {
        let mut coordinator = dispatched_coordinator_with_deadline(u64::MAX);
        let failed = coordinator.run("run.1");
        let mut first = snapshot();
        first.run_id = "run.0".to_string();
        let mut completed = coordinator
            .start_run(/*now_ms*/ 100, first)
            .expect("admit first run");
        let result = if drain {
            coordinator.begin_drain(u64::MAX, "agentd_draining")
        } else {
            coordinator.expire_deadlines(u64::MAX)
        };
        assert_eq!(result, Err(AgentRunError::ArithmeticOverflow));
        completed.revision += 1;
        completed.phase = RunPhase::Cancelled;
        completed.cancel_reason = Some(DEADLINE_CANCEL_REASON.to_string());
        completed.terminal_observed = true;
        assert_eq!(coordinator.run("run.0"), Some(completed));
        assert_eq!(coordinator.run("run.1"), failed);
        assert_eq!(coordinator.admissions_open(), !drain);
        assert_eq!(coordinator.active_run_count(), 1);
        assert_eq!(coordinator.unresolved_run_count(), 1);
    }
}

#[test]
fn bulk_unknown_error_retains_completed_prefix_and_failed_record() {
    let mut coordinator = dispatched_coordinator_with_deadline(/*deadline_ms*/ 10_000);
    coordinator.runs.get_mut("run.1").expect("run").revision = u64::MAX;
    let failed = coordinator.run("run.1");
    let mut first = snapshot();
    first.run_id = "run.0".to_string();
    coordinator.start_run(/*now_ms*/ 100, first).expect("admit first run");
    let mut context = attachment();
    context.run_id = "run.0".to_string();
    coordinator
        .attach_context(/*now_ms*/ 200, /*expected_revision*/ 1, context)
        .expect("attach first context");
    let mut completed = coordinator
        .mark_dispatched(/*now_ms*/ 300, "run.0", /*expected_revision*/ 2)
        .expect("dispatch first run");
    assert_eq!(
        coordinator.mark_unresolved_indeterminate("process_lost"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    completed.revision += 1;
    completed.phase = RunPhase::Indeterminate;
    completed.cancel_reason = Some("process_lost".to_string());
    assert_eq!(coordinator.run("run.0"), Some(completed));
    assert_eq!(coordinator.run("run.1"), failed);
    assert_eq!(coordinator.active_run_count(), 2);
    assert_eq!(coordinator.unresolved_run_count(), 2);
}
