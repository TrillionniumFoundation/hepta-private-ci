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
            slot.active_release
                .as_ref()
                .ok_or_else(|| SupervisorError::Invalid("source".to_string()))?
                .identity(),
            target.identity(),
            slot.control_revision,
            record.lifecycle.generation,
            /*authority_epoch*/ 7,
            SignedIntentStatus::Queued,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        write_intent(record.layout.owner_run_root(), &intent)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
-> Result<(), Box<dyn std::error::Error>> {
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
        let pending = supervisor
            .snapshot(&fleet.first)
            .ok_or_else(|| SupervisorError::Invalid("pending release".to_string()))?;
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
            .ok_or_else(|| SupervisorError::Invalid("completed release".to_string()))?;
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
            read_release_transaction(record.layout.owner_run_root())?
                .ok_or_else(|| SupervisorError::Invalid("transaction".to_string()))?
                .phase,
            ReleaseTransactionPhase::Committed
        );
    }
    Ok(())
}

#[test]
fn signed_receipt_failure_retries_after_terminal_release_journal()
-> Result<(), Box<dyn std::error::Error>> {
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
                .ok_or_else(|| SupervisorError::Invalid("snapshot".to_string()))?
                .release_change_pending
        );
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(
            read_release_transaction(record.layout.owner_run_root())?
                .ok_or_else(|| SupervisorError::Invalid("transaction".to_string()))?
                .phase,
            ReleaseTransactionPhase::Committed
        );
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert!(
            !supervisor
                .snapshot(&fleet.first)
                .ok_or_else(|| SupervisorError::Invalid("snapshot".to_string()))?
                .release_change_pending
        );
        assert_eq!(
            read_intent(record.layout.owner_run_root())?
                .ok_or_else(|| SupervisorError::Invalid("intent".to_string()))?
                .status,
            SignedIntentStatus::Committed
        );
        assert_eq!(control.spawn_count(&fleet.first), 2);
    }
    Ok(())
}

#[test]
fn signed_receipt_retry_after_target_exit_does_not_rollback_a_committed_release()
-> Result<(), Box<dyn std::error::Error>> {
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
        read_intent(record.layout.owner_run_root())?
            .ok_or_else(|| SupervisorError::Invalid("intent".to_string()))?
            .status,
        SignedIntentStatus::Committed
    );
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .ok_or_else(|| SupervisorError::Invalid("snapshot".to_string()))?
            .release_change_pending
    );
    Ok(())
}

#[test]
fn terminal_journal_ambiguity_then_target_exit_keeps_the_observed_healthy_outcome()
-> Result<(), Box<dyn std::error::Error>> {
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
            read_release_transaction(record.layout.owner_run_root())?
                .ok_or_else(|| SupervisorError::Invalid("transaction".to_string()))?
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
-> Result<(), Box<dyn std::error::Error>> {
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
                .ok_or_else(|| SupervisorError::Invalid("snapshot".to_string()))?
                .release_change_pending
        );
        assert_eq!(supervisor.tick(now).faults.len(), 1);
        assert_eq!(supervisor.record(&fleet.first)?.release_state, external);
        assert_eq!(control.spawn_count(&fleet.first), 2);
    }
    Ok(())
}
