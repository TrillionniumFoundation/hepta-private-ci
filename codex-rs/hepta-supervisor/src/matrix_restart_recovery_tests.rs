//! Exercise the public recovery lifecycle with real Fleet and restart files.
//! The existing FakeControl models process observations, not durable state.

use std::time::Duration;

use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

use super::TestFleet;
use super::config;
use super::ready_paired_supervisor;
use crate::Supervisor;
use crate::SupervisorError;
use crate::TickReport;
use crate::restart_budget::RestartBudgetState;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_main_restart_budget;
use crate::restart_journal::write_restart_journal;
use crate::restart_policy::RESTART_ATTEMPT_BUDGET;

fn seed_budgets(
    fleet: &TestFleet,
    matrix: DurableRestartWindow,
) -> Result<(AgentRecord, RestartBudgetState), SupervisorError> {
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .ok_or_else(|| SupervisorError::Invalid("fixture agent is missing".into()))?;
    let release_id = record
        .release_state
        .current
        .clone()
        .ok_or_else(|| SupervisorError::Invalid("fixture active release is missing".into()))?;
    let wall = unix_millis_now()?;
    let main = RestartBudgetState {
        schema_version: 1,
        window_started_unix_ms: wall,
        attempts: 2,
        pending: true,
        next_eligible_unix_ms: wall + 60_000,
    };
    write_main_restart_budget(record.layout.run_root(), &main)?;
    write_restart_journal(
        record.layout.run_root(),
        &RestartBudgetJournal::new(
            fleet.first.clone(),
            release_id,
            DurableRestartWindow::empty(),
            matrix,
        )?,
    )?;
    Ok((record, main))
}

#[test]
fn exhausted_matrix_window_survives_two_recoveries_without_new_spawns()
-> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-recovery-exhausted")?;
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer");
    let (record, _) = seed_budgets(
        &fleet,
        DurableRestartWindow {
            attempts: RESTART_ATTEMPT_BUDGET,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    control.set_matrix_exit(&fleet.first);
    drop(supervisor);

    for _ in 0..2 {
        let main_before = read_main_restart_budget(record.layout.run_root())?;
        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert_eq!(
            read_main_restart_budget(record.layout.run_root())?,
            main_before
        );
        let snapshot = recovered.snapshot(&fleet.first).expect("target");
        assert_eq!(snapshot.matrix.restart_attempt, RESTART_ATTEMPT_BUDGET);
        assert!(!snapshot.matrix.active);
        assert_eq!(recovered.tick(now), TickReport::default());
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
        let peer = recovered.snapshot(&fleet.second).expect("peer");
        assert_eq!(peer.process_system_id, peer_before.process_system_id);
        assert_eq!(
            peer.matrix.process_system_id,
            peer_before.matrix.process_system_id
        );
        assert!(peer.healthy && peer.matrix.healthy);
        assert_eq!(control.spawn_count(&fleet.second), 1);
        assert_eq!(control.matrix_spawn_count(&fleet.second), 1);
        assert_eq!(control.counts(&fleet.second), (0, 0, 0));
        assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
        drop(recovered);
    }
    assert_eq!(
        read_restart_journal(record.layout.run_root())?
            .expect("retained companion")
            .matrix
            .attempts,
        RESTART_ATTEMPT_BUDGET
    );
    Ok(())
}

#[test]
fn missing_matrix_orphan_spends_restored_budget_after_main_lease_resolves_release()
-> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-recovery-orphan")?;
    let (record, main) = seed_budgets(
        &fleet,
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    // The exact live main lease must resolve this release-state crash window
    // before the companion's release binding is selected for recovery.
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        record.release_state.generation,
        /*current*/ None,
        /*previous*/ None,
    )?;
    control.set_matrix_exit(&fleet.first);
    drop(supervisor);

    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered.snapshot(&fleet.first).expect("target");
    assert_eq!(snapshot.restart_attempt, main.attempts);
    assert_eq!(snapshot.matrix.restart_attempt, 3);
    assert!(!snapshot.matrix.active);
    assert_eq!(
        snapshot.active_release.as_deref(),
        record.release_state.current.as_ref().map(ReleaseId::as_str)
    );
    let restored = read_restart_journal(record.layout.run_root())?.expect("companion");
    assert_eq!(restored.main, DurableRestartWindow::empty());
    assert_eq!(restored.matrix.attempts, 3);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(main)
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    Ok(())
}

#[test]
fn matrix_window_normalization_preserves_the_complete_canonical_main_budget()
-> Result<(), SupervisorError> {
    enum Boundary {
        ClockRollback,
        ExpiredWindow,
        OtherRelease,
    }

    for boundary in [
        Boundary::ClockRollback,
        Boundary::ExpiredWindow,
        Boundary::OtherRelease,
    ] {
        let (fleet, control, supervisor, now) =
            ready_paired_supervisor("matrix-recovery-boundary")?;
        let wall = unix_millis_now()?;
        let started = match boundary {
            Boundary::ClockRollback => wall + 60_000,
            Boundary::ExpiredWindow => 1,
            Boundary::OtherRelease => wall,
        };
        let (record, main) = seed_budgets(
            &fleet,
            DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: Some(started),
            },
        )?;
        if matches!(boundary, Boundary::OtherRelease) {
            let original = read_restart_journal(record.layout.run_root())?.expect("companion");
            write_restart_journal(
                record.layout.run_root(),
                &RestartBudgetJournal::new(
                    original.agent_id,
                    ReleaseId::parse("prior-matrix-release")?,
                    DurableRestartWindow::empty(),
                    original.matrix,
                )?,
            )?;
        }
        drop(supervisor);

        let (mut recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        assert_eq!(
            read_main_restart_budget(record.layout.run_root())?,
            Some(main)
        );
        let restored = read_restart_journal(record.layout.run_root())?.expect("companion");
        assert_eq!(restored.main, DurableRestartWindow::empty());
        assert_eq!(
            Some(&restored.release_id),
            record.release_state.current.as_ref()
        );
        match boundary {
            Boundary::ClockRollback => {
                assert_eq!(restored.matrix.attempts, RESTART_ATTEMPT_BUDGET);
                let normalized_wall = restored.matrix.window_started_unix_millis.expect("window");
                assert!(wall <= normalized_wall && normalized_wall <= unix_millis_now()?);
                control.set_matrix_exit(&fleet.first);
                assert_eq!(recovered.tick(now), TickReport::default());
                assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
            }
            Boundary::ExpiredWindow | Boundary::OtherRelease => {
                assert_eq!(restored.matrix, DurableRestartWindow::empty());
                assert_eq!(
                    recovered
                        .snapshot(&fleet.first)
                        .expect("target")
                        .matrix
                        .restart_attempt,
                    0
                );
            }
        }
    }
    Ok(())
}

#[test]
fn companion_identity_failure_is_fatal_even_when_main_adoption_has_a_fault()
-> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-recovery-main-fault")?;
    let (record, main) = seed_budgets(
        &fleet,
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    let release = record
        .release_state
        .current
        .as_ref()
        .expect("active release");
    fleet.registry.revoke_release(&fleet.first, release)?;
    drop(supervisor);

    // A valid companion must not turn the existing main-process adoption
    // fault into a fatal recovery error or bypass its process fence.
    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report.faults.len(), 1);
    assert_eq!(report.faults[0].agent_id, fleet.first);
    assert_eq!(control.counts(&fleet.first).2, 1);
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 0));
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(main.clone())
    );
    drop(recovered);

    let original = read_restart_journal(record.layout.run_root())?.expect("companion");
    write_restart_journal(
        record.layout.run_root(),
        &RestartBudgetJournal::new(
            fleet.second.clone(),
            original.release_id,
            DurableRestartWindow::empty(),
            original.matrix,
        )?,
    )?;
    assert!(matches!(
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now),
        Err(SupervisorError::CorruptLease(message)) if message.contains("restart budget journal belongs")
    ));
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(main)
    );
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 0));
    Ok(())
}

#[test]
fn matrix_budget_restore_preserves_main_pending_claim() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("matrix-main-isolation")?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        3,
        Duration::from_secs(300),
        Duration::from_millis(250),
    )
    .expect("independent main claim");
    let before = crate::restart_journal::read_main_restart_budget(record.layout.run_root())?;
    drop(supervisor);

    let (recovered, report) = Supervisor::recover(fleet.registry, control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let state = recovered.snapshot(&fleet.first).expect("recovered");
    assert_eq!(state.restart_attempt, 1);
    assert!(!state.restart_pending);
    assert_eq!(state.matrix.restart_attempt, 1);
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(record.layout.run_root())?,
        before
    );
    Ok(())
}

#[test]
fn recovered_matrix_retry_waits_for_full_backoff_without_changing_main_budget()
-> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("matrix-recovery-retry-boundary")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let main_before = read_main_restart_budget(record.layout.run_root())?;
    let main_attempt_before = supervisor
        .snapshot(&fleet.first)
        .expect("target")
        .restart_attempt;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    assert_eq!(
        read_restart_journal(record.layout.run_root())?
            .expect("companion after observed exit")
            .matrix
            .attempts,
        1
    );
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    let record_path = record
        .layout
        .run_root()
        .join(crate::restart_journal::RESTART_JOURNAL_FILE);
    let record_before_recovery = std::fs::read(&record_path)?;
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let restored = recovered.snapshot(&fleet.first).expect("recovered");
    assert_eq!(restored.restart_attempt, main_attempt_before);
    assert_eq!(restored.matrix.restart_attempt, 1);
    assert!(!restored.matrix.active);
    assert_eq!(std::fs::read(&record_path)?, record_before_recovery);

    assert_eq!(
        recovered.tick(now + Duration::from_millis(249)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    assert_eq!(std::fs::read(&record_path)?, record_before_recovery);

    assert_eq!(
        recovered.tick(now + Duration::from_millis(250)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some());
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("target")
            .restart_attempt,
        main_attempt_before
    );
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    assert_eq!(std::fs::read(&record_path)?, record_before_recovery);
    Ok(())
}

#[test]
fn exhausted_matrix_window_recovers_degraded_without_an_orphan_lease() -> Result<(), SupervisorError>
{
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("matrix-recovery-exhausted-no-lease")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let main_before = read_main_restart_budget(record.layout.run_root())?;
    let main_attempt_before = supervisor
        .snapshot(&fleet.first)
        .expect("target")
        .restart_attempt;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    let original = read_restart_journal(record.layout.run_root())?.expect("companion after exit");
    assert_eq!(original.matrix.attempts, 1);
    let exhausted = RestartBudgetJournal::new(
        original.agent_id,
        original.release_id,
        original.main,
        DurableRestartWindow {
            attempts: RESTART_ATTEMPT_BUDGET,
            window_started_unix_millis: original.matrix.window_started_unix_millis,
        },
    )?;
    write_restart_journal(record.layout.run_root(), &exhausted)?;
    assert_eq!(
        read_restart_journal(record.layout.run_root())?,
        Some(exhausted)
    );
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    let record_path = record
        .layout
        .run_root()
        .join(crate::restart_journal::RESTART_JOURNAL_FILE);
    let record_before_recovery = std::fs::read(&record_path)?;
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    let restored = recovered.snapshot(&fleet.first).expect("recovered");
    assert_eq!(restored.restart_attempt, main_attempt_before);
    assert_eq!(restored.matrix.restart_attempt, RESTART_ATTEMPT_BUDGET);
    assert!(!restored.matrix.active);
    assert!(restored.matrix.degraded);
    assert_eq!(std::fs::read(&record_path)?, record_before_recovery);

    assert_eq!(
        recovered.tick(now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none());
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("target")
            .restart_attempt,
        main_attempt_before
    );
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    assert_eq!(std::fs::read(&record_path)?, record_before_recovery);
    Ok(())
}
