use super::JobObject;
use super::WinChild;
use crate::ProcessCleanupCustody;
use crate::ProcessCleanupObservation;
use crate::direct_child::PortableChild;
use crate::direct_custody::DirectCustody;
use crate::direct_custody::DirectLaunch;
use crate::direct_custody::DirectRegistry;
use crate::direct_custody::DirectWait;
use crate::direct_custody::ObservedExit;
use filedescriptor::OwnedHandle;
use portable_pty::Child as _;
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
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
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

struct DirectObservation {
    owner: Arc<PortableChild>,
    custody: Arc<DirectCustody>,
    waiter: DirectWait,
    exit_rx: tokio::sync::oneshot::Receiver<i32>,
    exited: Arc<AtomicBool>,
    code: Arc<Mutex<Option<i32>>>,
}

impl DirectObservation {
    fn new(
        launch: DirectLaunch,
        original: &NativeChild,
        access: DWORD,
        options: DWORD,
    ) -> anyhow::Result<Self> {
        let handle = original.duplicate(access, options)?;
        let owner = Arc::new(PortableChild::new(Box::new(WinChild::new(
            handle,
            Arc::new(JobObject::create()?),
        ))));
        launch.attach_owner(owner.clone())?;
        let custody = launch.custody();
        let (exit_tx, exit_rx) = tokio::sync::oneshot::channel();
        let exited = Arc::new(AtomicBool::new(false));
        let code = Arc::new(Mutex::new(None));
        let waiter = DirectWait::new(launch, Arc::clone(&exited), Arc::clone(&code), exit_tx);
        Ok(Self {
            owner,
            custody,
            waiter,
            exit_rx,
            exited,
            code,
        })
    }
}

#[tokio::test]
async fn direct_wait_failure_keeps_unknown_and_fences_admission() -> anyhow::Result<()> {
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let mut original = NativeChild::spawn(75)?;
    let observation = DirectObservation::new(
        launch,
        &original,
        PROCESS_QUERY_LIMITED_INFORMATION,
        /*options*/ 0,
    )?;
    assert!(original.is_running()?);
    let error = observation
        .owner
        .wait()
        .expect_err("missing synchronize must fail the actual wait");
    assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
    observation.waiter.finish(Err(error));
    assert!(
        tokio::time::timeout_at(original.deadline.into(), observation.exit_rx)
            .await?
            .is_err()
    );
    assert!(!observation.exited.load(Ordering::SeqCst));
    assert_eq!(
        *observation
            .code
            .lock()
            .map_err(|_| io::Error::other("test exit lock poisoned"))?,
        None
    );
    assert!(registry.reserve().is_err());
    assert!(observation.custody.observe_cleanup().is_err());
    assert!(original.is_running()?);
    assert_eq!(original.release_and_observe()?, 75);
    // The test's separate full-access handle cannot repair the retained rights.
    assert!(observation.custody.observe_cleanup().is_err());
    assert!(registry.reserve().is_err());
    Ok(())
}

#[tokio::test]
async fn direct_dropped_waiter_retains_same_child_for_late_cleanup() -> anyhow::Result<()> {
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let mut original = NativeChild::spawn(76)?;
    let observation =
        DirectObservation::new(launch, &original, /*access*/ 0, DUPLICATE_SAME_ACCESS)?;
    let waiter = observation.waiter;
    let owner = observation.owner;
    let unpolled = async move {
        waiter.finish(owner.wait().map(ObservedExit::from_portable));
    };
    drop(unpolled);
    assert!(
        tokio::time::timeout_at(original.deadline.into(), observation.exit_rx)
            .await?
            .is_err()
    );
    assert!(!observation.exited.load(Ordering::SeqCst));
    assert_eq!(
        *observation
            .code
            .lock()
            .map_err(|_| io::Error::other("test exit lock poisoned"))?,
        None
    );
    assert!(registry.reserve().is_err());
    assert_eq!(
        observation.custody.observe_cleanup()?,
        ProcessCleanupObservation::NoTerminalObservation
    );
    assert!(original.is_running()?);
    assert_eq!(original.release_and_observe()?, 76);
    assert_eq!(
        observation.custody.observe_cleanup()?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(76)
        },
    );
    assert!(registry.reserve().is_ok());
    // Cleanup evidence does not turn the failed original operation into success.
    assert!(!observation.exited.load(Ordering::SeqCst));
    assert_eq!(
        *observation
            .code
            .lock()
            .map_err(|_| io::Error::other("test exit lock poisoned"))?,
        None
    );
    Ok(())
}

#[tokio::test]
async fn direct_native_success_publishes_exit_before_releasing_observer() -> anyhow::Result<()> {
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let mut original = NativeChild::spawn(77)?;
    let observation =
        DirectObservation::new(launch, &original, /*access*/ 0, DUPLICATE_SAME_ACCESS)?;
    assert_eq!(original.release_and_observe()?, 77);
    observation
        .waiter
        .finish(observation.owner.wait().map(ObservedExit::from_portable));
    assert_eq!(
        tokio::time::timeout_at(original.deadline.into(), observation.exit_rx).await??,
        77
    );
    assert!(observation.exited.load(Ordering::SeqCst));
    assert_eq!(
        *observation
            .code
            .lock()
            .map_err(|_| io::Error::other("test exit lock poisoned"))?,
        Some(77)
    );
    assert_eq!(
        observation.custody.observe_cleanup()?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(77)
        },
    );
    assert!(registry.reserve().is_ok());
    Ok(())
}
