//! Idle companion ticks do not publish restart records; dirty clears retain
//! their exact retry state when filesystem acknowledgement fails.

use std::io::ErrorKind;

use pretty_assertions::assert_eq;

use super::*;
use crate::durability::with_qualification_fault;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;

fn start_without_matrix(
    fleet: &TestFleet,
    control: &FakeControl,
    now: Instant,
) -> Result<Supervisor<FakeDriver>, SupervisorError> {
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(
        &fleet.first,
        admitted_release(fleet, &fleet.first, "no-matrix-budget")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    Ok(supervisor)
}

#[test]
fn idle_no_matrix_ticks_preserve_restart_record_and_do_not_consume_write_fault()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut supervisor = start_without_matrix(&fleet, &control, now)?;
    let record = supervisor.record(&fleet.first)?;
    let run_root = record.layout.run_root();
    crate::restart_budget::claim_restart(
        run_root,
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    supervisor.with_slot(&fleet.first, |supervisor, slot| {
        supervisor.persist_restart_budget(&fleet.first, slot)
    })?;
    let path = run_root.join(RESTART_JOURNAL_FILE);
    let before = std::fs::read(&path)?;
    let before_metadata = std::fs::metadata(&path)?;
    let main = read_main_restart_budget(run_root)?;
    assert!(main.as_ref().is_some_and(|claim| claim.pending));
    let unconsumed =
        with_qualification_fault("restart_journal.file_write", ErrorKind::StorageFull, || {
            for index in 1..=40 {
                assert_eq!(
                    supervisor.tick(now + Duration::from_millis(index * 25)),
                    TickReport::default(),
                );
            }
            crate::durability::check("restart_journal", "file_write")
        });
    assert_eq!(
        unconsumed
            .expect_err("idle ticks must leave write fault unconsumed")
            .kind(),
        ErrorKind::StorageFull
    );
    assert_eq!(std::fs::read(&path)?, before);
    let after_metadata = std::fs::metadata(&path)?;
    assert_eq!(after_metadata.modified()?, before_metadata.modified()?);
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        assert_eq!(after_metadata.ino(), before_metadata.ino());
    }
    assert_eq!(read_main_restart_budget(run_root)?, main);
    Ok(())
}

#[test]
fn no_matrix_budget_clear_retries_failed_publication_and_preserves_main_claim()
-> Result<(), SupervisorError> {
    for point in [
        "restart_journal.file_write",
        "restart_journal.rename",
        "restart_journal.directory_sync",
    ] {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let now = Instant::now();
        let wall = unix_millis_now()?;
        let mut supervisor = start_without_matrix(&fleet, &control, now)?;
        let record = supervisor.record(&fleet.first)?;
        let run_root = record.layout.run_root();
        crate::restart_budget::claim_restart(
            run_root,
            config().restart_max_attempts,
            config().restart_window,
            config().restart_backoff_base,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let main = read_main_restart_budget(run_root)?;
        let dirty = (
            2,
            Some(now),
            Some(wall),
            Some(now + Duration::from_secs(1)),
            true,
            true,
        );
        supervisor.with_slot(&fleet.first, |supervisor, slot| {
            (
                slot.matrix.restart_attempt,
                slot.matrix.restart_window_started_at,
                slot.matrix.restart_window_started_unix_millis,
                slot.matrix.retry_at,
                slot.matrix.restart_after_exit,
                slot.matrix.restart_exhausted,
            ) = dirty;
            supervisor.persist_restart_budget(&fleet.first, slot)
        })?;
        let tick = with_qualification_fault(point, ErrorKind::Other, || supervisor.tick(now));
        assert_eq!(tick, TickReport::default());
        supervisor.with_slot(&fleet.first, |_, slot| {
            assert_eq!(
                (
                    slot.matrix.restart_attempt,
                    slot.matrix.restart_window_started_at,
                    slot.matrix.restart_window_started_unix_millis,
                    slot.matrix.retry_at,
                    slot.matrix.restart_after_exit,
                    slot.matrix.restart_exhausted,
                ),
                dirty,
                "{point}",
            );
            assert!(slot.events.items.iter().any(|event| matches!(
                &event.kind,
                SupervisorEventKind::DriverFault(message)
                    if message.starts_with("Matrix restart budget reset could not be persisted:")
                        && message.len() <= crate::runtime::MAX_FAULT_BYTES
            )));
            Ok(())
        })?;
        assert_eq!(read_main_restart_budget(run_root)?, main);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            read_restart_journal(run_root)?
                .expect("companion journal")
                .matrix,
            DurableRestartWindow::empty(),
        );
        assert_eq!(read_main_restart_budget(run_root)?, main);
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("Agent snapshot")
                .matrix
                .restart_attempt,
            0
        );
        assert_eq!(control.spawn_count(&fleet.first), 1);
    }
    Ok(())
}
