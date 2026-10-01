//! Admitted intentions remain containment authority after an initial failure.

use std::time::Duration;

use anyhow::Result;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::ProcessSet;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::control::pending::PendingControl;
use crate::control_intent::CONTROL_INTENT_FILE;
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
fn fresh_stop_retains_monotonic_deadline_while_matrix_defers_main_control() -> Result<()> {
    for matrix_stop_fails in [false, true] {
        let mut f = Fixture::new(ProcessSet::WithMatrix)?;
        let layout = f.fleet.registry.layout().agent(&f.fleet.first);
        let main_path = layout.run_root().join(PROCESS_LEASE_FILE);
        let matrix_path = layout.matrixd_process_lease().to_path_buf();
        let leases = (std::fs::read(&main_path)?, std::fs::read(&matrix_path)?);
        let admitted = f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle;
        f.faults.lock().expect("faults").matrix_stop_failures = u32::from(matrix_stop_fails);
        let result = f.supervisor.stop(&f.fleet.first, f.now);
        if matrix_stop_fails {
            assert!(
                result
                    .expect_err("companion Stop failure")
                    .to_string()
                    .contains("one-shot Matrix stop failure")
            );
        } else {
            result?;
        }
        let intent_path = layout.run_root().join(CONTROL_INTENT_FILE);
        let original_intent = std::fs::read(&intent_path)?;
        // A genuine operator retry finishes failed companion deferral without
        // replacing the already admitted main deadline or its owner journal.
        f.supervisor
            .stop(&f.fleet.first, f.now + Duration::from_millis(/*millis*/ 3))?;
        assert_eq!(std::fs::read(&intent_path)?, original_intent);
        assert!(matches!(
            f.supervisor.slots[&f.fleet.first].pending_control,
            Some(PendingControl::Stop { deadline, .. })
                if deadline == f.now + Duration::from_millis(/*millis*/ 10)
        ));
        assert_eq!(
            f.supervisor
                .tick(f.now + Duration::from_millis(/*millis*/ 9)),
            TickReport::default()
        );
        assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 0));
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 1, 0));
        let snapshot = f.supervisor.snapshot(&f.fleet.first).expect("both owners");
        assert!(snapshot.active && snapshot.healthy && snapshot.matrix.active);
        assert_eq!(
            (std::fs::read(&main_path)?, std::fs::read(&matrix_path)?),
            leases
        );
        assert_eq!(
            f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle,
            admitted
        );

        assert_eq!(
            f.supervisor
                .tick(f.now + Duration::from_millis(/*millis*/ 10)),
            TickReport::default()
        );
        assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 1));
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 1, 1));
        let snapshot = f
            .supervisor
            .snapshot(&f.fleet.first)
            .expect("retained owners");
        assert!(
            snapshot.active
                && !snapshot.healthy
                && snapshot.matrix.active
                && !snapshot.matrix.healthy
        );
        assert_eq!(
            (std::fs::read(&main_path)?, std::fs::read(&matrix_path)?),
            leases
        );
        assert_eq!(
            f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle,
            admitted
        );
        assert_eq!(control_events(&f), vec![SupervisorEventKind::KillRequested]);

        // The exact live processes still report healthy; an acknowledged Kill
        // must remain unready without losing ownership or repeating its signal.
        assert_eq!(
            f.supervisor
                .tick(f.now + Duration::from_millis(/*millis*/ 11)),
            TickReport::default()
        );
        let snapshot = f
            .supervisor
            .snapshot(&f.fleet.first)
            .expect("still live owners");
        assert!(
            snapshot.active
                && !snapshot.healthy
                && snapshot.matrix.active
                && !snapshot.matrix.healthy
        );
        assert_eq!(
            (std::fs::read(&main_path)?, std::fs::read(&matrix_path)?),
            leases
        );
        assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 1));
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 1, 1));
        assert_eq!(control_events(&f), vec![SupervisorEventKind::KillRequested]);

        f.control.set_exit(&f.fleet.first);
        f.control.set_matrix_exit(&f.fleet.first);
        assert_eq!(
            f.supervisor
                .tick(f.now + Duration::from_millis(/*millis*/ 12)),
            TickReport::default()
        );
        let snapshot = f
            .supervisor
            .snapshot(&f.fleet.first)
            .expect("finalized owners");
        assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
        assert!(!main_path.exists() && !matrix_path.exists());
        let finalized = f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle;
        assert_eq!(finalized.lifecycle, AgentLifecycle::Failed);
        assert_eq!(finalized.generation, admitted.generation + 1);
        assert_eq!(f.control.spawn_count(&f.fleet.first), 1);
        assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
        assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 1));
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 1, 1));
    }
    // An acknowledged Stop also stays unready on a subsequent successful live
    // probe before its Kill deadline, with its original lease still present.
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.supervisor.stop(&f.fleet.first, f.now)?;
    let lease = lease_bytes(&f)?;
    assert_eq!(
        f.supervisor
            .tick(f.now + Duration::from_millis(/*millis*/ 9)),
        TickReport::default()
    );
    assert_owned(&f, &lease)?;
    assert_eq!(f.control.counts(&f.fleet.first), (0, 1, 0));
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first].runtime.as_ref().expect("stopping owner").phase,
        RuntimePhase::Stopping { deadline }
            if deadline == f.now + Duration::from_millis(/*millis*/ 10)
    ));
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
