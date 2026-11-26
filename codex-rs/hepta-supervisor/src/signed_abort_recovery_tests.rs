use super::*;
use crate::DurableReleaseTransaction;
use crate::H7H89ProductionTransition;
use crate::ProductionMutationStatus;
use crate::ReleaseTransactionKind;
use crate::ReleaseTransactionPhase;
use crate::SignedIntentRecoveryDirective;
use crate::SignedIntentStatus;
use crate::SignedSupervisorIntent;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::restart_budget::claim_restart;
use crate::restart_journal::read_main_restart_budget;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use crate::signed_intent::write_recovery_directive;
use pretty_assertions::assert_eq;

#[test]
fn rejected_adoption_retains_the_lease_until_absence_is_proven()
-> Result<(), Box<dyn std::error::Error>> {
    for rejected_role in [FakeRole::Agentd, FakeRole::Matrixd] {
        let (fleet, control, supervisor, now) = ready_paired_supervisor("signed-abort-rejected")?;
        let record = fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .cloned()
            .expect("agent");
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"rejected-adoption-grant"),
            fleet.first.to_string(),
            H7H89ProductionTransition::Upgrade,
            "signed-abort-rejected",
            "target-release",
            4,
            record.lifecycle.generation,
            9,
            SignedIntentStatus::Queued,
        )?;
        write_intent(record.layout.run_root(), &intent)?;
        write_recovery_directive(
            record.layout.run_root(),
            &SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?,
        )?;
        match rejected_role {
            FakeRole::Agentd => {
                control.reject_adoption(fleet.first.clone());
                control.set_matrix_exit(&fleet.first);
            }
            FakeRole::Matrixd => {
                control
                    .world
                    .lock()
                    .expect("fake world lock")
                    .reject_matrix_adoption
                    .insert(fleet.first.clone());
                control.set_exit(&fleet.first);
            }
        }
        drop(supervisor);

        // Failed exact identity proof grants neither signal authority nor
        // evidence of exit. Reopening must keep the same digest and lease.
        for _ in 0..2 {
            let (mut recovered, report) =
                Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
            assert_eq!(report, TickReport::default());
            assert!(recovered.production_recovery_required(&fleet.first)?);
            assert_eq!(read_intent(record.layout.run_root())?, Some(intent.clone()));
            assert_eq!(
                read_lease(record.layout.run_root())?.is_some(),
                rejected_role == FakeRole::Agentd,
            );
            assert_eq!(
                read_matrix_lease(record.layout.matrixd_process_lease())?.is_some(),
                rejected_role == FakeRole::Matrixd,
            );
            assert_eq!(
                recovered.tick(now + Duration::from_secs(2)),
                TickReport::default()
            );
            assert_eq!(control.spawn_count(&fleet.first), 1);
            assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
            assert_eq!(control.counts(&fleet.first), (0, 0, 0));
            assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 0));
        }
        control.set_exit(&fleet.first);
        control.set_matrix_exit(&fleet.first);
        {
            let mut world = control.world.lock().expect("fake world lock");
            world.reject_adoption.remove(&fleet.first);
            world.reject_matrix_adoption.remove(&fleet.first);
        }
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert!(!recovered.production_recovery_required(&fleet.first)?);
        assert_eq!(
            read_intent(record.layout.run_root())?,
            Some(intent.with_status(SignedIntentStatus::Aborted)?),
        );
        assert_eq!(
            recovered.tick(now + Duration::from_secs(2)),
            TickReport::default()
        );
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    }
    Ok(())
}

#[test]
fn exact_abort_waits_for_both_children_and_survives_repeated_recovery()
-> Result<(), Box<dyn std::error::Error>> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("signed-abort-pair")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"paired-grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "signed-abort-pair",
        "target-release",
        4,
        record.lifecycle.generation,
        9,
        SignedIntentStatus::Queued,
    )?;
    write_intent(record.layout.run_root(), &intent)?;
    write_recovery_directive(
        record.layout.run_root(),
        &SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?,
    )?;
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(recovered.production_recovery_required(&fleet.first)?);
    assert_eq!(
        recovered
            .production_mutation_state(&fleet.first)?
            .expect("mutation")
            .receipt
            .status,
        ProductionMutationStatus::RecoveryRequired,
    );
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 1));
    assert_eq!(read_intent(record.layout.run_root())?, Some(intent.clone()));
    assert_eq!(
        recovered.tick(now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);

    // Main exits first. An adopted Matrix child must keep both its handle and
    // lease until its own exit is observed, even though the agent is Failed.
    control.set_exit(&fleet.first);
    drop(recovered);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(recovered.production_recovery_required(&fleet.first)?);
    let snapshot = recovered.snapshot(&fleet.first).expect("snapshot");
    assert!(!snapshot.active);
    assert!(snapshot.matrix.active);
    assert!(!snapshot.matrix.healthy);
    assert!(read_lease(record.layout.run_root())?.is_none());
    assert!(read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    assert_eq!(read_intent(record.layout.run_root())?, Some(intent.clone()));
    assert_eq!(
        recovered.tick(now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);

    control.set_matrix_exit(&fleet.first);
    drop(recovered);
    for _ in 0..2 {
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert!(!recovered.production_recovery_required(&fleet.first)?);
        assert_eq!(
            read_intent(record.layout.run_root())?,
            Some(intent.with_status(SignedIntentStatus::Aborted)?),
        );
        assert!(read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
        assert_eq!(
            recovered.tick(now + Duration::from_secs(2)),
            TickReport::default()
        );
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
        assert_eq!(control.counts(&fleet.second), (0, 0, 0));
        assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
    }
    Ok(())
}

#[test]
fn abort_clears_persisted_pending_restart_without_resetting_charges()
-> Result<(), Box<dyn std::error::Error>> {
    for phase in [
        ReleaseTransactionPhase::Prepared,
        ReleaseTransactionPhase::Aborted,
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        supervisor.start_release(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "signed-pending-source")?,
            now,
        )?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let record = fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .cloned()
            .expect("agent");
        claim_restart(
            record.layout.run_root(),
            config().restart_max_attempts,
            config().restart_window,
            config().restart_backoff_base,
        )?;
        let budget = read_main_restart_budget(record.layout.run_root())?.expect("claimed budget");
        assert!(budget.pending);
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"pending-grant"),
            fleet.first.to_string(),
            H7H89ProductionTransition::Upgrade,
            "signed-pending-source",
            "target-release",
            4,
            record.lifecycle.generation,
            9,
            SignedIntentStatus::RecoveryRequired,
        )?;
        let transaction = DurableReleaseTransaction::new(
            fleet.first.to_string(),
            ReleaseTransactionKind::Upgrade,
            &intent.source_release,
            &intent.target_release,
            None,
            None,
            None,
            record.release_state.generation,
            intent.expected_lifecycle_generation,
        )?
        .with_authority(intent.grant_sha256.clone(), intent.authority_epoch)?
        .with_phase(phase)?;
        write_release_transaction(record.layout.run_root(), &transaction)?;
        write_intent(record.layout.run_root(), &intent)?;
        write_recovery_directive(
            record.layout.run_root(),
            &SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?,
        )?;
        control.set_exit(&fleet.first);
        drop(supervisor);

        // Cover normal abort as well as a crash after the terminal transaction
        // was published but before the matching signed intent was updated.
        for _ in 0..2 {
            let (mut recovered, report) =
                Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
            assert_eq!(report, TickReport::default());
            assert!(!recovered.production_recovery_required(&fleet.first)?);
            assert!(
                !recovered
                    .snapshot(&fleet.first)
                    .expect("snapshot")
                    .restart_pending
            );
            let recovered_budget =
                read_main_restart_budget(record.layout.run_root())?.expect("retained budget");
            assert_eq!(
                (
                    recovered_budget.attempts,
                    recovered_budget.window_started_unix_ms,
                    recovered_budget.pending
                ),
                (budget.attempts, budget.window_started_unix_ms, false),
            );
            assert_eq!(
                read_intent(record.layout.run_root())?,
                Some(intent.with_status(SignedIntentStatus::Aborted)?),
            );
            assert_eq!(
                read_release_transaction(record.layout.run_root())?,
                Some(transaction.with_phase(ReleaseTransactionPhase::Aborted)?),
            );
            assert_eq!(
                recovered.tick(now + Duration::from_secs(2)),
                TickReport::default()
            );
            assert_eq!(control.spawn_count(&fleet.first), 1);
            assert!(!recovered.snapshot(&fleet.first).expect("snapshot").active);
        }
    }
    Ok(())
}

#[test]
fn stale_abort_digest_cannot_terminalize_a_different_intent()
-> Result<(), Box<dyn std::error::Error>> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Failed,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"new-grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source-release",
        "target-release",
        4,
        record.lifecycle.generation,
        9,
        SignedIntentStatus::Queued,
    )?;
    write_intent(record.layout.run_root(), &intent)?;
    write_recovery_directive(
        record.layout.run_root(),
        &SignedIntentRecoveryDirective::abort(Sha256Digest::for_bytes(b"old-intent"))?,
    )?;
    let now = Instant::now();
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(recovered.production_recovery_required(&fleet.first)?);
    assert_eq!(
        read_intent(record.layout.run_root())?,
        Some(intent.with_status(SignedIntentStatus::RecoveryRequired)?),
    );
    assert!(matches!(
        recovered.start_release(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "new-release")?,
            now
        ),
        Err(SupervisorError::SignedIntentRecoveryRequired(_)),
    ));
    assert_eq!(
        recovered.tick(now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 0);
    Ok(())
}

#[test]
fn abort_cannot_close_an_unrelated_release_transaction() -> Result<(), Box<dyn std::error::Error>> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Failed,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"intent-grant"),
        fleet.first.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source-release",
        "target-release",
        4,
        record.lifecycle.generation,
        9,
        SignedIntentStatus::RecoveryRequired,
    )?;
    let transaction = DurableReleaseTransaction::new(
        fleet.first.to_string(),
        ReleaseTransactionKind::Upgrade,
        &intent.source_release,
        &intent.target_release,
        None,
        None,
        None,
        record.release_state.generation,
        intent.expected_lifecycle_generation,
    )?
    .with_authority(
        Sha256Digest::for_bytes(b"unrelated-grant"),
        intent.authority_epoch,
    )?;
    write_release_transaction(record.layout.run_root(), &transaction)?;
    write_intent(record.layout.run_root(), &intent)?;
    write_recovery_directive(
        record.layout.run_root(),
        &SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?,
    )?;
    assert!(matches!(
        Supervisor::recover(
            fleet.registry.clone(),
            control.driver(),
            config(),
            Instant::now()
        ),
        Err(SupervisorError::Invalid(_)),
    ));
    assert_eq!(read_intent(record.layout.run_root())?, Some(intent));
    assert_eq!(
        read_release_transaction(record.layout.run_root())?,
        Some(transaction.with_phase(ReleaseTransactionPhase::RecoveryRequired)?),
    );
    assert_eq!(control.spawn_count(&fleet.first), 0);
    Ok(())
}
