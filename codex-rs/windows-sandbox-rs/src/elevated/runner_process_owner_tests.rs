use super::super::test_support::pipe_pair;
use super::super::tests::blocked_fixture;
use super::RunnerProcessOwner;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

#[test]
fn owned_cancel_aborts_only_retained_child_with_same_deadline() -> Result<()> {
    let mut child = blocked_fixture()?;
    let unrelated = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::new(child.0.as_handle().try_clone_to_owned()?);
    owner.arm_timeout(Some(5_000))?;
    let error = owner
        .wait_for_exit(23, || true)
        .expect_err("cancelled observation");
    let deadline = owner.process.observation_deadline;
    let error = owner.reconcile_failure(error);
    assert!(error.to_string().contains("native exit observed: 1"));
    assert_eq!(owner.process.observation_deadline, deadline);
    assert_eq!(owner.process.native_exit_code, Some(1));
    assert_eq!(child.0.wait()?.code(), Some(1));
    assert_eq!(
        unsafe { WaitForSingleObject(unrelated.0.as_raw_handle() as HANDLE, 0) },
        WAIT_TIMEOUT
    );
    Ok(())
}

#[test]
fn owned_expired_abort_does_not_claim_terminal_or_restart_budget() -> Result<()> {
    let mut child = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::new(child.0.as_handle().try_clone_to_owned()?);
    owner.arm_timeout(Some(1_000))?;
    let deadline = Instant::now();
    owner.process.deadline = Some(deadline);
    let error = owner
        .abort_and_reconcile()
        .expect_err("no remaining observation budget");
    assert!(error.to_string().contains("within the original budget"));
    assert_eq!(owner.process.observation_deadline, Some(deadline));
    assert_eq!(owner.process.native_exit_code, None);
    assert!(owner.abort_attempted);
    assert!(owner.abort_and_reconcile().is_err());
    assert_eq!(owner.process.observation_deadline, Some(deadline));
    // The abort request and a confirmed terminal receipt are separate facts.
    // This later fixture cleanup observation must not upgrade the owner's result.
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 5_000) },
        WAIT_OBJECT_0
    );
    assert_eq!(child.0.wait()?.code(), Some(1));
    assert_eq!(owner.process.native_exit_code, None);
    Ok(())
}

#[test]
fn owned_abort_failure_preserves_live_child_and_unknown_state() -> Result<()> {
    let child = blocked_fixture()?;
    let mut reduced: HANDLE = 0;
    let duplicated = unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            child.0.as_raw_handle() as HANDLE,
            GetCurrentProcess(),
            &mut reduced,
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
            0,
            0,
        )
    };
    if duplicated == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let mut owner = RunnerProcessOwner::new(unsafe { OwnedHandle::from_raw_handle(reduced as _) });
    owner.arm_timeout(Some(5_000))?;
    let error = owner
        .abort_and_reconcile()
        .expect_err("no PROCESS_TERMINATE right");
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_ACCESS_DENIED as i32)
    );
    assert_eq!(owner.process.native_exit_code, None);
    assert!(owner.abort_attempted);
    drop(owner);
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) },
        WAIT_TIMEOUT
    );
    Ok(())
}

#[test]
fn owned_pipe_disconnect_aborts_real_child_without_exit_message() -> Result<()> {
    let mut child = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::new(child.0.as_handle().try_clone_to_owned()?);
    owner.arm_timeout(Some(5_000))?;
    let (mut reader, writer) = pipe_pair()?;
    drop(writer);
    assert!(owner.read_frame(&mut reader, || false)?.is_none());
    let error = owner.reconcile_failure(anyhow::anyhow!("runner pipe closed before exit"));
    assert!(format!("{error:#}").contains("runner pipe closed before exit"));
    assert_eq!(owner.process.native_exit_code, Some(1));
    assert_eq!(child.0.wait()?.code(), Some(1));
    Ok(())
}

#[test]
fn owned_early_drop_aborts_exact_child() -> Result<()> {
    let mut child = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::new(child.0.as_handle().try_clone_to_owned()?);
    owner.arm_timeout(Some(5_000))?;
    drop(owner);
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) },
        WAIT_OBJECT_0
    );
    assert_eq!(child.0.wait()?.code(), Some(1));
    Ok(())
}

#[test]
fn owned_partial_frame_cancellation_aborts_without_control_writer() -> Result<()> {
    let mut child = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::new(child.0.as_handle().try_clone_to_owned()?);
    owner.arm_timeout(Some(5_000))?;
    let armed_deadline = owner.process.deadline;
    let (mut reader, mut writer) = pipe_pair()?;
    writer.write_all(&32_u32.to_le_bytes())?;
    writer.write_all(b"{")?;
    let cancelled = Arc::new(AtomicBool::new(false));
    let observer_cancelled = Arc::clone(&cancelled);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    let observer = std::thread::spawn(move || {
        let result = (|| -> Result<()> {
            let announced = AtomicBool::new(false);
            let result = owner.read_frame(&mut reader, || {
                let observed = observer_cancelled.load(Ordering::SeqCst);
                if !announced.swap(true, Ordering::SeqCst) {
                    let _ = entered_tx.send(observed);
                }
                observed
            });
            let error = match result {
                Err(error) => error,
                Ok(_) => anyhow::bail!("the live frame is incomplete and cancelled"),
            };
            assert_eq!(
                error
                    .downcast_ref::<std::io::Error>()
                    .map(std::io::Error::kind),
                Some(std::io::ErrorKind::Other)
            );
            let error = owner.reconcile_failure(error);
            assert!(format!("{error:#}").contains("observation cancelled"));
            assert_eq!(owner.process.deadline, armed_deadline);
            assert_eq!(owner.process.native_exit_code, Some(1));
            Ok(())
        })();
        let _ = done_tx.send(result);
    });
    let entered = entered_rx.recv_timeout(Duration::from_secs(5));
    cancelled.store(true, Ordering::SeqCst);
    let result = done_rx.recv_timeout(Duration::from_secs(5));
    // An old blocking decoder must also be released for failed-test cleanup.
    // Receiving a later EOF can never satisfy the cancellation assertion above.
    drop(writer);
    observer
        .join()
        .map_err(|_| anyhow::anyhow!("owned reader panicked"))?;
    assert!(!entered?);
    result??;
    assert_eq!(child.0.wait()?.code(), Some(1));
    Ok(())
}
