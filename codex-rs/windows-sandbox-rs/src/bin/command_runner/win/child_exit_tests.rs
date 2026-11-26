use super::CommandExit;
use super::NativeChildState;
use super::interpret_wait_result;
use super::observe_command_exit;
use super::wait_for_native_child;
use anyhow::Result;
use codex_windows_sandbox::RUNNER_TERMINATION_WAIT_MS;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::collections::VecDeque;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use windows_sys::Win32::Foundation::ERROR_INVALID_HANDLE;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_ABANDONED;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::CreateEventW;

enum EventState {
    Signaled,
    Pending,
}

fn owned_event(state: EventState) -> Result<OwnedHandle> {
    let initial_state = match state {
        EventState::Signaled => 1,
        EventState::Pending => 0,
    };
    let manual_reset = 1;
    let handle = unsafe {
        CreateEventW(
            std::ptr::null(),
            manual_reset,
            initial_state,
            std::ptr::null(),
        )
    };
    if handle == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(handle as _) })
}

fn native_error_code(error: &anyhow::Error) -> Option<i32> {
    error
        .root_cause()
        .downcast_ref::<std::io::Error>()
        .and_then(std::io::Error::raw_os_error)
}

struct OwnedChild(Child);

impl Drop for OwnedChild {
    fn drop(&mut self) {
        // This guard owns the exact Child handle; no PID-based or global cleanup.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn native_wait_failure_is_not_an_exit() {
    let error = wait_for_native_child(/*process*/ 0, /*timeout_ms*/ 0)
        .expect_err("invalid handle must fail the native wait");
    assert_eq!(
        (native_error_code(&error), error.to_string()),
        (
            Some(ERROR_INVALID_HANDLE as i32),
            "runner could not observe the command process".to_owned()
        )
    );
}

#[test]
fn native_signaled_non_process_handle_cannot_supply_an_exit_code() -> Result<()> {
    let event = owned_event(EventState::Signaled)?;
    let error = wait_for_native_child(event.as_raw_handle() as HANDLE, /*timeout_ms*/ 0)
        .expect_err("a signaled event is not an observed process exit");
    assert_eq!(
        (native_error_code(&error), error.to_string()),
        (
            Some(ERROR_INVALID_HANDLE as i32),
            "runner could not query the signaled command process exit".to_owned()
        )
    );
    Ok(())
}

#[test]
fn native_pending_wait_does_not_query_an_exit_code() -> Result<()> {
    let event = owned_event(EventState::Pending)?;
    assert_eq!(
        wait_for_native_child(event.as_raw_handle() as HANDLE, /*timeout_ms*/ 0)?,
        NativeChildState::Pending
    );
    Ok(())
}

#[test]
fn native_observed_exit_preserves_23_and_259() -> Result<()> {
    let system_root = std::env::var_os("SystemRoot")
        .map(PathBuf::from)
        .ok_or_else(|| anyhow::anyhow!("SystemRoot is required for the Windows native control"))?;
    for exit_code in [23, 259] {
        let mut child = OwnedChild(
            Command::new(system_root.join("System32").join("cmd.exe"))
                .args(["/d", "/c", &format!("exit /b {exit_code}")])
                .creation_flags(CREATE_NO_WINDOW)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?,
        );
        assert_eq!(
            wait_for_native_child(child.0.as_raw_handle() as HANDLE, /*timeout_ms*/ 5_000)?,
            NativeChildState::Exited(exit_code)
        );
        assert_eq!(child.0.wait()?.code(), Some(exit_code));
    }
    Ok(())
}

#[test]
fn unexpected_wait_results_do_not_query_or_report_exit() {
    for wait_result in [WAIT_ABANDONED, 1, 0x1234_5678] {
        let queries = Cell::new(0);
        let error = interpret_wait_result(wait_result, || {
            queries.set(queries.get() + 1);
            Ok(23)
        })
        .expect_err("unknown wait result must not authorize a query");
        assert_eq!(
            (queries.get(), error.to_string()),
            (
                0,
                format!("runner received an unexpected command wait result: {wait_result:#010x}")
            )
        );
    }
}

#[test]
fn normal_exit_keeps_status_and_never_requests_termination() -> Result<()> {
    let mut waits = Vec::new();
    let terminations = Cell::new(0);
    let result = observe_command_exit(
        /*timeout_ms*/ 43,
        |timeout| {
            waits.push(timeout);
            Ok(NativeChildState::Exited(23))
        },
        || terminations.set(terminations.get() + 1),
    )?;
    assert_eq!(
        (result, waits, terminations.get()),
        (CommandExit::Normal(23), vec![43], 0)
    );
    Ok(())
}

#[test]
fn timeout_requires_native_exit_within_the_same_grace() -> Result<()> {
    let mut states = VecDeque::from([
        Ok(NativeChildState::Pending),
        Ok(NativeChildState::Exited(1)),
    ]);
    let mut waits = Vec::new();
    let terminations = Cell::new(0);
    let result = observe_command_exit(
        /*timeout_ms*/ 43,
        |timeout| {
            waits.push(timeout);
            states.pop_front().expect("only the two admitted waits")
        },
        || terminations.set(terminations.get() + 1),
    )?;
    assert_eq!(
        (result, waits, terminations.get(), states.len()),
        (
            CommandExit::TimedOut,
            vec![43, RUNNER_TERMINATION_WAIT_MS],
            1,
            0
        )
    );
    Ok(())
}

#[test]
fn termination_grace_timeout_cannot_become_an_exit() {
    let mut waits = Vec::new();
    let terminations = Cell::new(0);
    let error = observe_command_exit(
        /*timeout_ms*/ 43,
        |timeout| {
            waits.push(timeout);
            Ok(NativeChildState::Pending)
        },
        || terminations.set(terminations.get() + 1),
    )
    .expect_err("a second pending wait is not terminal");
    assert_eq!(
        (error.to_string(), waits, terminations.get()),
        (
            "runner command process did not exit within the original termination grace".to_owned(),
            vec![43, RUNNER_TERMINATION_WAIT_MS],
            1
        )
    );
}

#[test]
fn termination_grace_observation_error_cannot_become_an_exit() {
    let mut states = VecDeque::from([
        Ok(NativeChildState::Pending),
        Err(anyhow::Error::new(std::io::Error::from_raw_os_error(
            ERROR_INVALID_HANDLE as i32,
        ))),
    ]);
    let mut waits = Vec::new();
    let terminations = Cell::new(0);
    let error = observe_command_exit(
        /*timeout_ms*/ 43,
        |timeout| {
            waits.push(timeout);
            states.pop_front().expect("only the two admitted waits")
        },
        || terminations.set(terminations.get() + 1),
    )
    .expect_err("failed cleanup observation must remain unknown");
    assert_eq!(
        (
            native_error_code(&error),
            waits,
            terminations.get(),
            states.len()
        ),
        (
            Some(ERROR_INVALID_HANDLE as i32),
            vec![43, RUNNER_TERMINATION_WAIT_MS],
            1,
            0
        )
    );
}

#[test]
fn initial_observation_error_does_not_start_another_wait() {
    let mut waits = Vec::new();
    let terminations = Cell::new(0);
    let error = observe_command_exit(
        /*timeout_ms*/ 43,
        |timeout| {
            waits.push(timeout);
            Err(anyhow::Error::new(std::io::Error::from_raw_os_error(
                ERROR_INVALID_HANDLE as i32,
            )))
        },
        || terminations.set(terminations.get() + 1),
    )
    .expect_err("initial observation failure is not successful exit");
    assert_eq!(
        (native_error_code(&error), waits, terminations.get()),
        (Some(ERROR_INVALID_HANDLE as i32), vec![43], 0)
    );
}
