//! A hostile public binding is rejected by the real Matrix lifecycle caller.
use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::FileTypeExt;

#[test]
fn ordinary_matrix_binding_fifo_is_refused_before_companion_process_entry()
-> QualificationResult<()> {
    let (mut publisher, fleet) = pq_fleet()?;
    let id = publish(&mut publisher, &fleet, "matrix-fifo", /*matrix*/ true)?;
    let release = AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    let record = supervisor.record(&fleet.first)?;
    let path = record.layout.matrix_public_binding();
    std::fs::remove_file(path)?;
    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes())?;
    // SAFETY: the owned NUL-terminated path remains live for this syscall.
    assert_eq!(unsafe { libc::mkfifo(path_bytes.as_ptr(), 0o600) }, 0);
    let frontier = publisher.frontier()?;
    let attempts = publisher.cas_attempts();

    // No FIFO writer exists. The ordinary tick must finish its bounded read and
    // retain the healthy primary without entering the companion driver.
    control.set_healthy(&fleet.first);
    let _ = supervisor.tick(now);
    let snapshot = supervisor.snapshot(&fleet.first).unwrap();
    assert!(snapshot.active && snapshot.healthy);
    assert!(!snapshot.matrix.active && snapshot.matrix.degraded);
    assert!(snapshot.matrix.last_error.as_ref().is_some_and(|error| {
        error.contains("Matrix public binding is not a bounded regular file")
    }));
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 0);
    assert!(std::fs::symlink_metadata(path)?.file_type().is_fifo());
    assert_eq!(publisher.frontier()?, frontier);
    assert_eq!(publisher.cas_attempts(), attempts);
    Ok(())
}
