//! Native child observations used by the broker's original command wait.
//!
//! A failed wait or exit query cannot authorize an Exit frame or preservation of
//! descendants. A timeout uses the existing termination grace once.

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_windows_sandbox::RUNNER_TERMINATION_WAIT_MS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_FAILED;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::GetProcessId;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

#[derive(Debug, Eq, PartialEq)]
pub(super) enum NativeChildState {
    Exited(i32),
    Pending,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) enum CommandExit {
    Normal(i32),
    TimedOut,
}

pub(super) fn wait_for_native_child(process: HANDLE, timeout_ms: u32) -> Result<NativeChildState> {
    let wait_result = unsafe { WaitForSingleObject(process, timeout_ms) };
    interpret_wait_result(wait_result, || {
        // A signaled waitable object need not be a process. Verify this same
        // owned handle supports process identity before accepting an exit code.
        if unsafe { GetProcessId(process) } == 0 {
            return Err(std::io::Error::last_os_error())
                .context("runner could not query the signaled command process exit");
        }
        let mut exit_code = 0;
        if unsafe { GetExitCodeProcess(process, &mut exit_code) } == 0 {
            return Err(std::io::Error::last_os_error())
                .context("runner could not query the signaled command process exit");
        }
        Ok(exit_code as i32)
    })
}

fn interpret_wait_result(
    wait_result: u32,
    query_exit: impl FnOnce() -> Result<i32>,
) -> Result<NativeChildState> {
    match wait_result {
        WAIT_OBJECT_0 => query_exit().map(NativeChildState::Exited),
        WAIT_TIMEOUT => Ok(NativeChildState::Pending),
        WAIT_FAILED => Err(std::io::Error::last_os_error())
            .context("runner could not observe the command process"),
        unexpected => {
            bail!("runner received an unexpected command wait result: {unexpected:#010x}")
        }
    }
}

pub(super) fn observe_command_exit(
    timeout_ms: u32,
    mut wait: impl FnMut(u32) -> Result<NativeChildState>,
    terminate: impl FnOnce(),
) -> Result<CommandExit> {
    match wait(timeout_ms)? {
        NativeChildState::Exited(exit_code) => Ok(CommandExit::Normal(exit_code)),
        NativeChildState::Pending => {
            terminate();
            match wait(RUNNER_TERMINATION_WAIT_MS)? {
                NativeChildState::Exited(_) => Ok(CommandExit::TimedOut),
                NativeChildState::Pending => {
                    bail!(
                        "runner command process did not exit within the original termination grace"
                    )
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "child_exit_tests.rs"]
mod tests;
