//! Real Linux process-custody tests; these do not manufacture a native role.
use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn actual_child_pidfd_reaps_normal_exit_without_reusing_numeric_identity() -> TestResult {
    let mut process = Command::new("/bin/sh")
        .args(["-c", "read -r value; exit 0"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let mut custody = KernelInitialChild::capture(process.id())?;
    assert!(custody.is_alive()?);
    process
        .stdin
        .take()
        .ok_or("child stdin missing")?
        .write_all(b"release\n")?;
    let deadline = Instant::now() + Duration::from_secs(5);
    let exit = loop {
        if let Some(exit) = custody.try_wait()? {
            break exit;
        }
        if Instant::now() >= deadline {
            return Err("child failed to exit within test budget".into());
        }
        std::thread::sleep(Duration::from_millis(1));
    };
    assert_eq!(
        exit,
        ProcessExit {
            success: true,
            code: Some(0)
        }
    );
    assert_eq!(custody.try_wait()?, Some(exit));
    assert!(!custody.is_alive()?);
    // The original guard has already reaped the exact child. A later reap
    // cannot consume a second process, and repeated stop is harmless.
    custody.signal(libc::SIGTERM)?;
    let waited = unsafe { libc::waitpid(process.id() as i32, std::ptr::null_mut(), libc::WNOHANG) };
    assert_eq!(
        (waited, io::Error::last_os_error().raw_os_error()),
        (-1, Some(libc::ECHILD))
    );
    Ok(())
}

#[test]
fn actual_child_guard_drop_terminates_and_reaps_only_its_held_process() -> TestResult {
    let process = Command::new("/usr/bin/sleep")
        .arg("60")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let custody = KernelInitialChild::capture(process.id())?;
    custody.check_alive()?;
    drop(custody);
    let waited = unsafe { libc::waitpid(process.id() as i32, std::ptr::null_mut(), libc::WNOHANG) };
    assert_eq!(
        (waited, io::Error::last_os_error().raw_os_error()),
        (-1, Some(libc::ECHILD))
    );
    assert!(KernelInitialChild::capture(std::process::id()).is_err());
    Ok(())
}

#[test]
fn altered_process_identity_cannot_signal_the_still_running_actual_child() -> TestResult {
    let process = Command::new("/usr/bin/sleep")
        .arg("60")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let mut custody = KernelInitialChild::capture(process.id())?;
    let original_start = custody.start_ticks;
    custody.start_ticks = original_start
        .checked_add(1)
        .ok_or("start ticks overflow")?;
    assert!(custody.signal(libc::SIGKILL).is_err());
    assert!(custody.try_wait().is_err());
    custody.start_ticks = original_start;
    assert!(custody.is_alive()?);
    drop(custody);
    Ok(())
}
