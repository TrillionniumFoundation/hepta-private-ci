//! Actual owned-child observations only, not prepared-token or sandbox admission.
use super::ProcessObservation;
use super::observe_process;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use std::io;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::process::CommandExt as _;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;

fn command(script: &str) -> Result<Command> {
    let shell = std::path::PathBuf::from(std::env::var_os("SystemRoot").context("SystemRoot")?)
        .join("System32/cmd.exe");
    let mut command = Command::new(shell);
    command.args(["/D", "/C"]).raw_arg(script);
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(command)
}

fn remaining(deadline: Instant) -> Result<u32> {
    let duration = deadline
        .checked_duration_since(Instant::now())
        .context("original eight-second child deadline expired")?;
    Ok(u32::try_from(duration.as_millis())?)
}

fn with_child(
    mut command: Command,
    check: impl FnOnce(&mut Child, Instant) -> Result<()>,
) -> Result<()> {
    // Capture the original deadline before birth and retain the actual Child during checks.
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 8);
    let mut child = command.spawn()?;
    let checked =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| check(&mut child, deadline)));
    drop(child.stdin.take());
    if !matches!(child.try_wait(), Ok(Some(_))) {
        // Cleanup targets this exact owned Child only, never a PID lookup.
        if let Err(error) = child.kill() {
            eprintln!("owned observation test child stop failed: {error}");
        }
    }
    // Always attempt the original Child wait before propagating error or panic.
    let reaped = child.wait();
    if let Err(error) = &reaped {
        eprintln!("owned observation test child wait failed: {error}");
    }
    match checked {
        Ok(result) => {
            result?;
            reaped?;
            ensure!(
                Instant::now() < deadline,
                "original eight-second child deadline expired"
            );
            Ok(())
        }
        Err(panic) => std::panic::resume_unwind(panic),
    }
}

fn reduced(process: BorrowedHandle<'_>, rights: u32) -> io::Result<OwnedHandle> {
    let mut raw = 0;
    if unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            process.as_raw_handle() as HANDLE,
            GetCurrentProcess(),
            &mut raw,
            rights,
            /*binherithandle*/ 0,
            /*dwoptions*/ 0,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as _) })
}

#[test]
fn original_signalled_exit_zero_seven_and_259_require_successful_query() -> Result<()> {
    for code in [0, 7, 259] {
        with_child(command(&format!("exit /b {code}"))?, |child, deadline| {
            assert_eq!(
                observe_process(child.as_handle(), remaining(deadline)?)?,
                ProcessObservation::Exited(code)
            );
            Ok(())
        })?;
    }
    Ok(())
}

#[test]
fn actual_wait_and_query_rights_failures_do_not_publish_exit() -> Result<()> {
    with_child(command("exit /b 7")?, |child, deadline| {
        assert_eq!(
            observe_process(child.as_handle(), remaining(deadline)?)?,
            ProcessObservation::Exited(7)
        );
        for rights in [PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE] {
            let handle = reduced(child.as_handle(), rights)?;
            let error = observe_process(handle.as_handle(), /*timeout_ms*/ 0).unwrap_err();
            assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
        }
        // Failed reduced views cannot change the original process's real exit.
        assert_eq!(
            observe_process(child.as_handle(), remaining(deadline)?)?,
            ProcessObservation::Exited(7)
        );
        Ok(())
    })
}

#[test]
fn actual_live_child_is_pending_until_original_stdin_closes() -> Result<()> {
    with_child(command("set /p value= & exit /b 0")?, |child, deadline| {
        assert_eq!(
            observe_process(child.as_handle(), /*timeout_ms*/ 0)?,
            ProcessObservation::Pending
        );
        drop(child.stdin.take());
        assert_eq!(
            observe_process(child.as_handle(), remaining(deadline)?)?,
            ProcessObservation::Exited(0)
        );
        Ok(())
    })
}
