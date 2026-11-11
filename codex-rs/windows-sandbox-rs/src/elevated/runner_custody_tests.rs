use super::super::custody::RunnerCustodyRegistry;
use super::super::tests::OwnedFixtureChild;
use super::super::tests::blocked_fixture;
use super::RunnerProcessOwner;
use anyhow::Context;
use anyhow::Result;
use codex_utils_pty::ProcessCleanupObservation;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::io::Write;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc as std_mpsc;
use std::time::Duration;
use std::time::Instant;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

type FailureFenceHandshake = (std_mpsc::Sender<()>, std_mpsc::Receiver<()>);

thread_local! {
    static FAILURE_FENCE_HANDSHAKE: RefCell<Option<FailureFenceHandshake>> = const { RefCell::new(None) };
}

pub(super) fn after_failure_fence() {
    let handshake = FAILURE_FENCE_HANDSHAKE.with(|slot| slot.borrow_mut().take());
    if let Some((entered, release)) = handshake {
        assert!(
            entered.send(()).is_ok(),
            "failure fence observer is retained"
        );
        assert!(
            release.recv_timeout(Duration::from_secs(5)).is_ok(),
            "fixture releases cleanup within its original bound"
        );
    }
}

fn duplicate_with_access(child: &OwnedFixtureChild, access: u32) -> Result<OwnedHandle> {
    let mut reduced: HANDLE = 0;
    if unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            child.0.as_raw_handle() as HANDLE,
            GetCurrentProcess(),
            &mut reduced,
            access,
            0,
            0,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(reduced as _) })
}

fn observation_handle(child: &OwnedFixtureChild) -> Result<OwnedHandle> {
    duplicate_with_access(
        child,
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
    )
}

fn release_fixture(child: &mut OwnedFixtureChild) -> Result<()> {
    child
        .0
        .stdin
        .take()
        .context("fixture stdin")?
        .write_all(b"release\n")?;
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 5_000) },
        WAIT_OBJECT_0
    );
    assert_eq!(child.0.wait()?.code(), Some(23));
    Ok(())
}

#[test]
fn reservation_and_confirmed_exit_release_only_their_exact_slot() -> Result<()> {
    let registry = Arc::new(RunnerCustodyRegistry::default());
    let abandoned = registry.reserve()?;
    assert_eq!(registry.retained_count(), 1);
    drop(abandoned);
    assert_eq!(registry.retained_count(), 0);

    let mut completed_child = blocked_fixture()?;
    let mut unknown_child = blocked_fixture()?;
    let mut completed = RunnerProcessOwner::from_admission(
        completed_child.0.as_handle().try_clone_to_owned()?,
        registry.reserve()?,
    );
    let mut unknown = RunnerProcessOwner::from_admission(
        observation_handle(&unknown_child)?,
        registry.reserve()?,
    );
    completed.arm_timeout(Some(5_000))?;
    unknown.arm_timeout(Some(5_000))?;
    let original = unknown.reconcile_failure(anyhow::anyhow!("original transport failed"));
    assert!(format!("{original:#}").contains("original transport failed"));
    assert!(format!("{original:#}").contains("terminal state unknown"));
    drop(unknown);
    assert_eq!(registry.retained_count(), 2);
    assert!(registry.reserve().is_err());

    release_fixture(&mut completed_child)?;
    completed.wait_for_exit(23, || false)?;
    assert_eq!(registry.retained_count(), 1);
    assert!(
        registry.reserve().is_err(),
        "another unknown owner still fences admission"
    );
    release_fixture(&mut unknown_child)?;
    let reconciled = registry.reconcile()?;
    assert_eq!(reconciled.len(), 1);
    assert!(reconciled[0].original_failed);
    assert_eq!(
        reconciled
            .into_iter()
            .next()
            .context("unknown owner receipt")?
            .observation?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(23)
        },
    );
    assert_eq!(registry.retained_count(), 0);
    drop(registry.reserve()?);
    Ok(())
}

#[tokio::test]
async fn session_custody_survives_taken_terminator_and_driver_disconnect() -> Result<()> {
    let registry = Arc::new(RunnerCustodyRegistry::default());
    let mut child = blocked_fixture()?;
    let mut owner =
        RunnerProcessOwner::from_admission(observation_handle(&child)?, registry.reserve()?);
    owner.arm_timeout(Some(5_000))?;
    let custody = owner.cleanup_custody()?;
    let weak = Arc::downgrade(&custody);
    let (writer_tx, _writer_rx) = mpsc::channel(1);
    let (stdout_tx, stdout_rx) = broadcast::channel(8);
    let (exit_tx, exit_rx) = oneshot::channel();
    let terminations = Arc::new(AtomicUsize::new(0));
    let seen = Arc::clone(&terminations);
    let mut spawned = spawn_from_driver(ProcessDriver {
        writer_tx,
        stdout_rx,
        stderr_rx: None,
        exit_rx,
        terminator: Some(Box::new(move || {
            seen.fetch_add(1, Ordering::SeqCst);
        })),
        writer_handle: None,
        resizer: None,
        tty: false,
    });
    spawned
        .session
        .retain_cleanup_custody(Arc::clone(&custody))?;
    assert_eq!(
        spawned
            .session
            .retain_cleanup_custody(Arc::clone(&custody))
            .expect_err("native custody cannot be replaced")
            .kind(),
        std::io::ErrorKind::AlreadyExists,
    );
    let original = owner.reconcile_failure(anyhow::anyhow!("driver disconnected"));
    drop(owner);
    drop(original);
    drop(custody);
    drop(exit_tx);
    assert!(
        tokio::time::timeout(Duration::from_secs(2), &mut spawned.exit_rx)
            .await?
            .is_err()
    );
    spawned.session.request_terminate();
    spawned.session.request_terminate();
    assert_eq!(terminations.load(Ordering::SeqCst), 1);
    assert!(weak.upgrade().is_some());
    assert!(registry.reserve().is_err());
    assert_eq!(
        spawned.session.observe_cleanup()?,
        Some(ProcessCleanupObservation::NoTerminalObservation),
    );
    assert!(!spawned.session.has_exited());
    assert_eq!(spawned.session.exit_code(), None);

    release_fixture(&mut child)?;
    assert_eq!(
        spawned.session.observe_cleanup()?,
        Some(ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(23)
        }),
    );
    assert_eq!(registry.retained_count(), 0);
    assert!(
        weak.upgrade().is_some(),
        "the session independently retains the same capability"
    );
    assert!(
        !spawned.session.has_exited(),
        "late cleanup cannot change the failed driver result"
    );
    assert_eq!(spawned.session.exit_code(), None);
    drop(stdout_tx);
    drop(spawned);
    assert!(weak.upgrade().is_none());
    Ok(())
}

#[test]
fn dropped_sync_error_retains_owner_until_late_same_handle_observation() -> Result<()> {
    let registry = Arc::new(RunnerCustodyRegistry::default());
    let mut child = blocked_fixture()?;
    let mut owner =
        RunnerProcessOwner::from_admission(observation_handle(&child)?, registry.reserve()?);
    owner.arm_timeout(Some(1_000))?;
    let original_deadline = Instant::now();
    owner.process.deadline = Some(original_deadline);
    let error = owner
        .wait_for_exit(23, || false)
        .expect_err("the original command budget expired");
    assert!(format!("{error:#}").contains("within the original budget"));
    let error = owner.reconcile_failure(error);
    assert_eq!(owner.process.observation_deadline, Some(original_deadline));
    assert_eq!(owner.process.native_exit_code, None);
    let weak = Arc::downgrade(
        owner
            .custody
            .as_ref()
            .context("registered native custody")?,
    );
    drop(owner);
    drop(error);
    assert!(
        weak.upgrade().is_some(),
        "dropping anyhow/worker cannot discard the native owner"
    );
    assert!(registry.reserve().is_err());
    let pending = registry.reconcile()?;
    assert_eq!(pending.len(), 1);
    assert!(pending[0].original_failed);
    assert_eq!(
        pending
            .into_iter()
            .next()
            .context("pending owner receipt")?
            .observation?,
        ProcessCleanupObservation::NoTerminalObservation,
    );

    release_fixture(&mut child)?;
    let mut late = registry.reconcile()?;
    assert_eq!(late.len(), 1);
    let late = late.pop().context("late cleanup receipt")?;
    assert!(
        late.original_failed,
        "the expired original task must remain failed"
    );
    assert_eq!(late.observed_after_deadline, Some(true));
    assert_eq!(
        late.observation?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(23)
        },
    );
    assert_eq!(registry.retained_count(), 0);
    assert!(weak.upgrade().is_none());
    drop(registry.reserve()?);
    Ok(())
}

#[test]
fn unarmed_startup_abort_keeps_custody_until_zero_wait_terminal_query() -> Result<()> {
    let registry = Arc::new(RunnerCustodyRegistry::default());
    let mut child = blocked_fixture()?;
    let owner = RunnerProcessOwner::from_admission(
        child.0.as_handle().try_clone_to_owned()?,
        registry.reserve()?,
    );
    drop(owner);
    assert_eq!(
        registry.retained_count(),
        1,
        "startup abort does not fabricate a terminal receipt"
    );
    assert!(registry.reserve().is_err());
    assert_eq!(
        unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 5_000) },
        WAIT_OBJECT_0,
    );
    assert_eq!(child.0.wait()?.code(), Some(1));
    let mut cleanup = registry.reconcile()?;
    assert_eq!(cleanup.len(), 1);
    let cleanup = cleanup.pop().context("startup cleanup receipt")?;
    assert!(cleanup.original_failed);
    assert_eq!(cleanup.observed_after_deadline, None);
    assert_eq!(
        cleanup.observation?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(1)
        },
    );
    assert_eq!(registry.retained_count(), 0);
    Ok(())
}

#[test]
fn failure_fences_admission_before_native_abort_or_wait() -> Result<()> {
    let registry = Arc::new(RunnerCustodyRegistry::default());
    let mut child = blocked_fixture()?;
    let mut owner = RunnerProcessOwner::from_admission(
        child.0.as_handle().try_clone_to_owned()?,
        registry.reserve()?,
    );
    owner.arm_timeout(Some(5_000))?;
    let deadline = owner.process.deadline;
    let (entered_tx, entered_rx) = std_mpsc::channel();
    let (release_tx, release_rx) = std_mpsc::channel();
    let (done_tx, done_rx) = std_mpsc::channel();
    let worker = std::thread::spawn(move || {
        FAILURE_FENCE_HANDSHAKE.with(|slot| *slot.borrow_mut() = Some((entered_tx, release_rx)));
        let error = owner.reconcile_failure(anyhow::anyhow!("original reader failed"));
        let _ = done_tx.send((
            error,
            owner.process.deadline,
            owner.process.native_exit_code,
        ));
    });
    let entered = entered_rx.recv_timeout(Duration::from_secs(5));
    let refused = registry.reserve().is_err();
    let native_before_abort = unsafe { WaitForSingleObject(child.0.as_raw_handle() as HANDLE, 0) };
    let _ = release_tx.send(());
    let result = done_rx.recv_timeout(Duration::from_secs(5));
    worker
        .join()
        .map_err(|_| anyhow::anyhow!("failure cleanup worker panicked"))?;
    entered?;
    assert!(
        refused,
        "no new owner may enter while the failed owner begins cleanup"
    );
    assert_eq!(native_before_abort, WAIT_TIMEOUT);
    let (error, unchanged_deadline, exit_code) = result?;
    assert!(format!("{error:#}").contains("original reader failed"));
    assert_eq!(unchanged_deadline, deadline);
    assert_eq!(exit_code, Some(1));
    assert_eq!(child.0.wait()?.code(), Some(1));
    assert_eq!(registry.retained_count(), 0);
    Ok(())
}

#[test]
fn cleanup_query_access_failures_fence_without_reclassifying_original_work() -> Result<()> {
    for access in [PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE] {
        let registry = Arc::new(RunnerCustodyRegistry::default());
        let mut child = blocked_fixture()?;
        let mut owner = RunnerProcessOwner::from_admission(
            duplicate_with_access(&child, access)?,
            registry.reserve()?,
        );
        owner.arm_timeout(Some(5_000))?;
        let custody = owner.cleanup_custody()?;
        if access == PROCESS_SYNCHRONIZE {
            assert_eq!(
                custody.observe_cleanup()?,
                ProcessCleanupObservation::NoTerminalObservation
            );
            release_fixture(&mut child)?;
        }
        let error = custody
            .observe_cleanup()
            .expect_err("the exact handle lacks a required observation right");
        assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
        assert!(
            !owner.failed,
            "a cleanup query must not rewrite the original command result"
        );
        assert!(registry.reserve().is_err());
        let mut facts = registry.reconcile()?;
        assert_eq!(facts.len(), 1);
        let facts = facts.pop().context("unresolved cleanup receipt")?;
        assert!(!facts.original_failed);
        assert!(facts.cleanup_observation_lost);
        assert!(facts.observation.is_err());
        assert_eq!(registry.retained_count(), 1);
    }
    Ok(())
}
