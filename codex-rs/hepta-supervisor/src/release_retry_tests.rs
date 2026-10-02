//! Live transition retries over real journals and the shared process double.
//! Injected filesystem failures do not constitute target-host power-loss proof.

use super::*;

use pretty_assertions::assert_eq;
use std::io::ErrorKind;

use crate::H7H89ProductionTransition;
use crate::ReleaseTransactionPhase;
use crate::SignedIntentStatus;
use crate::SignedSupervisorIntent;
use crate::durability::with_qualification_fault;
use crate::durability::with_qualification_fault_after;
use crate::release_transaction::read_release_transaction;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

fn start_source(
    fleet: &TestFleet,
    control: &FakeControl,
    now: Instant,
) -> Result<Supervisor<FakeDriver>, SupervisorError> {
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(
        &fleet.first,
        admitted_release(fleet, &fleet.first, "retry-source")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    Ok(supervisor)
}

fn queue_signed_change(
    supervisor: &mut Supervisor<FakeDriver>,
    fleet: &TestFleet,
    target: AgentRelease,
    now: Instant,
    transition: H7H89ProductionTransition,
) -> Result<(), SupervisorError> {
    // Exercise the post-verification journal owner; grant cryptography has its
    // own qualification tests and this helper confers no production authority.
    supervisor.with_slot(&fleet.first, |supervisor, slot| {
        let record = supervisor.record(&fleet.first)?;
        let grant = Sha256Digest::for_bytes(b"release-retry-qualified-grant");
        let intent = SignedSupervisorIntent::new(
            grant.clone(),
            fleet.first.to_string(),
            transition,
            slot.active_release.as_ref().expect("source").identity(),
            target.identity(),
            slot.control_revision,
            record.lifecycle.generation,
            /*authority_epoch*/ 7,
            SignedIntentStatus::Queued,
        )
        .expect("signed intent");
        write_intent(record.layout.run_root(), &intent).expect("persist qualification intent");
        slot.signed_intent = Some(intent);
        supervisor.upgrade_slot(
            &fleet.first,
            slot,
            target,
            now,
            transition == H7H89ProductionTransition::Rollback,
            Some((grant, 7)),
        )
    })
}

#[test]
fn terminal_release_journal_failure_retries_without_duplicate_commit_or_spawn()
-> Result<(), SupervisorError> {
    for point in [
        "release_transaction.file_write",
        "release_transaction.rename",
        "release_transaction.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        supervisor.upgrade(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "retry-target")?,
            now,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        let failed = with_qualification_fault(point, ErrorKind::Other, || supervisor.tick(now));
        assert_eq!(failed.faults.len(), 1, "{point}");
        let pending = supervisor.snapshot(&fleet.first).expect("pending release");
        assert!(pending.release_change_pending, "{point}");
        assert!(
            !pending.events.iter().any(|event| {
                matches!(event.kind, SupervisorEventKind::UpgradeCommitted { .. })
            })
        );
        let record = supervisor.record(&fleet.first)?;
        let committed_state = record.release_state.clone();
        let spawns = control.spawn_count(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let done = supervisor
            .snapshot(&fleet.first)
            .expect("completed release");
        assert!(!done.release_change_pending);
        assert_eq!(control.spawn_count(&fleet.first), spawns);
        assert_eq!(
            supervisor.record(&fleet.first)?.release_state,
            committed_state
        );
        assert_eq!(
            done.events
                .iter()
                .filter(|event| {
                    matches!(event.kind, SupervisorEventKind::UpgradeCommitted { .. })
                })
                .count(),
            1
        );
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("terminal transaction")
                .expect("transaction")
                .phase,
            ReleaseTransactionPhase::Committed
        );
    }
    Ok(())
}

#[test]
fn signed_receipt_failure_retries_after_terminal_release_journal() -> Result<(), SupervisorError> {
    for point in [
        "signed_intent.file_write",
        "signed_intent.file_sync",
        "signed_intent.rename",
        "signed_intent.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        queue_signed_change(
            &mut supervisor,
            &fleet,
            admitted_release(&fleet, &fleet.first, "signed-retry-target")?,
            now,
            H7H89ProductionTransition::Upgrade,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        let failed = with_qualification_fault(point, ErrorKind::Other, || supervisor.tick(now));
        assert_eq!(failed.faults.len(), 1, "{point}");
        assert!(
            supervisor
                .snapshot(&fleet.first)
                .expect("snapshot")
                .release_change_pending
        );
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("transaction read")
                .expect("transaction")
                .phase,
            ReleaseTransactionPhase::Committed
        );
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert!(
            !supervisor
                .snapshot(&fleet.first)
                .expect("snapshot")
                .release_change_pending
        );
        assert_eq!(
            read_intent(record.layout.run_root())
                .expect("intent read")
                .expect("intent")
                .status,
            SignedIntentStatus::Committed
        );
        assert_eq!(control.spawn_count(&fleet.first), 2);
    }
    Ok(())
}

#[test]
fn target_start_journal_failure_keeps_transition_for_next_empty_runtime_tick()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    let target = admitted_release(&fleet, &fleet.first, "empty-runtime-target")?;
    supervisor.upgrade(&fleet.first, target.clone(), now)?;
    control.set_drained(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_exit(&fleet.first);
    let failed =
        with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
            supervisor.tick(now)
        });
    assert_eq!(failed.faults.len(), 1);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("snapshot")
            .release_change_pending
    );
    // An ordinary caller cannot hijack the retained transition while its
    // predecessor has exited and the target journal writer is being retried.
    let before = supervisor.record(&fleet.first)?;
    assert!(matches!(
        supervisor.start(&fleet.first, command()?, now),
        Err(SupervisorError::Invalid(_))
    ));
    assert!(matches!(
        supervisor.start_release(&fleet.first, target, now),
        Err(SupervisorError::Invalid(_))
    ));
    #[cfg(unix)]
    assert!(matches!(
        supervisor.preflight_start(&fleet.first),
        Err(SupervisorError::Invalid(_))
    ));
    let after = supervisor.record(&fleet.first)?;
    assert_eq!(after.lifecycle, before.lifecycle);
    assert_eq!(after.release_state, before.release_state);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("snapshot")
            .active_release
            .as_deref(),
        Some("empty-runtime-target")
    );
    Ok(())
}

#[test]
fn automatic_rollback_phase_write_failure_retains_source_restoration() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "unhealthy-target")?,
        now,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    let after_timeout = now + Duration::from_millis(11);
    assert_eq!(supervisor.tick(after_timeout), TickReport::default());
    control.set_exit(&fleet.first);
    let failed =
        with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
            supervisor.tick(after_timeout)
        });
    assert_eq!(failed.faults.len(), 1);
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert_eq!(supervisor.tick(after_timeout), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 3);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(after_timeout), TickReport::default());
    let restored = supervisor.snapshot(&fleet.first).expect("snapshot");
    assert_eq!(restored.active_release.as_deref(), Some("retry-source"));
    assert!(!restored.release_change_pending);
    Ok(())
}

#[test]
fn signed_receipt_retry_after_target_exit_does_not_rollback_a_committed_release()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    queue_signed_change(
        &mut supervisor,
        &fleet,
        admitted_release(&fleet, &fleet.first, "signed-exited-target")?,
        now,
        H7H89ProductionTransition::Upgrade,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    let failed = with_qualification_fault("signed_intent.file_write", ErrorKind::Other, || {
        supervisor.tick(now)
    });
    assert_eq!(failed.faults.len(), 1);
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);
    let record = supervisor.record(&fleet.first)?;
    assert_eq!(
        read_intent(record.layout.run_root())
            .expect("intent read")
            .expect("intent")
            .status,
        SignedIntentStatus::Committed
    );
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .expect("snapshot")
            .release_change_pending
    );
    Ok(())
}

#[test]
fn terminal_journal_ambiguity_then_target_exit_keeps_the_observed_healthy_outcome()
-> Result<(), SupervisorError> {
    for point in [
        "release_transaction.file_write",
        "release_transaction.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        supervisor.upgrade(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "healthy-exit-target")?,
            now,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        let failed = with_qualification_fault(point, ErrorKind::Other, || supervisor.tick(now));
        assert_eq!(failed.faults.len(), 1);
        control.set_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(control.spawn_count(&fleet.first), 2);
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("transaction read")
                .expect("transaction")
                .phase,
            ReleaseTransactionPhase::Committed
        );
        assert_eq!(
            record.release_state.current,
            Some(ReleaseId::parse("healthy-exit-target")?)
        );
    }
    Ok(())
}

#[test]
fn healthy_target_cannot_overwrite_an_unrelated_release_state_generation()
-> Result<(), SupervisorError> {
    for external_target_pair in [false, true] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        supervisor.upgrade(
            &fleet.first,
            admitted_release(&fleet, &fleet.first, "drift-target")?,
            now,
        )?;
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        let before = supervisor.record(&fleet.first)?.release_state;
        let first = fleet.registry.compare_and_set_release_state(
            &fleet.first,
            before.generation,
            Some(ReleaseId::parse("unrelated-release")?),
            None,
        )?;
        let external = if external_target_pair {
            fleet.registry.compare_and_set_release_state(
                &fleet.first,
                first.generation,
                Some(ReleaseId::parse("drift-target")?),
                Some(ReleaseId::parse("retry-source")?),
            )?
        } else {
            first
        };
        control.set_healthy(&fleet.first);
        let failed = supervisor.tick(now);
        assert_eq!(failed.faults.len(), 1);
        assert_eq!(supervisor.record(&fleet.first)?.release_state, external);
        assert!(
            supervisor
                .snapshot(&fleet.first)
                .expect("snapshot")
                .release_change_pending
        );
        assert_eq!(supervisor.tick(now).faults.len(), 1);
        assert_eq!(supervisor.record(&fleet.first)?.release_state, external);
        assert_eq!(control.spawn_count(&fleet.first), 2);
    }
    Ok(())
}

#[test]
fn failed_signed_explicit_rollback_terminalizes_restoration_of_its_source()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    let target = admitted_release(&fleet, &fleet.first, "rejected-signed-rollback-target")?;
    control.reject_spawn_program(target.command().program.clone());
    queue_signed_change(
        &mut supervisor,
        &fleet,
        target,
        now,
        H7H89ProductionTransition::Rollback,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let restored = supervisor.snapshot(&fleet.first).expect("snapshot");
    assert_eq!(restored.active_release.as_deref(), Some("retry-source"));
    assert!(!restored.release_change_pending);
    let record = supervisor.record(&fleet.first)?;
    assert_eq!(
        read_intent(record.layout.run_root())
            .expect("intent read")
            .expect("intent")
            .status,
        SignedIntentStatus::RolledBack
    );
    assert!(!supervisor.production_recovery_required(&fleet.first)?);
    // Reconstruct the cut where the rollback outcome is durable but the
    // signed receipt is still queued when a new owner starts.
    let queued = read_intent(record.layout.run_root())
        .expect("intent read")
        .expect("intent")
        .with_status(SignedIntentStatus::Queued)
        .expect("queued crash cut");
    write_intent(record.layout.run_root(), &queued).expect("write queued crash cut");
    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    assert_eq!(
        read_intent(record.layout.run_root())
            .expect("intent read")
            .expect("intent")
            .status,
        SignedIntentStatus::RolledBack
    );
    Ok(())
}

#[test]
fn healthy_active_target_does_not_complete_an_unrelated_signed_intent()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    supervisor.with_slot(&fleet.first, |supervisor, slot| {
        let record = supervisor.record(&fleet.first)?;
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"unrelated-qualified-grant"),
            fleet.first.to_string(),
            H7H89ProductionTransition::Upgrade,
            "unrelated-source",
            "retry-source",
            slot.control_revision,
            record.lifecycle.generation,
            /*authority_epoch*/ 7,
            SignedIntentStatus::Queued,
        )
        .expect("unrelated intent");
        write_intent(record.layout.run_root(), &intent).expect("persist unrelated intent");
        slot.signed_intent = Some(intent);
        Ok(())
    })?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = supervisor.record(&fleet.first)?;
    assert_eq!(
        read_intent(record.layout.run_root())
            .expect("intent read")
            .expect("intent")
            .status,
        SignedIntentStatus::Queued
    );
    Ok(())
}

#[test]
fn recovering_a_committed_target_preserves_its_rollback_predecessor_and_generation()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "recover-committed-target")?,
        now,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let committed = supervisor.record(&fleet.first)?.release_state;
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(recovered.record(&fleet.first)?.release_state, committed);
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("snapshot")
            .previous_release
            .as_deref(),
        Some("retry-source")
    );
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(recovered.record(&fleet.first)?.release_state, committed);
    assert_eq!(control.spawn_count(&fleet.first), 2);
    Ok(())
}

#[test]
fn recovering_target_running_before_release_state_cas_defers_publication_until_health()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_source(&fleet, &control, now)?;
    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "recover-before-cas-target")?,
        now,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    let source_state = supervisor.record(&fleet.first)?.release_state;
    let starting = supervisor.record(&fleet.first)?.lifecycle;
    fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Running,
    )?;
    control.set_healthy(&fleet.first);
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(recovered.record(&fleet.first)?.release_state, source_state);
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("snapshot")
            .active_release
            .as_deref(),
        Some("recover-before-cas-target")
    );
    assert_eq!(recovered.tick(now), TickReport::default());
    let record = recovered.record(&fleet.first)?;
    assert_eq!(
        record.release_state.current,
        Some(ReleaseId::parse("recover-before-cas-target")?)
    );
    assert_eq!(
        record.release_state.previous,
        Some(ReleaseId::parse("retry-source")?)
    );
    assert_eq!(record.release_state.generation, source_state.generation + 1);
    assert_eq!(
        read_release_transaction(record.layout.run_root())
            .expect("transaction read")
            .expect("transaction")
            .phase,
        ReleaseTransactionPhase::Committed
    );
    assert_eq!(control.spawn_count(&fleet.first), 2);
    Ok(())
}

#[test]
fn public_verified_grant_commits_registered_source_and_rejects_qualification_sources()
-> Result<(), SupervisorError> {
    use crate::H7H89ProductionGrantVerifier;
    use crate::signed_authority::H7H89ProductionGrantSigner;
    use codex_hepta_memory::H7ArtifactSigner;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7SignedArtifactTransition;

    for source_case in ["registered", "unregistered", "noncanonical"] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = if source_case == "registered" {
            start_source(&fleet, &control, now)?
        } else {
            if source_case == "noncanonical" {
                admitted_release(&fleet, &fleet.first, "retry-source")?;
            }
            let (mut supervisor, report) =
                Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
            assert_eq!(report, TickReport::default());
            supervisor.start_release(
                &fleet.first,
                AgentRelease::new(
                    "retry-source",
                    AgentCommand::new(fake_program("fixture-source"), Vec::new())?,
                )?,
                now,
            )?;
            control.set_healthy(&fleet.first);
            assert_eq!(supervisor.tick(now), TickReport::default());
            supervisor
        };
        if source_case == "noncanonical" {
            // The launch boundary now restores canonical catalog commands.
            // Inject a corrupted selection witness after that safe launch to
            // retain this grant admission regression's independent invariant.
            supervisor.with_slot(&fleet.first, |_supervisor, slot| {
                slot.active_release = Some(AgentRelease::new(
                    "retry-source",
                    AgentCommand::new(fake_program("fixture-source"), Vec::new())?,
                )?);
                Ok(())
            })?;
        }
        admitted_release(&fleet, &fleet.first, "verified-grant-target")?;
        let snapshot = supervisor.snapshot(&fleet.first).expect("snapshot");
        let lifecycle_generation = supervisor.record(&fleet.first)?.lifecycle.generation;

        let mut h7_runtime = H7QualificationRuntime::new();
        let event = codex_hepta_memory::H7TrajectoryEvent::new(
            "release-grant-trajectory",
            /*event_seq*/ 1,
            "reload",
            /*reward_bps*/ 100,
            /*safety_ok*/ true,
            /*authority_epoch*/ 1,
            /*owner_epoch*/ 1,
            /*generation*/ 1,
            Sha256Digest::for_bytes(b"qualified-h7-fence"),
        )
        .expect("trajectory event");
        h7_runtime
            .append_trajectory_event(event)
            .expect("append trajectory");
        h7_runtime
            .evaluate_trajectory("release-grant-trajectory")
            .expect("evaluate trajectory");
        let artifact = h7_runtime
            .propose_artifact(
                "release-grant-artifact",
                "release-grant-trajectory",
                /*generation*/ 1,
            )
            .expect("qualified artifact");
        // Public deterministic fixture material, never a deployment trust anchor.
        let h7_signer =
            H7ArtifactSigner::from_seed("h7-fixture", /*signer_epoch*/ 1, [41; 32])
                .expect("H7 fixture signer");
        let envelope = h7_signer
            .sign(
                &artifact,
                /*ope*/ None,
                H7SignedArtifactTransition::Reload,
                /*expected_runtime_generation*/ 0,
                /*predecessor_artifact_sha256*/ None,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .expect("H7 envelope");
        let signer = H7H89ProductionGrantSigner::from_seed(
            "operator-fixture",
            /*signer_epoch*/ 4,
            [53; 32],
        )
        .expect("independent fixture signer");
        let grant = signer
            .sign(
                &fleet.first,
                "retry-source",
                "verified-grant-target",
                H7H89ProductionTransition::Upgrade,
                &envelope,
                snapshot.control_revision,
                lifecycle_generation,
                /*authority_epoch*/ 7,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .expect("production grant");
        let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
            "operator-fixture",
            /*signer_epoch*/ 4,
            signer.verifying_key(),
            h7_signer.verifier(),
        )
        .expect("pinned verifier");
        let admission = supervisor.apply_production_grant(
            &fleet.first,
            &grant,
            &envelope,
            &verifier,
            /*expected_authority_epoch*/ 7,
            /*now_unix_seconds*/ 150,
            now,
        );
        if source_case != "registered" {
            assert!(
                matches!(admission, Err(SupervisorError::ProductionAuthority(_))),
                "{source_case}"
            );
            assert_eq!(
                supervisor
                    .snapshot(&fleet.first)
                    .expect("rejected snapshot")
                    .control_revision,
                snapshot.control_revision
            );
            assert_eq!(control.counts(&fleet.first), (0, 0, 0));
            assert_eq!(control.spawn_count(&fleet.first), 1);
            let record = supervisor.record(&fleet.first)?;
            assert!(
                read_intent(record.layout.run_root())
                    .expect("no intent")
                    .is_none()
            );
            assert!(
                read_release_transaction(record.layout.run_root())
                    .expect("no transaction")
                    .is_none()
            );
            continue;
        }
        let receipt = admission?;
        assert_eq!(receipt.status, crate::ProductionMutationStatus::Queued);
        assert_eq!(receipt.control_revision, snapshot.control_revision + 1);
        finish_release_drain(&mut supervisor, &control, &fleet.first, now);
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor
                .production_mutation_state(&fleet.first)?
                .expect("mutation")
                .receipt
                .status,
            crate::ProductionMutationStatus::Committed
        );
        let committed = supervisor
            .snapshot(&fleet.first)
            .expect("committed snapshot");
        assert!(matches!(
            supervisor.apply_production_grant(
                &fleet.first,
                &grant,
                &envelope,
                &verifier,
                /*expected_authority_epoch*/ 7,
                /*now_unix_seconds*/ 150,
                now
            ),
            Err(SupervisorError::ProductionAuthority(_))
        ));
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("replay snapshot")
                .control_revision,
            committed.control_revision
        );
        assert_eq!(control.spawn_count(&fleet.first), 2);
    }
    Ok(())
}

#[test]
fn revoked_earlier_predecessor_remains_durable_through_recovery_upgrade_and_restoration()
-> Result<(), SupervisorError> {
    for reject_target in [false, true] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let supervisor = start_source(&fleet, &control, now)?;
        let predecessor = admitted_release(&fleet, &fleet.first, "revoked-predecessor")?;
        let record = supervisor.record(&fleet.first)?;
        let durable_source = fleet.registry.compare_and_set_release_state(
            &fleet.first,
            record.release_state.generation,
            Some(ReleaseId::parse("retry-source")?),
            Some(predecessor.release_id().clone()),
        )?;
        fleet
            .registry
            .revoke_release(&fleet.first, predecessor.release_id())?;
        drop(supervisor);
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert_eq!(
            recovered
                .snapshot(&fleet.first)
                .expect("snapshot")
                .previous_release,
            None
        );
        assert_eq!(recovered.tick(now), TickReport::default());
        assert_eq!(
            recovered.record(&fleet.first)?.release_state,
            durable_source
        );
        let target = admitted_release(&fleet, &fleet.first, "revoked-predecessor-target")?;
        if reject_target {
            control.reject_spawn_program(target.command().program.clone());
        }
        recovered.upgrade(&fleet.first, target, now)?;
        finish_release_drain(&mut recovered, &control, &fleet.first, now);
        drop(recovered);
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        control.set_healthy(&fleet.first);
        assert_eq!(recovered.tick(now), TickReport::default());
        let record = recovered.record(&fleet.first)?;
        if reject_target {
            assert_eq!(record.release_state, durable_source);
        } else {
            assert_eq!(
                record.release_state.current,
                Some(ReleaseId::parse("revoked-predecessor-target")?)
            );
            assert_eq!(
                record.release_state.previous,
                Some(ReleaseId::parse("retry-source")?)
            );
            assert_eq!(
                record.release_state.generation,
                durable_source.generation + 1
            );
        }
        assert!(
            !recovered
                .snapshot(&fleet.first)
                .expect("snapshot")
                .release_change_pending
        );
    }
    Ok(())
}

#[test]
fn rollback_spawn_and_failed_outcome_publication_retain_the_failed_transition_until_retry()
-> Result<(), SupervisorError> {
    for signed in [false, true] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        let source = supervisor.slots[&fleet.first]
            .active_release
            .as_ref()
            .expect("source")
            .clone();
        let target = admitted_release(&fleet, &fleet.first, "rejected-double-failure-target")?;
        control.reject_spawn_program(source.command().program.clone());
        control.reject_spawn_program(target.command().program.clone());
        if signed {
            queue_signed_change(
                &mut supervisor,
                &fleet,
                target,
                now,
                H7H89ProductionTransition::Upgrade,
            )?;
        } else {
            supervisor.upgrade(&fleet.first, target, now)?;
        }
        control.set_drained(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_exit(&fleet.first);
        // TargetStarting and AutomaticRollbackStarting publish successfully; the
        // failed source's RecoveryRequired publication is the third journal write.
        let failed = with_qualification_fault_after(
            "release_transaction.file_write",
            ErrorKind::Other,
            /*successful_occurrences*/ 2,
            || supervisor.tick(now),
        );
        assert_eq!(failed.faults.len(), 1);
        let snapshot = supervisor
            .snapshot(&fleet.first)
            .expect("pending failed transition");
        assert!(snapshot.release_change_pending);
        assert!(!snapshot.events.iter().any(|event| matches!(
            event.kind,
            SupervisorEventKind::AutomaticRollbackFailed { .. }
        )));
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("transaction read")
                .expect("transaction")
                .phase,
            ReleaseTransactionPhase::AutomaticRollbackStarting
        );
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            read_release_transaction(record.layout.run_root())
                .expect("transaction read")
                .expect("transaction")
                .phase,
            ReleaseTransactionPhase::RecoveryRequired
        );
        assert!(
            !supervisor
                .snapshot(&fleet.first)
                .expect("failed transition acknowledged")
                .release_change_pending
        );
        assert_eq!(control.spawn_count(&fleet.first), 1);
        if signed {
            assert!(supervisor.production_recovery_required(&fleet.first)?);
            assert_eq!(
                read_intent(record.layout.run_root())
                    .expect("intent read")
                    .expect("intent")
                    .status,
                SignedIntentStatus::RecoveryRequired
            );
        }
    }
    Ok(())
}

#[test]
fn failed_restart_dispatch_retries_cancellation_without_redispatch() -> Result<(), SupervisorError>
{
    for point in [
        "restart_lineage.rename",
        "restart_lineage.directory_sync",
        "restart_journal.file_write",
        "restart_journal.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut supervisor = start_source(&fleet, &control, now)?;
        let source_program = supervisor.with_slot(&fleet.first, |_supervisor, slot| {
            Ok(slot
                .active_release
                .as_ref()
                .expect("source")
                .command()
                .program
                .clone())
        })?;
        supervisor.restart(&fleet.first, now)?;
        control.set_drained(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.reject_spawn_program(source_program);
        let record = supervisor.record(&fleet.first)?;
        let dispatch_claim = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            config().restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("charged dispatch");
        let operation = (
            dispatch_claim.window_started_unix_ms,
            dispatch_claim.attempt,
        );
        let now = now + config().restart_backoff_base;
        // This release has no companion budget to reset. The first matching
        // journal publication therefore belongs to dispatch cancellation.
        let failed = with_qualification_fault(point, ErrorKind::Other, || supervisor.tick(now));
        assert_eq!(failed.faults.len(), 1);
        assert_eq!(control.spawn_count(&fleet.first), 1);
        let snapshot = supervisor.snapshot(&fleet.first).expect("failed dispatch");
        assert!(!snapshot.active);
        assert!(snapshot.restart_pending, "{point}: {:?}", failed.faults);
        let retained_operation = supervisor.with_slot(&fleet.first, |_supervisor, slot| {
            Ok(slot
                .failed_restart_spawn
                .as_ref()
                .map(|claim| (claim.window_started_unix_ms, claim.attempt)))
        })?;
        assert_eq!(retained_operation, Some(operation), "{point}");
        assert_eq!(snapshot.restart_attempt, operation.1);
        // An overriding idle Stop keeps containment available, but a failed
        // cancellation receipt must continue to exclude another Start/Restart
        // even after Stop cleared the ordinary restart_pending flag.
        let stopped =
            with_qualification_fault("restart_lineage.directory_sync", ErrorKind::Other, || {
                supervisor.stop(&fleet.first, now)
            });
        assert!(
            stopped.is_err(),
            "{point}: stop cancellation must publish its receipt"
        );
        assert!(
            !supervisor
                .snapshot(&fleet.first)
                .expect("stop cancellation")
                .restart_pending
        );
        let before = supervisor.record(&fleet.first)?;
        assert!(matches!(
            supervisor.start(&fleet.first, command()?, now),
            Err(SupervisorError::Invalid(_))
        ));
        let source = supervisor.with_slot(&fleet.first, |_supervisor, slot| {
            Ok(slot.active_release.clone().expect("source"))
        })?;
        assert!(matches!(
            supervisor.start_release(&fleet.first, source, now),
            Err(SupervisorError::Invalid(_))
        ));
        assert!(matches!(
            supervisor.restart(&fleet.first, now),
            Err(SupervisorError::Invalid(_))
        ));
        assert_eq!(supervisor.record(&fleet.first)?.lifecycle, before.lifecycle);
        // If the owner accidentally dispatched again, this cleared rejection
        // would create a new process under the already charged attempt.
        control
            .world
            .lock()
            .expect("fake world")
            .reject_spawn_programs
            .clear();
        // A second ambiguous terminal publication still cannot discard the
        // witness merely because the destination already reads Cancelled.
        let retry =
            with_qualification_fault("restart_lineage.directory_sync", ErrorKind::Other, || {
                supervisor.tick(now)
            });
        assert_eq!(retry.faults.len(), 1, "{point}");
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert!(matches!(
            supervisor.start(&fleet.first, command()?, now),
            Err(SupervisorError::Invalid(_))
        ));
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert!(
            !supervisor
                .snapshot(&fleet.first)
                .expect("cancelled")
                .restart_pending
        );
        let record = supervisor.record(&fleet.first)?;
        assert!(
            crate::restart_budget::pending_restart(
                record.layout.run_root(),
                config().restart_max_attempts
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .is_none()
        );
        supervisor.restart(&fleet.first, now)?;
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("new charged attempt")
                .restart_attempt,
            2
        );
        assert_eq!(control.spawn_count(&fleet.first), 1);
    }
    Ok(())
}

#[path = "release_admission_tests.rs"]
mod admission;

#[path = "release_signed_recovery_tests.rs"]
mod signed_recovery;
