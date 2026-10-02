//! Direct companion control failures remain visible alongside later faults.

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::ProcessSet;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::lease::PROCESS_LEASE_FILE;
use crate::lease::read_matrix_lease;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::RuntimePhase;

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

#[test]
fn stored_matrix_exit_blocks_graceful_resignal_until_exact_cleanup() -> Result<()> {
    for action in [
        DeferredAgentActionKind::Drain,
        DeferredAgentActionKind::Stop,
    ] {
        let mut f = Fixture::new(ProcessSet::WithMatrix)?;
        let layout = f.fleet.registry.layout().agent(&f.fleet.first);
        let main_path = layout.run_root().join(PROCESS_LEASE_FILE);
        let matrix_path = layout.matrixd_process_lease().to_path_buf();
        let leases = pair_lease_bytes(&f)?;
        let admitted = f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle;
        let mut foreign = read_matrix_lease(&matrix_path)?.expect("owned Matrix lease");
        foreign
            .process_incarnation
            .push_str("-foreign-cleanup-owner");
        let foreign_bytes = serde_json::to_vec(&foreign)?;
        std::fs::write(&matrix_path, &foreign_bytes)?;
        f.control.set_matrix_exit(&f.fleet.first);
        let report = f.supervisor.tick(f.now);
        f.assert_faults(
            &report,
            &["Matrix exit cleanup requires the exact existing lease"],
        );
        let terminal = f.supervisor.slots[&f.fleet.first].matrix.observed_exit;
        assert!(terminal.is_some());
        {
            let mut faults = f.faults.lock().expect("faults");
            faults.matrix_stop_failures = u32::MAX;
            faults.matrix_kill_failures = u32::MAX;
            faults.matrix_poll_failures = u32::MAX;
        }
        match action {
            DeferredAgentActionKind::Drain => f.supervisor.drain(&f.fleet.first, f.now)?,
            DeferredAgentActionKind::Stop => f.supervisor.stop(&f.fleet.first, f.now)?,
        }
        let slot = &f.supervisor.slots[&f.fleet.first];
        assert!(matches!(
            slot.deferred_agent_action,
            Some(deferred) if deferred.kind == action
                && deferred.spawn_generation == slot.runtime.as_ref().expect("main owner").spawn_generation
        ));
        assert_eq!(slot.matrix.observed_exit, terminal);
        assert!(matches!(
            slot.matrix.runtime.as_ref().expect("terminal owner").phase,
            MatrixRuntimePhase::Running
        ));
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 0, 0));
        if action == DeferredAgentActionKind::Stop {
            assert!(matches!(
                slot.pending_control,
                Some(crate::control::pending::PendingControl::Stop { deadline, .. })
                    if deadline == f.now + std::time::Duration::from_millis(/*millis*/ 10)
            ));
        }
        let report = f
            .supervisor
            .tick(f.now + std::time::Duration::from_millis(/*millis*/ 9));
        f.assert_faults(
            &report,
            &["Matrix exit cleanup requires the exact existing lease"],
        );
        assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 0));
        assert_eq!(
            pair_lease_bytes(&f)?,
            (leases.0.clone(), foreign_bytes.clone())
        );
        assert_eq!(
            f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle,
            admitted
        );
        if action == DeferredAgentActionKind::Stop {
            let report = f
                .supervisor
                .tick(f.now + std::time::Duration::from_millis(/*millis*/ 10));
            f.assert_faults(
                &report,
                &["Matrix exit cleanup requires the exact existing lease"],
            );
            assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 1));
            assert!(matches!(
                f.supervisor.slots[&f.fleet.first]
                    .runtime
                    .as_ref()
                    .expect("main owner")
                    .phase,
                RuntimePhase::Killing
            ));
            assert_eq!(pair_lease_bytes(&f)?, (leases.0.clone(), foreign_bytes));
        }

        // Restore the exact real lease while the main is still alive. Cleanup
        // may release Matrix ownership, but cannot replay an acknowledged Kill.
        std::fs::write(&matrix_path, &leases.1)?;
        assert_eq!(
            f.supervisor
                .tick(f.now + std::time::Duration::from_millis(/*millis*/ 11)),
            TickReport::default()
        );
        let slot = &f.supervisor.slots[&f.fleet.first];
        let main = slot.runtime.as_ref().expect("still live main owner");
        assert!(!main.healthy);
        assert!(slot.matrix.runtime.is_none() && slot.matrix.observed_exit.is_none());
        assert!(slot.matrix.exit_lease_removal.is_none() && slot.deferred_agent_action.is_none());
        assert!(!matrix_path.exists());
        assert_eq!(std::fs::read(&main_path)?, leases.0);
        let after_cleanup = f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle;
        match action {
            DeferredAgentActionKind::Drain => {
                assert!(matches!(main.phase, RuntimePhase::Draining { .. }));
                assert_eq!(f.control.counts(&f.fleet.first), (1, 0, 0));
                assert_eq!(
                    after_cleanup.lifecycle,
                    codex_hepta_fleet::AgentLifecycle::Draining
                );
                assert_eq!(after_cleanup.generation, admitted.generation + 1);
            }
            DeferredAgentActionKind::Stop => {
                assert!(matches!(main.phase, RuntimePhase::Killing));
                assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 1));
                assert_eq!(after_cleanup, admitted);
            }
        }
        let events = &slot.events.items;
        assert_eq!(
            events
                .iter()
                .filter(|event| matches!(event.kind, SupervisorEventKind::MatrixExited(_)))
                .count(),
            1
        );
        assert!(events.iter().all(|event| !matches!(
            event.kind,
            SupervisorEventKind::MatrixStopRequested | SupervisorEventKind::MatrixKillRequested
        )));
        assert_eq!(
            events
                .iter()
                .filter(|event| event.kind == SupervisorEventKind::KillRequested)
                .count(),
            usize::from(action == DeferredAgentActionKind::Stop)
        );
        assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 0, 0));
        {
            let faults = f.faults.lock().expect("faults");
            assert_eq!(
                (
                    faults.matrix_stop_failures,
                    faults.matrix_kill_failures,
                    faults.matrix_poll_failures
                ),
                (u32::MAX, u32::MAX, u32::MAX)
            );
        }

        f.control.set_exit(&f.fleet.first);
        assert_eq!(
            f.supervisor
                .tick(f.now + std::time::Duration::from_millis(/*millis*/ 12)),
            TickReport::default()
        );
        let snapshot = f
            .supervisor
            .snapshot(&f.fleet.first)
            .expect("finalized owners");
        assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
        assert!(!main_path.exists() && !matrix_path.exists());
        let finalized = f.fleet.registry.load_agent(&f.fleet.first)?.lifecycle;
        assert_eq!(finalized.generation, after_cleanup.generation + 1);
        assert_eq!(
            finalized.lifecycle,
            match action {
                DeferredAgentActionKind::Drain => codex_hepta_fleet::AgentLifecycle::Stopped,
                DeferredAgentActionKind::Stop => codex_hepta_fleet::AgentLifecycle::Failed,
            }
        );
        assert_eq!(f.control.spawn_count(&f.fleet.first), 1);
        assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
    }
    Ok(())
}

#[test]
fn deferred_drain_exit_does_not_admit_automatic_restart_before_matrix_cleanup() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    let layout = f.fleet.registry.layout().agent(&f.fleet.first);
    let main_path = layout.run_root().join(PROCESS_LEASE_FILE);
    let matrix_path = layout.matrixd_process_lease().to_path_buf();
    let lineage_path = layout
        .run_root()
        .join(crate::restart_lineage::RESTART_LINEAGE_FILE);
    let initial_budget = crate::restart_journal::read_main_restart_budget(layout.run_root())?;
    assert!(!lineage_path.exists());
    let leases = pair_lease_bytes(&f)?;
    let mut foreign = read_matrix_lease(&matrix_path)?.expect("owned Matrix lease");
    foreign
        .process_incarnation
        .push_str("-foreign-drain-cleanup-owner");
    let foreign_bytes = serde_json::to_vec(&foreign)?;
    std::fs::write(&matrix_path, &foreign_bytes)?;
    f.control.set_matrix_exit(&f.fleet.first);
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["Matrix exit cleanup requires the exact existing lease"],
    );
    f.supervisor.drain(&f.fleet.first, f.now)?;
    let slot = &f.supervisor.slots[&f.fleet.first];
    assert!(matches!(
        slot.deferred_agent_action,
        Some(action) if action.kind == DeferredAgentActionKind::Drain
            && action.spawn_generation == slot.runtime.as_ref().expect("main owner").spawn_generation
    ));
    assert!(slot.pending_control.is_none());
    assert_eq!(pair_lease_bytes(&f)?, (leases.0, foreign_bytes.clone()));

    // The physical source exits while its accepted Drain still awaits Matrix
    // cleanup. That existing termination intent cannot admit a replacement.
    f.control.set_exit(&f.fleet.first);
    let report = f
        .supervisor
        .tick(f.now + std::time::Duration::from_millis(/*millis*/ 1));
    f.assert_faults(
        &report,
        &["Matrix exit cleanup requires the exact existing lease"],
    );
    let slot = &f.supervisor.slots[&f.fleet.first];
    assert!(slot.runtime.is_none() && slot.matrix.runtime.is_some());
    assert!(slot.matrix.observed_exit.is_some());
    assert!(!slot.restart_pending);
    assert!(!main_path.exists());
    assert_eq!(std::fs::read(&matrix_path)?, foreign_bytes);
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(layout.run_root())?,
        initial_budget
    );
    assert!(!lineage_path.exists());
    assert!(slot.events.items.iter().all(|event| !matches!(
        event.kind,
        SupervisorEventKind::RestartQueued | SupervisorEventKind::AutomaticRestartQueued { .. }
    )));
    assert_eq!(
        f.fleet
            .registry
            .load_agent(&f.fleet.first)?
            .lifecycle
            .lifecycle,
        codex_hepta_fleet::AgentLifecycle::Failed
    );

    std::fs::write(&matrix_path, &leases.1)?;
    assert_eq!(
        f.supervisor
            .tick(f.now + std::time::Duration::from_millis(/*millis*/ 20)),
        TickReport::default()
    );
    let snapshot = f
        .supervisor
        .snapshot(&f.fleet.first)
        .expect("finalized owners");
    assert!(!snapshot.active && !snapshot.matrix.active && !snapshot.restart_pending);
    assert!(!main_path.exists() && !matrix_path.exists() && !lineage_path.exists());
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(layout.run_root())?,
        initial_budget
    );
    assert!(snapshot.events.iter().all(|event| !matches!(
        event.kind,
        SupervisorEventKind::RestartQueued | SupervisorEventKind::AutomaticRestartQueued { .. }
    )));
    assert_eq!(f.control.counts(&f.fleet.first), (0, 0, 0));
    assert_eq!(f.control.matrix_counts(&f.fleet.first), (0, 0, 0));
    assert_eq!(f.control.spawn_count(&f.fleet.first), 1);
    assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
    Ok(())
}
