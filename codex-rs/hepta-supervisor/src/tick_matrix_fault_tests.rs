//! Direct companion control failures remain visible alongside later faults.

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::ProcessSet;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::lease::PROCESS_LEASE_FILE;
use crate::lease::read_matrix_lease;
use crate::runtime::MatrixRuntimePhase;

fn pair_lease_bytes(fixture: &Fixture) -> Result<(Vec<u8>, Vec<u8>)> {
    let layout = fixture.fleet.registry.layout().agent(&fixture.fleet.first);
    Ok((
        std::fs::read(layout.run_root().join(PROCESS_LEASE_FILE))?,
        std::fs::read(layout.matrixd_process_lease())?,
    ))
}

fn matrix_kill_events(fixture: &Fixture) -> Vec<SupervisorEventKind> {
    fixture
        .supervisor
        .snapshot(&fixture.fleet.first)
        .expect("owner")
        .events
        .into_iter()
        .filter_map(|event| {
            (event.kind == SupervisorEventKind::MatrixKillRequested).then_some(event.kind)
        })
        .collect()
}

#[test]
fn direct_companion_kill_failure_survives_main_and_matrix_poll_failures() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    let leases = pair_lease_bytes(&f)?;
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.main_poll_failures = 1;
        faults.matrix_kill_failures = 1;
        faults.matrix_poll_failures = 1;
    }
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &[
            "one-shot main poll failure",
            "one-shot Matrix kill failure",
            "one-shot Matrix poll failure",
        ],
    );
    let snapshot = f.supervisor.snapshot(&f.fleet.first).expect("owners");
    assert!(snapshot.active && snapshot.matrix.active);
    assert!(!snapshot.healthy && !snapshot.matrix.healthy);
    assert_eq!(pair_lease_bytes(&f)?, leases);
    let slot = &f.supervisor.slots[&f.fleet.first];
    assert!(!slot.runtime.as_ref().expect("main owner").fenced);
    let matrix = slot.matrix.runtime.as_ref().expect("Matrix owner");
    assert!(matrix.fenced);
    assert!(matches!(matrix.phase, MatrixRuntimePhase::Running));
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 1);
    assert!(matrix_kill_events(&f).is_empty());

    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    assert_eq!(
        matrix_kill_events(&f),
        vec![SupervisorEventKind::MatrixKillRequested]
    );
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first]
            .matrix
            .runtime
            .as_ref()
            .expect("Matrix owner")
            .phase,
        MatrixRuntimePhase::Killing
    ));
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    assert_eq!(pair_lease_bytes(&f)?, leases);
    assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
    Ok(())
}

#[test]
fn direct_companion_kill_failure_survives_exact_exit_lease_cleanup_failure() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    let leases = pair_lease_bytes(&f)?;
    let matrix_path = f
        .fleet
        .registry
        .layout()
        .agent(&f.fleet.first)
        .matrixd_process_lease()
        .to_path_buf();
    let mut foreign = read_matrix_lease(&matrix_path)?.expect("exact Matrix lease");
    foreign.process_incarnation.push_str("-foreign-owner");
    let foreign_bytes = serde_json::to_vec(&foreign)?;
    std::fs::write(&matrix_path, &foreign_bytes)?;
    // A failed main health observation fences the companion directly, without
    // an earlier generation-drift kill that could capture the same fault.
    f.control
        .update(&f.fleet.first, |state| state.healthy = false);
    f.control.set_matrix_exit(&f.fleet.first);
    f.faults.lock().expect("faults").matrix_kill_failures = 1;
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &[
            "one-shot Matrix kill failure",
            "Matrix exit cleanup requires the exact existing lease",
        ],
    );
    let snapshot = f.supervisor.snapshot(&f.fleet.first).expect("owners");
    assert!(snapshot.active && snapshot.matrix.active);
    assert!(!snapshot.healthy && !snapshot.matrix.healthy);
    assert_eq!(
        pair_lease_bytes(&f)?,
        (leases.0.clone(), foreign_bytes.clone())
    );
    assert_eq!(read_matrix_lease(&matrix_path)?, Some(foreign));
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 1);
    assert!(matrix_kill_events(&f).is_empty());
    assert_eq!(
        f.supervisor.slots[&f.fleet.first].matrix.observed_exit,
        Some(crate::ProcessExit {
            success: true,
            code: Some(0)
        })
    );

    // A real main generation drift uses the common companion containment
    // helper before its tick. Stored exit must still skip signaling and probes.
    f.fence()?;
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.matrix_kill_failures = u32::MAX;
        faults.matrix_poll_failures = u32::MAX;
    }
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["Matrix exit cleanup requires the exact existing lease"],
    );
    assert_eq!(pair_lease_bytes(&f)?, (leases.0.clone(), foreign_bytes));
    {
        let faults = f.faults.lock().expect("faults");
        assert_eq!(
            (
                faults.matrix_kills,
                faults.matrix_kill_failures,
                faults.matrix_poll_failures
            ),
            (1, u32::MAX, u32::MAX)
        );
    }
    assert!(matrix_kill_events(&f).is_empty());
    assert!(matches!(
        f.supervisor.slots[&f.fleet.first]
            .matrix
            .runtime
            .as_ref()
            .expect("terminal Matrix owner")
            .phase,
        MatrixRuntimePhase::Running
    ));
    std::fs::write(&matrix_path, &leases.1)?;
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    let slot = &f.supervisor.slots[&f.fleet.first];
    assert!(slot.runtime.is_some());
    assert!(slot.matrix.runtime.is_none());
    assert!(slot.matrix.observed_exit.is_none());
    assert!(slot.matrix.exit_lease_removal.is_none());
    assert!(read_matrix_lease(&matrix_path)?.is_none());
    assert_eq!(
        std::fs::read(
            f.fleet
                .registry
                .layout()
                .agent(&f.fleet.first)
                .run_root()
                .join(PROCESS_LEASE_FILE)
        )?,
        leases.0
    );
    let faults = f.faults.lock().expect("faults");
    assert_eq!(
        (
            faults.matrix_kills,
            faults.matrix_kill_failures,
            faults.matrix_poll_failures
        ),
        (1, u32::MAX, u32::MAX)
    );
    assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
    Ok(())
}
