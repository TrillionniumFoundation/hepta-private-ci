use super::JobObject;
use super::WinChild;
use filedescriptor::OwnedHandle;
use pretty_assertions::assert_eq;
use std::io;
use std::io::Read as _;
use std::io::Write as _;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use winapi::shared::minwindef::DWORD;
use winapi::shared::winerror::ERROR_ACCESS_DENIED;
use winapi::shared::winerror::WAIT_TIMEOUT;
use winapi::um::handleapi::DuplicateHandle;
use winapi::um::processthreadsapi::GetCurrentProcess;
use winapi::um::synchapi::WaitForSingleObject;
use winapi::um::winbase::WAIT_FAILED;
use winapi::um::winbase::WAIT_OBJECT_0;
use winapi::um::winnt::DUPLICATE_SAME_ACCESS;
use winapi::um::winnt::PROCESS_QUERY_LIMITED_INFORMATION;
use winapi::um::winnt::SYNCHRONIZE;

const CHILD_EXIT_ENV: &str = "CODEX_PTY_NATIVE_WAIT_TEST_EXIT";
const CHILD_TEST: &str = "win::observation_tests::native_child_fixture";

struct NativeChild {
    child: Child,
    deadline: Instant,
}

impl NativeChild {
    fn spawn(exit_code: i32) -> io::Result<Self> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let child = Command::new(std::env::current_exe()?)
            .args(["--exact", CHILD_TEST, "--nocapture"])
            .env(CHILD_EXIT_ENV, exit_code.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        Ok(Self { child, deadline })
    }

    fn duplicate(&self, access: DWORD, options: DWORD) -> io::Result<OwnedHandle> {
        let mut duplicate = std::ptr::null_mut();
        let duplicated = unsafe {
            DuplicateHandle(
                GetCurrentProcess(),
                self.child.as_raw_handle().cast(),
                GetCurrentProcess(),
                &mut duplicate,
                access,
                /*bInheritHandle*/ 0,
                options,
            )
        };
        if duplicated == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { OwnedHandle::from_raw_handle(duplicate.cast()) })
    }

    fn is_running(&self) -> io::Result<bool> {
        match unsafe { WaitForSingleObject(self.child.as_raw_handle().cast(), 0) } {
            WAIT_TIMEOUT => Ok(true),
            WAIT_OBJECT_0 => Ok(false),
            WAIT_FAILED => Err(io::Error::last_os_error()),
            _ => Err(io::Error::other("unexpected fixture process wait result")),
        }
    }

    fn release_and_observe(&mut self) -> io::Result<i32> {
        let mut stdin = self
            .child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("fixture stdin missing"))?;
        stdin.write_all(&[1])?;
        drop(stdin);
        let remaining = self
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::TimedOut, "fixture observation expired")
            })?;
        let wait_ms = remaining.as_millis().min(u128::from(u32::MAX)) as u32;
        match unsafe { WaitForSingleObject(self.child.as_raw_handle().cast(), wait_ms) } {
            WAIT_OBJECT_0 => {}
            WAIT_TIMEOUT => {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "fixture child remained live",
                ));
            }
            WAIT_FAILED => return Err(io::Error::last_os_error()),
            _ => return Err(io::Error::other("unexpected fixture process wait result")),
        }
        self.child
            .try_wait()?
            .and_then(|status| status.code())
            .ok_or_else(|| io::Error::other("signaled fixture process lacks its native exit code"))
    }
}

impl Drop for NativeChild {
    fn drop(&mut self) {
        // Failed tests still request cleanup of this exact owned child. Every
        // successful case separately proves its native terminal state above.
        if self.is_running().unwrap_or(true) {
            let _ = self.child.kill();
        }
    }
}

#[test]
fn wait_without_synchronize_is_an_error_not_an_exit() -> anyhow::Result<()> {
    let mut original = NativeChild::spawn(73)?;
    let handle = original.duplicate(PROCESS_QUERY_LIMITED_INFORMATION, 0)?;
    let mut child = WinChild::new(handle, Arc::new(JobObject::create()?));
    assert!(original.is_running()?);
    let error = child
        .wait()
        .expect_err("query access cannot establish native termination");
    assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
    assert!(original.is_running()?);
    assert_eq!(original.release_and_observe()?, 73);
    Ok(())
}

#[test]
fn query_failure_after_native_signal_is_not_pending() -> anyhow::Result<()> {
    let mut original = NativeChild::spawn(74)?;
    let handle = original.duplicate(SYNCHRONIZE, 0)?;
    let mut child = WinChild::new(handle, Arc::new(JobObject::create()?));
    assert!(original.is_running()?);
    assert!(child.try_wait()?.is_none());
    assert_eq!(original.release_and_observe()?, 74);
    let error = child
        .try_wait()
        .expect_err("native signal does not grant query access");
    assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
    Ok(())
}

#[test]
fn signaled_process_can_have_exit_code_259() -> anyhow::Result<()> {
    let mut original = NativeChild::spawn(259)?;
    let handle = original.duplicate(0, DUPLICATE_SAME_ACCESS)?;
    let mut child = WinChild::new(handle, Arc::new(JobObject::create()?));
    assert!(original.is_running()?);
    assert!(child.try_wait()?.is_none());
    assert_eq!(original.release_and_observe()?, 259);
    let status = child
        .try_wait()?
        .expect("signaled process is terminal even when its code is 259");
    assert_eq!(status.exit_code(), 259);
    assert_eq!(child.wait()?.exit_code(), 259);
    Ok(())
}

#[test]
fn native_child_fixture() -> anyhow::Result<()> {
    let Ok(exit_code) = std::env::var(CHILD_EXIT_ENV) else {
        return Ok(());
    };
    let exit_code: i32 = exit_code.parse()?;
    let mut release = [0u8; 1];
    std::io::stdin().read_exact(&mut release)?;
    assert_eq!(release, [1]);
    std::process::exit(exit_code);
}
