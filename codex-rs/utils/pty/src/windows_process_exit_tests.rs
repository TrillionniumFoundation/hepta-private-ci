use super::shell_command;
use crate::ProcessExitObserver;
use crate::ProcessExitState;
use anyhow::Context;
use pretty_assertions::assert_eq;
use std::io;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use winapi::shared::winerror::WAIT_TIMEOUT;
use winapi::um::synchapi::WaitForSingleObject;
use winapi::um::winbase::WAIT_FAILED;
use winapi::um::winbase::WAIT_OBJECT_0;

#[derive(Debug, PartialEq, Eq)]
struct ControlObservation {
    initial_child_status: Option<ExitStatus>,
    initial_observer: ProcessExitState,
    exit_code: Option<i32>,
    after_original_drop: ProcessExitState,
}

fn wait_for_child_exit(child: &mut Child, deadline: Instant) -> io::Result<ExitStatus> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    let timeout_ms = u32::try_from(remaining.as_millis()).map_err(io::Error::other)?;
    let wait_result = {
        let process = child.as_handle();
        // SAFETY: the test retains this Child throughout the finite wait. This
        // borrows its process handle without opening a PID or changing access.
        unsafe { WaitForSingleObject(process.as_raw_handle().cast(), timeout_ms) }
    };
    match wait_result {
        WAIT_OBJECT_0 => child
            .try_wait()?
            .ok_or_else(|| io::Error::other("signaled child did not return an exit status")),
        WAIT_TIMEOUT => Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "process-exit control exceeded its fixed deadline",
        )),
        // Capture the failed wait's last-error before any other Windows call.
        WAIT_FAILED => Err(io::Error::last_os_error()),
        _ => Err(io::Error::other("unexpected control process wait result")),
    }
}

fn observe_gated_child(exit_code: u32) -> anyhow::Result<ControlObservation> {
    // Reuse the existing COMSPEC/cmd.exe test choice. SET /P cannot finish
    // normally while this test owns the input pipe and has supplied no input.
    // Its EOF errorlevel is deliberately replaced by the explicit EXIT code.
    let script = format!("set /p HEPTA_EXIT_OBSERVER_GATE= & exit /B {exit_code}");
    let (program, args) = shell_command(&script);
    let started = Instant::now();
    let normal_deadline = started + Duration::from_secs(5);
    let cleanup_deadline = started + Duration::from_secs(10);
    let mut child = Command::new(program)
        .args(["/D", "/Q"])
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;

    // Retain errors until the original child has been explicitly cleaned up.
    // There are no assertions or early-return operators between spawn and drop.
    let observer = ProcessExitObserver::try_from_child(&child);
    let before = observer.as_ref().ok().map(|observer| {
        child
            .try_wait()
            .and_then(|status| observer.snapshot().map(|state| (status, state)))
    });
    drop(child.stdin.take());
    let normal_exit = wait_for_child_exit(&mut child, normal_deadline);
    let cleanup = if normal_exit.is_err() {
        // Only this test-owned Child can be terminated, once, on failure. The
        // second wait shares the original total ten-second cleanup deadline.
        let kill = child.kill();
        let reap = wait_for_child_exit(&mut child, cleanup_deadline);
        Some((kill, reap))
    } else {
        None
    };
    drop(child);

    let outcome = observer.and_then(|observer| {
        let (initial_child_status, initial_observer) =
            before.ok_or_else(|| io::Error::other("missing initial control observation"))??;
        let exit_status = normal_exit?;
        let after_original_drop = observer.snapshot()?;
        Ok(ControlObservation {
            initial_child_status,
            initial_observer,
            exit_code: exit_status.code(),
            after_original_drop,
        })
    });
    match cleanup {
        None => outcome.map_err(Into::into),
        Some((kill, reap)) => outcome.with_context(|| {
            let kill_error = kill.err().map(|error| (error.kind(), error.raw_os_error()));
            let reap_error = reap.err().map(|error| (error.kind(), error.raw_os_error()));
            format!(
                "test-only cleanup after failure: kill_error={kill_error:?}, reap_error={reap_error:?}"
            )
        }),
    }
}

#[test]
fn process_exit_observer_tracks_child_and_outlives_original_handle() -> anyhow::Result<()> {
    assert_eq!(
        observe_gated_child(/*exit_code*/ 0)?,
        ControlObservation {
            initial_child_status: None,
            initial_observer: ProcessExitState::Running,
            exit_code: Some(0),
            after_original_drop: ProcessExitState::Exited { exit_code: 0 },
        }
    );
    Ok(())
}

#[test]
fn process_exit_observer_preserves_signaled_exit_code_259() -> anyhow::Result<()> {
    assert_eq!(
        observe_gated_child(/*exit_code*/ 259)?,
        ControlObservation {
            initial_child_status: None,
            initial_observer: ProcessExitState::Running,
            exit_code: Some(259),
            after_original_drop: ProcessExitState::Exited { exit_code: 259 },
        }
    );
    Ok(())
}
