use super::RunnerProcess;
use anyhow::Context;
use anyhow::Result;
use std::io::BufRead;
use std::io::Write;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

pub(super) struct OwnedFixtureChild(pub(super) Child);

impl Drop for OwnedFixtureChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

pub(super) fn blocked_fixture() -> Result<OwnedFixtureChild> {
    let mut child = OwnedFixtureChild(
        Command::new(r"C:\Windows\System32\cmd.exe")
            .args([
                "/d",
                "/q",
                "/c",
                "echo READY & set /p release= & exit /b 23",
            ])
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?,
    );
    let stdout = child.0.stdout.take().context("fixture stdout pipe")?;
    let (ready_tx, ready_rx) = mpsc::channel();
    let ready = std::thread::spawn(move || {
        let mut line = String::new();
        let result = std::io::BufReader::new(stdout).read_line(&mut line);
        let _ = ready_tx.send(result.map(|_| line));
    });
    assert_eq!(
        ready_rx.recv_timeout(Duration::from_secs(5))??.trim(),
        "READY"
    );
    ready
        .join()
        .map_err(|_| anyhow::anyhow!("fixture readiness reader panicked"))?;
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) },
        WAIT_TIMEOUT,
        "the real native child must remain blocked until its private input is released"
    );
    Ok(child)
}

fn observe_fixture(expected_exit: i32) -> Result<Result<()>> {
    let mut child = blocked_fixture()?;
    let mut process = RunnerProcess::new(child.0.as_handle().try_clone_to_owned()?);
    process.arm_timeout(Some(5_000))?;
    let (done_tx, done_rx) = mpsc::channel();
    let observer = std::thread::spawn(move || {
        let _ = done_tx.send(process.wait_for_exit(expected_exit, || false));
    });
    assert!(matches!(done_rx.try_recv(), Err(mpsc::TryRecvError::Empty)));
    child
        .0
        .stdin
        .take()
        .context("fixture stdin pipe")?
        .write_all(b"release\n")?;
    let result = done_rx.recv_timeout(Duration::from_secs(5))?;
    observer
        .join()
        .map_err(|_| anyhow::anyhow!("native process observer panicked"))?;
    assert_eq!(child.0.wait()?.code(), Some(23));
    Ok(result)
}

#[test]
fn native_wait_observes_release_and_exact_exit() -> Result<()> {
    observe_fixture(23)??;
    Ok(())
}

#[test]
fn native_wait_rejects_conflicting_exit_message() -> Result<()> {
    let error =
        observe_fixture(24)?.expect_err("a conflicting IPC exit code is not terminal success");
    assert!(
        error
            .to_string()
            .contains("runner native exit differs from reported exit")
    );
    Ok(())
}

#[test]
fn native_wait_does_not_reset_expired_command_budget() -> Result<()> {
    let child = blocked_fixture()?;
    let mut process = RunnerProcess::new(child.0.as_handle().try_clone_to_owned()?);
    process.arm_timeout(Some(1_000))?;
    process.deadline = Some(Instant::now());
    let error = process
        .wait_for_exit(23, || false)
        .expect_err("an expired command budget must not gain a fresh terminal deadline");
    assert!(error.to_string().contains("within the original budget"));
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) },
        WAIT_TIMEOUT
    );
    Ok(())
}

#[test]
fn native_wait_cancellation_does_not_report_live_process_as_terminal() -> Result<()> {
    let child = blocked_fixture()?;
    let mut process = RunnerProcess::new(child.0.as_handle().try_clone_to_owned()?);
    process.arm_timeout(Some(1_000))?;
    let cancelled = Arc::new(AtomicBool::new(false));
    let observer_cancelled = Arc::clone(&cancelled);
    let (waiting_tx, waiting_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    let observer = std::thread::spawn(move || {
        let announced = AtomicBool::new(false);
        let _ = done_tx.send(process.wait_for_exit(23, || {
            let observed = observer_cancelled.load(Ordering::SeqCst);
            if !announced.swap(true, Ordering::SeqCst) {
                let _ = waiting_tx.send(observed);
            }
            observed
        }));
    });
    assert!(!waiting_rx.recv_timeout(Duration::from_secs(5))?);
    cancelled.store(true, Ordering::SeqCst);
    let error = done_rx
        .recv_timeout(Duration::from_secs(5))?
        .expect_err("cancellation cannot prove the still-running child exited");
    observer
        .join()
        .map_err(|_| anyhow::anyhow!("native process observer panicked"))?;
    assert!(error.to_string().contains("observation cancelled"));
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) },
        WAIT_TIMEOUT
    );
    Ok(())
}
