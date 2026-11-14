use super::config;
use super::ready_paired_supervisor;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;
use anyhow::Context;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[test]
fn matrix_restart_attempts_survive_each_supervisor_recovery() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, mut now) =
        ready_paired_supervisor("matrix-budget-recovery")?;
    let main_pid = supervisor
        .snapshot(&fleet.first)
        .context("first agent")?
        .process_system_id;
    let peer = supervisor.snapshot(&fleet.second).context("peer")?;
    for attempt in 1..=2 {
        now += Duration::from_millis(1);
        control.set_matrix_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .context("failed companion")?
                .matrix
                .restart_attempt,
            attempt
        );
        drop(supervisor);
        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        supervisor = recovered;
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .context("recovered companion")?
                .matrix
                .restart_attempt,
            attempt
        );
        now += Duration::from_millis(300);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_matrix_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            control.matrix_spawn_count(&fleet.first),
            attempt as usize + 1
        );
    }
    let actual = supervisor.snapshot(&fleet.first).context("first agent")?;
    let peer_after = supervisor.snapshot(&fleet.second).context("peer")?;
    assert_eq!(actual.process_system_id, main_pid);
    assert_eq!(peer_after.process_system_id, peer.process_system_id);
    assert_eq!(
        peer_after.matrix.process_system_id,
        peer.matrix.process_system_id
    );
    Ok(())
}

#[test]
fn matrix_clock_rollback_restores_exhaustion_without_resetting_main_budget() -> anyhow::Result<()> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-clock-rollback")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .context("record")?
        .clone();
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )?;
    let main_before = read_main_restart_budget(record.layout.run_root())?;
    assert!(main_before.is_some());
    let journal = RestartBudgetJournal::new(
        fleet.first.clone(),
        record
            .release_state
            .current
            .clone()
            .context("active release")?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(unix_millis_now()? + 60_000),
        },
    )?;
    write_restart_journal(record.layout.run_root(), &journal)?;
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .context("recovered companion")?
            .matrix
            .restart_attempt,
        config().restart_max_attempts
    );
    assert_eq!(recovered.tick(now), TickReport::default());
    control.set_matrix_exit(&fleet.first);
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(
        recovered.tick(now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert!(
        recovered
            .snapshot(&fleet.first)
            .context("first agent")?
            .events
            .iter()
            .any(|event| {
                matches!(
                    event.kind,
                    SupervisorEventKind::MatrixRestartBudgetExhausted { attempts: 3 }
                )
            })
    );
    Ok(())
}

#[test]
fn matrix_budget_identity_mismatch_fails_closed_before_process_recovery() -> anyhow::Result<()> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-owner-mismatch")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .context("record")?
        .clone();
    let journal = RestartBudgetJournal::new(
        fleet.second.clone(),
        record
            .release_state
            .current
            .clone()
            .context("active release")?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 1,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    write_restart_journal(record.layout.run_root(), &journal)?;
    drop(supervisor);
    assert!(matches!(
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now),
        Err(SupervisorError::CorruptLease(_))
    ));
    assert_eq!(
        read_restart_journal(record.layout.run_root())?,
        Some(journal)
    );
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 0));
    Ok(())
}

#[test]
fn a_new_release_resets_only_its_matrix_budget() -> anyhow::Result<()> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-current-release")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .context("record")?
        .clone();
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )?;
    let main_before = read_main_restart_budget(record.layout.run_root())?;
    let journal = RestartBudgetJournal::new(
        fleet.first.clone(),
        ReleaseId::parse("matrix-previous-release")?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    write_restart_journal(record.layout.run_root(), &journal)?;
    drop(supervisor);
    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_before
    );
    let current =
        read_restart_journal(record.layout.run_root())?.context("current matrix budget")?;
    assert_eq!(
        current,
        RestartBudgetJournal::new(
            fleet.first.clone(),
            record.release_state.current.context("active release")?,
            DurableRestartWindow::empty(),
            DurableRestartWindow::empty(),
        )?
    );
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .context("first agent")?
            .matrix
            .restart_attempt,
        0
    );
    Ok(())
}
