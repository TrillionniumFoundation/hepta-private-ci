//! Admitted intentions remain containment authority after an initial failure.

use std::time::Duration;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::ProcessSet;
use crate::SupervisorEventKind;
use crate::control::pending::PendingControl;
use crate::lease::PROCESS_LEASE_FILE;
use crate::runtime::RuntimePhase;

fn lease_bytes(fixture: &Fixture) -> Result<Vec<u8>> {
    let layout = fixture.fleet.registry.layout().agent(&fixture.fleet.first);
    Ok(std::fs::read(layout.run_root().join(PROCESS_LEASE_FILE))?)
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

fn corrupt_unrelated_manifest(fixture: &Fixture) -> Result<()> {
    let manifest = fixture.fleet.registry.layout().agent(&fixture.fleet.second);
    std::fs::write(manifest.agent_config(), b"invalid = [")?;
    Ok(())
}

fn assert_owned(fixture: &Fixture, lease: &[u8]) -> Result<()> {
    let snapshot = fixture
        .supervisor
        .snapshot(&fixture.fleet.first)
        .expect("owner");
    assert!(snapshot.active && !snapshot.healthy);
    assert_eq!(lease_bytes(fixture)?, lease);
    assert_eq!(fixture.control.spawn_count(&fixture.fleet.first), 1);
    Ok(())
}

#[test]
fn failed_initial_drain_escalates_through_corrupt_fleet_at_original_deadlines() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.faults.lock().expect("faults").main_drain_failures = 1;
    assert!(f.supervisor.drain(&f.fleet.first, f.now).is_err());
    let slot = &f.supervisor.slots[&f.fleet.first];
    assert!(matches!(
        slot.runtime.as_ref().expect("owner").phase,
        RuntimePhase::Running
    ));
    assert!(matches!(
        slot.pending_control,
        Some(PendingControl::Drain { .. })
    ));
    let lease = lease_bytes(&f)?;
    corrupt_unrelated_manifest(&f)?;
    for millis in [9, 10, 19, 20, 30] {
        let report = f.supervisor.tick(f.now + Duration::from_millis(millis));
        f.assert_faults(&report, &["invalid agent manifest"]);
        assert_owned(&f, &lease)?;
        let faults = f.faults.lock().expect("faults");
        assert_eq!(
            (faults.main_drains, faults.main_stops, faults.main_kills),
            match millis {
                9 => (1, 0, 0),
                10 | 19 => (1, 1, 0),
                20 | 30 => (1, 1, 1),
                _ => unreachable!("fixed schedule"),
            }
        );
        if millis == 10 {
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
            SupervisorEventKind::StopRequested,
            SupervisorEventKind::KillRequested
        ]
    );
    Ok(())
}

#[test]
fn failed_initial_stop_escalates_through_corrupt_fleet_at_original_deadline() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.faults.lock().expect("faults").main_stop_failures = 1;
    assert!(f.supervisor.stop(&f.fleet.first, f.now).is_err());
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first].pending_control,
        Some(PendingControl::Stop { .. })
    ));
    let lease = lease_bytes(&f)?;
    corrupt_unrelated_manifest(&f)?;
    for millis in [9, 10, 25] {
        let report = f.supervisor.tick(f.now + Duration::from_millis(millis));
        f.assert_faults(&report, &["invalid agent manifest"]);
        assert_owned(&f, &lease)?;
        let faults = f.faults.lock().expect("faults");
        assert_eq!(
            (faults.main_drains, faults.main_stops, faults.main_kills),
            (0, 1, usize::from(millis >= 10))
        );
    }
    assert_eq!(control_events(&f), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn failed_initial_kill_retries_through_corrupt_fleet_without_signalling_stale_owner() -> Result<()>
{
    for stale in [false, true] {
        let mut f = Fixture::new(ProcessSet::MainOnly)?;
        f.faults.lock().expect("faults").main_kill_failures = 1;
        assert!(f.supervisor.kill(&f.fleet.first).is_err());
        let slot = f.supervisor.slots.get_mut(&f.fleet.first).expect("slot");
        let owner = slot.runtime.as_ref().expect("owner");
        assert!(!owner.fenced);
        assert!(matches!(owner.phase, RuntimePhase::Running));
        let generation = owner.spawn_generation;
        assert!(
            matches!(slot.pending_control, Some(PendingControl::Kill { spawn_generation }) if spawn_generation == generation)
        );
        if stale {
            slot.pending_control = Some(PendingControl::Kill {
                spawn_generation: generation + 1,
            });
        }
        let lease = lease_bytes(&f)?;
        corrupt_unrelated_manifest(&f)?;
        for _ in 0..2 {
            let report = f.supervisor.tick(f.now);
            f.assert_faults(&report, &["invalid agent manifest"]);
            assert_owned(&f, &lease)?;
        }
        assert_eq!(
            f.faults.lock().expect("faults").main_kills,
            if stale { 1 } else { 2 }
        );
        assert_eq!(
            control_events(&f),
            if stale {
                Vec::new()
            } else {
                vec![SupervisorEventKind::KillRequested]
            }
        );
    }
    Ok(())
}
