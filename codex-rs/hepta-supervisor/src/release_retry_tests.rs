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
    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "empty-runtime-target")?,
        now,
    )?;
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
