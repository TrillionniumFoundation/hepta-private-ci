use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;

use anyhow::Context;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

use super::FakeControl;
use super::FakeDriver;
use super::TestFleet;
use super::admitted_release;
use super::config;
use super::ready_paired_supervisor;
use crate::Supervisor;
use crate::TickReport;
use crate::restart_budget::claim_restart;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;

const EMPTY_RELEASE: &str = "empty-matrix-v1";

fn started_unconfigured_supervisor()
-> anyhow::Result<(TestFleet, FakeControl, Supervisor<FakeDriver>, Instant)> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, EMPTY_RELEASE)?,
        now,
    )?;
    Ok((fleet, control, supervisor, now))
}

fn journal_path(fleet: &TestFleet) -> PathBuf {
    fleet
        .registry
        .layout()
        .agent(&fleet.first)
        .run_root()
        .join(RESTART_JOURNAL_FILE)
}

fn empty_journal(fleet: &TestFleet, release_name: &str) -> anyhow::Result<RestartBudgetJournal> {
    Ok(RestartBudgetJournal::new(
        fleet.first.clone(),
        ReleaseId::parse(release_name)?,
        DurableRestartWindow::empty(),
        DurableRestartWindow::empty(),
    )?)
}

#[derive(Debug, Eq, PartialEq)]
struct RecordObservation {
    bytes: Vec<u8>,
    modified: SystemTime,
}

fn observe_record(path: &Path) -> std::io::Result<RecordObservation> {
    Ok(RecordObservation {
        bytes: std::fs::read(path)?,
        modified: std::fs::metadata(path)?.modified()?,
    })
}

fn mark_record(path: &Path) -> std::io::Result<RecordObservation> {
    // A fixed old mtime detects atomic replacement without sleeping or relying
    // on two adjacent writes receiving different filesystem timestamps.
    File::options()
        .read(true)
        .write(true)
        .open(path)?
        .set_modified(SystemTime::UNIX_EPOCH + Duration::from_secs(/*secs*/ 86_400))?;
    observe_record(path)
}

#[test]
fn empty_matrix_projection_is_written_once_and_keeps_main_pending() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, now) = started_unconfigured_supervisor()?;
    let path = journal_path(&fleet);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        read_restart_journal(path.parent().context("journal parent")?)?,
        Some(empty_journal(&fleet, EMPTY_RELEASE)?)
    );
    let first = mark_record(&path)?;
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
    }
    assert_eq!(observe_record(&path)?, first);

    let run_root = path.parent().context("journal parent")?;
    let configuration = config();
    let claim = claim_restart(
        run_root,
        configuration.restart_max_attempts,
        configuration.restart_window,
        configuration.restart_backoff_base,
    )?;
    assert_eq!(claim.attempt, 1);
    let pending = read_main_restart_budget(run_root)?.context("pending main restart")?;
    assert!(pending.pending);
    let after_main_write = mark_record(&path)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(read_main_restart_budget(run_root)?, Some(pending));
    assert_eq!(observe_record(&path)?, after_main_write);
    Ok(())
}

#[test]
fn failed_empty_matrix_publication_is_retried_after_repair() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, now) = started_unconfigured_supervisor()?;
    let path = journal_path(&fleet);
    // The real writer rejects a non-regular journal. The no-companion branch
    // still has its original best-effort error policy.
    std::fs::create_dir(&path)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(path.is_dir());
    std::fs::remove_dir(&path)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        read_restart_journal(path.parent().context("journal parent")?)?,
        Some(empty_journal(&fleet, EMPTY_RELEASE)?)
    );
    let published = mark_record(&path)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(observe_record(&path)?, published);
    Ok(())
}

#[test]
fn failed_new_release_publication_invalidates_the_old_acknowledgment() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, now) = started_unconfigured_supervisor()?;
    let path = journal_path(&fleet);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let old_projection = empty_journal(&fleet, EMPTY_RELEASE)?;

    supervisor.stop(&fleet.first, now)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    std::fs::remove_file(&path)?;
    std::fs::create_dir(&path)?;
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "empty-matrix-v2")?,
        now,
    )?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(path.is_dir());
    supervisor.stop(&fleet.first, now)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    // Repair to the previous valid bytes, then return to that release. A
    // failed attempt for v2 must not retain v1's earlier acknowledgment.
    std::fs::remove_dir(&path)?;
    write_restart_journal(path.parent().context("journal parent")?, &old_projection)?;
    let repaired = mark_record(&path)?;
    supervisor.start_release(
        &fleet.first,
        crate::AgentRelease::try_from(
            fleet
                .registry
                .resolve_release(&fleet.first, &ReleaseId::parse(EMPTY_RELEASE)?)?,
        )?,
        now,
    )?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let republished = observe_record(&path)?;
    assert_eq!(republished.bytes, repaired.bytes);
    assert_ne!(republished.modified, repaired.modified);
    assert_eq!(
        read_restart_journal(path.parent().context("journal parent")?)?,
        Some(old_projection)
    );
    Ok(())
}

#[test]
fn reopened_supervisor_republishes_and_clears_stale_matrix_budget() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, now) = started_unconfigured_supervisor()?;
    let path = journal_path(&fleet);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let before_reopen = mark_record(&path)?;
    drop(supervisor);

    let (mut reopened, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(reopened.tick(now), TickReport::default());
    let after_reopen = observe_record(&path)?;
    assert_eq!(after_reopen.bytes, before_reopen.bytes);
    assert_ne!(after_reopen.modified, before_reopen.modified);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    drop(reopened);

    let old_projection = RestartBudgetJournal::new(
        fleet.first.clone(),
        ReleaseId::parse(EMPTY_RELEASE)?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    write_restart_journal(path.parent().context("journal parent")?, &old_projection)?;
    let (mut reopened, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(reopened.tick(now), TickReport::default());
    assert_eq!(
        read_restart_journal(path.parent().context("journal parent")?)?,
        Some(empty_journal(&fleet, EMPTY_RELEASE)?)
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}

#[test]
fn configured_matrix_failures_still_persist_each_restart_attempt() -> anyhow::Result<()> {
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("configured-matrix-budget")?;
    let path = journal_path(&fleet);
    let run_root = path.parent().context("journal parent")?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let first = read_restart_journal(run_root)?.context("first Matrix restart")?;
    assert_eq!(first.matrix.attempts, 1);
    assert!(first.matrix.window_started_unix_millis.is_some());

    let retry = now + Duration::from_millis(/*millis*/ 300);
    assert_eq!(supervisor.tick(retry), TickReport::default());
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    control.set_matrix_healthy(&fleet.first);
    assert_eq!(supervisor.tick(retry), TickReport::default());
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(retry), TickReport::default());
    assert_eq!(
        read_restart_journal(run_root)?,
        Some(RestartBudgetJournal::new(
            fleet.first.clone(),
            ReleaseId::parse("configured-matrix-budget")?,
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: first.matrix.window_started_unix_millis,
            },
        )?)
    );
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .context("agent snapshot")?
            .healthy
    );
    assert!(
        supervisor
            .snapshot(&fleet.second)
            .context("peer snapshot")?
            .matrix
            .healthy
    );
    Ok(())
}
