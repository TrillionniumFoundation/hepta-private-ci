use super::SandboxAccountSetupGuard;
use super::process_creation_time;
use crate::sandbox_account::SandboxAccountLease;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::process::Command;
use std::sync::mpsc;
use std::thread;
use windows_sys::Win32::System::Threading::OpenEventW;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;

#[test]
fn an_entered_setup_helper_finishes_before_the_next_account_lease() -> Result<()> {
    let first = SandboxAccountLease::acquire()?;
    let witness = first.witness();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (finish_tx, finish_rx) = mpsc::channel();
    let helper = thread::spawn(move || -> Result<()> {
        let _setup = SandboxAccountSetupGuard::acquire(&witness)?;
        entered_tx.send(())?;
        finish_rx.recv()?;
        Ok(())
    });
    entered_rx.recv()?;
    drop(first);
    let (started_tx, started_rx) = mpsc::channel();
    let (next_tx, next_rx) = mpsc::channel();
    let next = thread::spawn(move || -> Result<()> {
        started_tx.send(())?;
        let _lease = SandboxAccountLease::acquire()?;
        next_tx.send(())?;
        Ok(())
    });
    started_rx.recv()?;
    assert_eq!(next_rx.try_recv(), Err(mpsc::TryRecvError::Empty));
    finish_tx.send(())?;
    next_rx.recv()?;
    helper
        .join()
        .map_err(|_| anyhow::anyhow!("setup fixture thread panicked"))??;
    next.join()
        .map_err(|_| anyhow::anyhow!("next lease thread panicked"))??;
    Ok(())
}

#[test]
fn a_late_helper_rejects_a_closed_lease_even_while_the_parent_is_alive() -> Result<()> {
    let lease = SandboxAccountLease::acquire()?;
    let witness = lease.witness();
    let event = unsafe {
        OpenEventW(
            PROCESS_SYNCHRONIZE,
            /*binherithandle*/ 0,
            crate::winutil::to_wide(&witness.closed_event).as_ptr(),
        )
    };
    anyhow::ensure!(
        event != 0,
        "retain fixture event: {}",
        std::io::Error::last_os_error()
    );
    // Retain the signalled object, so this checks closed state rather than only NotFound.
    let _event = unsafe { OwnedHandle::from_raw_handle(event as _) };
    drop(lease);
    let result = SandboxAccountSetupGuard::acquire(&witness);
    let error = result
        .err()
        .ok_or_else(|| anyhow::anyhow!("closed lease was accepted"))?;
    assert_eq!(error.to_string(), "setup account lease is closed");
    Ok(())
}

#[test]
fn setup_rejects_changed_parent_identity_and_a_real_exited_parent() -> Result<()> {
    let lease = SandboxAccountLease::acquire()?;
    let mut changed = lease.witness();
    changed.parent_creation_time = changed.parent_creation_time.wrapping_add(1);
    assert!(SandboxAccountSetupGuard::acquire(&changed).is_err());
    let mut child = Command::new("C:\\Windows\\System32\\cmd.exe")
        .args(["/d", "/c", "exit 0"])
        .spawn()?;
    let mut exited = lease.witness();
    exited.parent_process_id = child.id();
    exited.parent_creation_time = process_creation_time(child.as_raw_handle() as _)?;
    assert!(child.wait()?.success());
    assert!(SandboxAccountSetupGuard::acquire(&exited).is_err());
    Ok(())
}
