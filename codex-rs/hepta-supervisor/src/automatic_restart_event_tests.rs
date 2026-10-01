//! Automatic restart admission and retry evidence over real durable files.

use std::io;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::FakeControl;
use super::TestFleet;
use super::command;
use super::config;
use super::ready_paired_supervisor;
use crate::Supervisor;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::durability::with_qualification_fault;
use crate::durability::with_qualification_fault_after;
use crate::restart_journal::read_main_restart_budget;

#[test]
fn automatic_restart_cleanup_retry_preserves_one_admission_and_charge() -> Result<()> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut policy = config();
    policy.event_capacity = 64;
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), policy, now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = supervisor.record(&fleet.first)?;
    let owner = supervisor.snapshot(&fleet.first).expect("running owner");

    control.set_exit(&fleet.first);
    // Admission publishes the first lineage. Fail its second publication,
    // which follows exact exit/lease removal and must remain retryable.
    let failed = with_qualification_fault_after(
        "restart_lineage.rename",
        io::ErrorKind::Other,
        /*successful_occurrences*/ 1,
        || supervisor.tick(now),
    );
    assert_eq!(failed.faults.len(), 1);
    assert!(failed.faults[0].message.contains("restart_lineage.rename"));
    let retained = supervisor.snapshot(&fleet.first).expect("retained owner");
    assert!(retained.active);
    assert_eq!(retained.spawn_generation, owner.spawn_generation);
    assert!(retained.restart_pending);
    let charged = read_main_restart_budget(record.layout.run_root())?.expect("charged budget");
    assert_eq!((charged.attempts, charged.pending), (1, true));

    // Repeated cleanup failure never queues or charges the same operation
    // again. Each actual I/O failure remains visible in TickReport.
    let failed = with_qualification_fault("restart_lineage.rename", io::ErrorKind::Other, || {
        supervisor.tick(now)
    });
    assert_eq!(failed.faults.len(), 1);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(charged.clone())
    );
    assert_eq!(supervisor.tick(now), TickReport::default());
    let finalized = supervisor.snapshot(&fleet.first).expect("finalized owner");
    assert!(!finalized.active);
    assert!(finalized.restart_pending);
    assert_eq!(
        finalized
            .events
            .iter()
            .filter(|event| event.kind == SupervisorEventKind::AutomaticRestartQueued { attempt: 1 })
            .count(),
        1
    );
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(charged)
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);

    assert_eq!(
        supervisor.tick(now + Duration::from_millis(1)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 2);
    control.set_healthy(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(1)),
        TickReport::default()
    );
    let completed = read_main_restart_budget(record.layout.run_root())?.expect("completed budget");
    assert_eq!((completed.attempts, completed.pending), (1, false));
    Ok(())
}

#[test]
fn automatic_restart_admission_io_failure_is_a_fault_without_success_event() -> Result<()> {
    for point in [
        "restart_journal.file_write",
        "restart_journal.file_sync",
        "restart_journal.rename",
        "restart_journal.directory_sync",
        "restart_lineage.rename",
        "restart_lineage.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let mut policy = config();
        policy.event_capacity = 64;
        let (mut supervisor, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), policy, now)?;
        supervisor.start(&fleet.first, command()?, now)?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_exit(&fleet.first);
        let failed =
            with_qualification_fault(point, io::ErrorKind::StorageFull, || supervisor.tick(now));
        assert_eq!(failed.faults.len(), 1, "{point}");
        assert!(failed.faults[0].message.contains(point), "{point}");
        let stopped = supervisor.snapshot(&fleet.first).expect("failed admission");
        assert!(!stopped.active, "{point}");
        assert!(!stopped.restart_pending, "{point}");
        assert!(
            !stopped.events.iter().any(|event| matches!(
                event.kind,
                SupervisorEventKind::AutomaticRestartQueued { .. }
                    | SupervisorEventKind::AutomaticRestartBudgetExhausted { .. }
            )),
            "{point}"
        );
        let record = supervisor.record(&fleet.first)?;
        assert_eq!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Failed,
            "{point}"
        );
        let before_retry = read_main_restart_budget(record.layout.run_root())?;
        // Failed admission cannot dispatch free replacements or erase a
        // possibly published charge on a later tick.
        assert_eq!(
            supervisor.tick(now + Duration::from_secs(1)),
            TickReport::default()
        );
        assert_eq!(
            read_main_restart_budget(record.layout.run_root())?,
            before_retry,
            "{point}"
        );
        assert_eq!(control.spawn_count(&fleet.first), 1, "{point}");
    }
    Ok(())
}

#[test]
fn automatic_restart_admission_and_main_cleanup_faults_are_both_reported() -> Result<()> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut policy = config();
    policy.event_capacity = 64;
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), policy, now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = supervisor.record(&fleet.first)?;
    let before_budget = read_main_restart_budget(record.layout.run_root())?;
    let lease = crate::lease::read_lease(record.layout.run_root())?.expect("exact live lease");
    crate::lease::remove_lease(record.layout.run_root(), &lease)?;
    control.set_exit(&fleet.first);

    let failed = with_qualification_fault(
        "restart_journal.file_write",
        io::ErrorKind::StorageFull,
        || supervisor.tick(now),
    );
    assert_eq!(failed.faults.len(), 2);
    assert!(
        failed
            .faults
            .iter()
            .all(|fault| fault.agent_id == fleet.first)
    );
    assert!(
        failed
            .faults
            .iter()
            .any(|fault| fault.message.contains("restart_journal.file_write"))
    );
    assert!(
        failed
            .faults
            .iter()
            .any(|fault| fault.message.contains("active process lease is missing"))
    );
    assert!(
        failed
            .faults
            .iter()
            .all(|fault| fault.message.len() <= crate::runtime::MAX_FAULT_BYTES)
    );
    let retained = supervisor
        .snapshot(&fleet.first)
        .expect("retained exact owner");
    assert!(retained.active);
    assert_eq!(retained.spawn_generation, Some(lease.spawn_generation));
    assert!(!retained.restart_pending);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        before_budget
    );

    // Repair only the cleanup evidence. The retained exact exit cannot
    // re-admit the failed restart or report the admission error twice.
    crate::lease::write_lease(record.layout.run_root(), &lease)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let stopped = supervisor
        .snapshot(&fleet.first)
        .expect("completed cleanup");
    assert!(!stopped.active);
    assert!(!stopped.restart_pending);
    assert!(!stopped.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::AutomaticRestartQueued { .. }
            | SupervisorEventKind::AutomaticRestartBudgetExhausted { .. }
    )));
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        before_budget
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(
        supervisor.record(&fleet.first)?.lifecycle.lifecycle,
        AgentLifecycle::Failed
    );
    Ok(())
}

#[test]
fn automatic_restart_admission_and_companion_cleanup_faults_are_both_reported() -> Result<()> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("admission-companion-cut")?;
    let record = supervisor.record(&fleet.first)?;
    let before_budget = read_main_restart_budget(record.layout.run_root())?;
    let path = record.layout.matrixd_process_lease();
    let lease = crate::lease::read_matrix_lease(path)?.expect("exact companion lease");
    crate::lease::remove_matrix_lease(path, &lease)?;
    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);

    let failed = with_qualification_fault(
        "restart_journal.file_write",
        io::ErrorKind::StorageFull,
        || supervisor.tick(now),
    );
    assert_eq!(failed.faults.len(), 2);
    assert!(
        failed
            .faults
            .iter()
            .all(|fault| fault.agent_id == fleet.first)
    );
    assert!(
        failed
            .faults
            .iter()
            .any(|fault| fault.message.contains("restart_journal.file_write"))
    );
    assert!(failed.faults.iter().any(|fault| {
        fault
            .message
            .contains("Matrix exit cleanup requires the exact existing lease")
    }));
    assert!(
        failed
            .faults
            .iter()
            .all(|fault| fault.message.len() <= crate::runtime::MAX_FAULT_BYTES)
    );
    let retained = supervisor
        .snapshot(&fleet.first)
        .expect("retained companion");
    assert!(!retained.active);
    assert!(retained.matrix.active);
    assert_eq!(
        retained.matrix.process_system_id,
        Some(lease.identity.system_id())
    );
    assert!(!retained.restart_pending);

    crate::lease::write_matrix_lease(path, &lease)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let stopped = supervisor
        .snapshot(&fleet.first)
        .expect("completed paired cleanup");
    assert!(!stopped.active);
    assert!(!stopped.matrix.active);
    assert!(!stopped.restart_pending);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        before_budget
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    Ok(())
}
