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

/// Tests authenticate the complete statement against an independently held
/// expected value. This fixture is not a production authority verifier.
struct ExpectedObservation {
    statement: RunReconciliation,
    revoked: bool,
    calls: usize,
}

impl RunReconciliationVerifier for ExpectedObservation {
    fn verify_current_observation(
        &mut self,
        _now_ms: u64,
        observation: &RunReconciliation,
    ) -> Result<(), AgentRunError> {
        self.calls += 1;
        if self.revoked || observation != &self.statement {
            Err(AgentRunError::ReconciliationRejected)
        } else {
            Ok(())
        }
    }
}

fn indeterminate_run() -> AgentRunCoordinator {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    coordinator.start_run(/*now_ms*/ 100, snapshot()).unwrap();
    coordinator
        .attach_context(/*expected_revision*/ 1, attachment())
        .unwrap();
    coordinator
        .mark_dispatched("run.1", /*expected_revision*/ 2)
        .unwrap();
    coordinator
        .observe_terminal(
            "run.1",
            /*expected_revision*/ 3,
            RunPhase::Indeterminate,
            /*terminal_observed*/ false,
        )
        .unwrap();
    coordinator
}

fn reconciliation(outcome: ReconciledRunOutcome) -> RunReconciliation {
    RunReconciliation {
        composition: composition(),
        snapshot: snapshot(),
        expected_revision: 4,
        current_authority_epoch: 8,
        observation_id: "observation.1".to_string(),
        evidence_digest: digest('a'),
        observed_at_ms: 20_000,
        valid_until_ms: 30_000,
        outcome,
    }
}

#[test]
fn indeterminate_requires_current_verified_reconciliation_even_after_deadline() {
    for (outcome, phase, observed) in [
        (ReconciledRunOutcome::Succeeded, RunPhase::Succeeded, true),
        (ReconciledRunOutcome::Failed, RunPhase::Failed, true),
        (ReconciledRunOutcome::Cancelled, RunPhase::Cancelled, true),
        (
            ReconciledRunOutcome::Quarantined,
            RunPhase::Quarantined,
            false,
        ),
    ] {
        let mut coordinator = indeterminate_run();
        let before = coordinator.run("run.1").unwrap();
        assert_eq!(
            coordinator.cancel_run("run.1", /*expected_revision*/ 4),
            Ok((
                CancellationDisposition::ReconciliationRequired,
                before.clone()
            ))
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", /*expected_revision*/ 4),
            Err(AgentRunError::InvalidTransition)
        );
        let statement = reconciliation(outcome);
        let mut verifier = ExpectedObservation {
            statement: statement.clone(),
            revoked: false,
            calls: 0,
        };
        let settled = coordinator
            .reconcile_run(/*now_ms*/ 25_000, statement.clone(), &mut verifier)
            .unwrap();
        assert_eq!(
            settled,
            RunReceipt {
                revision: 5,
                phase,
                terminal_observed: observed,
                ..before
            }
        );
        let replay = coordinator
            .reconcile_run(/*now_ms*/ 25_001, statement.clone(), &mut verifier)
            .unwrap();
        assert_eq!(
            replay,
            RunReceipt {
                idempotent: true,
                ..settled.clone()
            }
        );
        assert_eq!(verifier.calls, 2);
        verifier.revoked = true;
        assert_eq!(
            coordinator.reconcile_run(/*now_ms*/ 25_002, statement, &mut verifier),
            Err(AgentRunError::ReconciliationRejected)
        );
        assert_eq!(coordinator.run("run.1"), Some(settled.clone()));
        assert_eq!(
            coordinator.remove_closed_run("run.1", /*expected_revision*/ 5),
            Ok(settled)
        );
    }
}

#[test]
fn reconciliation_rejects_mixed_stale_expired_or_unverified_evidence_atomically() {
    let base = reconciliation(ReconciledRunOutcome::Succeeded);
    let mut cases = Vec::new();
    let mut changed = base.clone();
    changed.composition.agentd_generation += 1;
    cases.push((changed, AgentRunError::StaleComposition));
    let mut changed = base.clone();
    changed.snapshot.request_digest = digest('b');
    cases.push((changed, AgentRunError::MixedSnapshot));
    let mut changed = base.clone();
    changed.current_authority_epoch = 6;
    cases.push((changed, AgentRunError::StaleAuthorityEpoch));
    let mut changed = base.clone();
    changed.valid_until_ms = 25_000;
    cases.push((changed, AgentRunError::InvalidObservationWindow));
    let mut changed = base.clone();
    changed.observed_at_ms = 25_001;
    cases.push((changed, AgentRunError::InvalidObservationWindow));
    let mut changed = base.clone();
    changed.evidence_digest = digest('0');
    cases.push((
        changed,
        AgentRunError::InvalidDigest("reconciliation evidence"),
    ));
    let mut changed = base.clone();
    changed.evidence_digest = digest('b');
    cases.push((changed, AgentRunError::ReconciliationRejected));
    for (statement, error) in cases {
        let mut coordinator = indeterminate_run();
        let before = coordinator.runs.clone();
        let mut verifier = ExpectedObservation {
            statement: base.clone(),
            revoked: false,
            calls: 0,
        };
        assert_eq!(
            coordinator.reconcile_run(/*now_ms*/ 25_000, statement, &mut verifier),
            Err(error)
        );
        assert_eq!(coordinator.runs, before);
    }
    for revision in [3, u64::MAX] {
        let mut coordinator = indeterminate_run();
        if revision == u64::MAX {
            coordinator.runs.get_mut("run.1").unwrap().revision = revision;
        }
        let mut statement = base.clone();
        statement.expected_revision = revision;
        let mut verifier = ExpectedObservation {
            statement: statement.clone(),
            revoked: false,
            calls: 0,
        };
        let before = coordinator.runs.clone();
        let expected = if revision == u64::MAX {
            AgentRunError::ArithmeticOverflow
        } else {
            AgentRunError::StaleRevision
        };
        assert_eq!(
            coordinator.reconcile_run(/*now_ms*/ 25_000, statement, &mut verifier),
            Err(expected)
        );
        assert_eq!(coordinator.runs, before);
    }
}

#[test]
fn reconciliation_releases_capacity_without_forgetting_unresolved_runs() {
    let mut coordinator = indeterminate_run();
    for index in 1..MAX_ACTIVE_RUNS {
        let mut request = snapshot();
        request.run_id = format!("waiting.{index}");
        coordinator.start_run(/*now_ms*/ 100, request).unwrap();
    }
    let mut extra = snapshot();
    extra.run_id = "extra".to_string();
    assert_eq!(
        coordinator.start_run(/*now_ms*/ 100, extra.clone()),
        Err(AgentRunError::CapacityExceeded)
    );
    let statement = reconciliation(ReconciledRunOutcome::Quarantined);
    let mut verifier = ExpectedObservation {
        statement: statement.clone(),
        revoked: false,
        calls: 0,
    };
    coordinator
        .reconcile_run(/*now_ms*/ 25_000, statement, &mut verifier)
        .unwrap();
    assert_eq!(coordinator.active_run_count(), MAX_ACTIVE_RUNS - 1);
    // Admission uses its own clock/deadline, independent of the recovered run.
    extra.deadline_ms = 40_000;
    coordinator.start_run(/*now_ms*/ 25_000, extra).unwrap();
    let quarantined = coordinator.run("run.1").unwrap();
    assert_eq!(quarantined.phase, RunPhase::Quarantined);
    assert!(!quarantined.terminal_observed);
    assert_eq!(
        coordinator
            .cancel_run("run.1", /*expected_revision*/ 5)
            .unwrap()
            .0,
        CancellationDisposition::AlreadyQuarantined
    );
}

#[test]
fn context_idempotence_never_accepts_a_mixed_snapshot() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    coordinator.start_run(/*now_ms*/ 100, snapshot()).unwrap();
    coordinator
        .attach_context(/*expected_revision*/ 1, attachment())
        .unwrap();
    let before = coordinator.runs.clone();
    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(/*expected_revision*/ 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );
    assert_eq!(coordinator.runs, before);
}

#[test]
fn revision_overflow_does_not_partially_mutate_context_or_phase() {
    for phase in [
        RunPhase::Admitted,
        RunPhase::ContextAttached,
        RunPhase::Dispatched,
    ] {
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
        coordinator.start_run(/*now_ms*/ 100, snapshot()).unwrap();
        let record = coordinator.runs.get_mut("run.1").unwrap();
        record.phase = phase;
        record.revision = u64::MAX;
        let before = coordinator.runs.clone();
        let result = match phase {
            RunPhase::Admitted => coordinator.attach_context(u64::MAX, attachment()),
            RunPhase::ContextAttached => coordinator.mark_dispatched("run.1", u64::MAX),
            RunPhase::Dispatched => coordinator.observe_terminal(
                "run.1",
                u64::MAX,
                RunPhase::Succeeded,
                /*terminal_observed*/ true,
            ),
            _ => unreachable!("only mutable transitions are exercised"),
        };
        assert_eq!(result, Err(AgentRunError::ArithmeticOverflow));
        assert_eq!(coordinator.runs, before);
        assert_eq!(
            coordinator.cancel_run("run.1", u64::MAX),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.runs, before);
    }
}
