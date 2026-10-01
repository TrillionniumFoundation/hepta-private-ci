//! Acknowledged phase deadlines survive later probe and Fleet failures.

use std::time::Duration;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::ProcessSet;
use crate::SupervisorEventKind;
use crate::control::pending::PendingControl;
use crate::lease::PROCESS_LEASE_FILE;
use crate::runtime::RuntimePhase;

#[path = "tick_control_budget_tests.rs"]
mod budget_tests;

fn lease_bytes(fixture: &Fixture) -> Result<Vec<u8>> {
    let layout = fixture.fleet.registry.layout().agent(&fixture.fleet.first);
    Ok(std::fs::read(layout.run_root().join(PROCESS_LEASE_FILE))?)
}

fn assert_retained(fixture: &Fixture, lease: &[u8]) -> Result<()> {
    let snapshot = fixture
        .supervisor
        .snapshot(&fixture.fleet.first)
        .expect("owner");
    assert!(snapshot.active && !snapshot.healthy);
    assert_eq!(lease_bytes(fixture)?, lease);
    assert_eq!(fixture.control.spawn_count(&fixture.fleet.first), 1);
    Ok(())
}

fn control_events(fixture: &Fixture) -> Vec<SupervisorEventKind> {
    fixture
        .supervisor
        .snapshot(&fixture.fleet.first)
        .expect("owner")
        .events
        .into_iter()
        .filter_map(|event| match event.kind {
            SupervisorEventKind::DrainRequested
            | SupervisorEventKind::StopRequested
            | SupervisorEventKind::KillRequested => Some(event.kind),
            _ => None,
        })
        .collect()
}

#[test]
fn acknowledged_drain_deadlines_escalate_despite_persistent_poll_errors() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.drain(&f.fleet.first, f.now)?;
    assert!(f.supervisor.slots[&f.fleet.first].pending_control.is_none());
    let lease = lease_bytes(&f)?;
    f.faults.lock().expect("faults").main_poll_failures = u32::MAX;
    for millis in [9, 15, 19, 20, 40] {
        let report = f.supervisor.tick(f.now + Duration::from_millis(millis));
        f.assert_faults(&report, &["one-shot main poll failure"]);
        assert_retained(&f, &lease)?;
        let faults = f.faults.lock().expect("faults");
        assert_eq!(
            (faults.main_stops, faults.main_kills),
            match millis {
                9 => (0, 0),
                15 | 19 => (1, 0),
                20 | 40 => (1, 1),
                _ => unreachable!("fixed schedule"),
            }
        );
        if millis == 15 {
            assert!(matches!(
                f.supervisor.slots[&f.fleet.first].runtime.as_ref().expect("owner").phase,
                RuntimePhase::Stopping { deadline }
                    if deadline == f.now + Duration::from_millis(/*millis*/ 20)
            ));
        }
    }
    assert_eq!(
        control_events(&f),
        vec![
            SupervisorEventKind::DrainRequested,
            SupervisorEventKind::StopRequested,
            SupervisorEventKind::KillRequested,
        ]
    );
    Ok(())
}

#[test]
fn acknowledged_stop_deadline_kills_despite_persistent_poll_errors() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.stop(&f.fleet.first, f.now)?;
    assert!(f.supervisor.slots[&f.fleet.first].pending_control.is_none());
    let lease = lease_bytes(&f)?;
    f.faults.lock().expect("faults").main_poll_failures = u32::MAX;
    for millis in [9, 10, 25] {
        let report = f.supervisor.tick(f.now + Duration::from_millis(millis));
        f.assert_faults(&report, &["one-shot main poll failure"]);
        assert_retained(&f, &lease)?;
        let faults = f.faults.lock().expect("faults");
        assert_eq!(
            (faults.main_stops, faults.main_kills),
            (1, usize::from(millis >= 10))
        );
    }
    assert_eq!(
        control_events(&f),
        vec![
            SupervisorEventKind::StopRequested,
            SupervisorEventKind::KillRequested
        ]
    );
    Ok(())
}

#[test]
fn expired_drain_signal_and_poll_faults_retain_owner_and_original_budget() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.drain(&f.fleet.first, f.now)?;
    let lease = lease_bytes(&f)?;
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.main_stop_failures = 1;
        faults.main_poll_failures = u32::MAX;
    }
    let report = f
        .supervisor
        .tick(f.now + Duration::from_millis(/*millis*/ 10));
    f.assert_faults(
        &report,
        &["one-shot main stop failure", "one-shot main poll failure"],
    );
    assert_retained(&f, &lease)?;
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first].pending_control,
        Some(PendingControl::Stop { deadline, .. })
            if deadline == f.now + Duration::from_millis(/*millis*/ 20)
    ));
    assert_eq!(
        control_events(&f),
        vec![SupervisorEventKind::DrainRequested]
    );
    let report = f
        .supervisor
        .tick(f.now + Duration::from_millis(/*millis*/ 20));
    f.assert_faults(&report, &["one-shot main poll failure"]);
    assert_retained(&f, &lease)?;
    assert!(f.supervisor.slots[&f.fleet.first].pending_control.is_none());
    let faults = f.faults.lock().expect("faults");
    assert_eq!((faults.main_stops, faults.main_kills), (1, 1));
    assert_eq!(
        control_events(&f),
        vec![
            SupervisorEventKind::DrainRequested,
            SupervisorEventKind::KillRequested
        ]
    );
    Ok(())
}

#[test]
fn expired_phase_preserves_a_stronger_pending_kill() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.drain(&f.fleet.first, f.now)?;
    let lease = lease_bytes(&f)?;
    let slot = f.supervisor.slots.get_mut(&f.fleet.first).expect("slot");
    slot.pending_control = Some(PendingControl::Kill {
        spawn_generation: slot.runtime.as_ref().expect("owner").spawn_generation,
    });
    f.faults.lock().expect("faults").main_poll_failures = u32::MAX;
    let report = f
        .supervisor
        .tick(f.now + Duration::from_millis(/*millis*/ 10));
    f.assert_faults(&report, &["one-shot main poll failure"]);
    assert_retained(&f, &lease)?;
    let faults = f.faults.lock().expect("faults");
    assert_eq!((faults.main_stops, faults.main_kills), (0, 1));
    assert_eq!(
        control_events(&f),
        vec![
            SupervisorEventKind::DrainRequested,
            SupervisorEventKind::KillRequested
        ]
    );
    Ok(())
}

#[test]
fn acknowledged_stop_escalates_before_corrupt_fleet_observation() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.stop(&f.fleet.first, f.now)?;
    let lease = lease_bytes(&f)?;
    let manifest = f
        .fleet
        .registry
        .layout()
        .agent(&f.fleet.second)
        .agent_config()
        .to_path_buf();
    let original = std::fs::read(&manifest)?;
    std::fs::write(&manifest, b"invalid = [")?;
    f.faults.lock().expect("faults").main_kill_failures = 1;
    let report = f
        .supervisor
        .tick(f.now + Duration::from_millis(/*millis*/ 10));
    f.assert_faults(
        &report,
        &["one-shot main kill failure", "invalid agent manifest"],
    );
    assert_retained(&f, &lease)?;
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first].pending_control,
        Some(PendingControl::Kill { .. })
    ));
    assert_eq!(control_events(&f), vec![SupervisorEventKind::StopRequested]);
    for millis in [11, 30] {
        let report = f.supervisor.tick(f.now + Duration::from_millis(millis));
        f.assert_faults(&report, &["invalid agent manifest"]);
        assert_retained(&f, &lease)?;
    }
    assert_eq!(f.faults.lock().expect("faults").main_kills, 2);
    assert_eq!(
        control_events(&f),
        vec![
            SupervisorEventKind::StopRequested,
            SupervisorEventKind::KillRequested
        ]
    );
    std::fs::write(&manifest, original)?;
    f.control.set_exit(&f.fleet.first);
    assert_eq!(
        f.supervisor
            .tick(f.now + Duration::from_millis(/*millis*/ 31)),
        crate::TickReport::default()
    );
    assert!(
        !f.supervisor
            .snapshot(&f.fleet.first)
            .expect("snapshot")
            .active
    );
    assert!(
        crate::lease::read_lease(f.fleet.registry.layout().agent(&f.fleet.first).run_root())?
            .is_none()
    );
    Ok(())
}
