use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use tokio::time::timeout;

use super::SingleInstanceLock;
use super::run_owned;

struct RetiredOwner {
    path: PathBuf,
    retired_while_locked: Arc<AtomicBool>,
}

impl Drop for RetiredOwner {
    fn drop(&mut self) {
        self.retired_while_locked.store(
            SingleInstanceLock::acquire(&self.path).is_err(),
            Ordering::Release,
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoned_startup_waiter_keeps_flock_through_work_and_result_retirement() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("owner.lock");
    let owner = Arc::new(SingleInstanceLock::acquire(&path)?);
    let retired = Arc::new(AtomicBool::new(false));
    let (entered, entry) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let retirement = Arc::clone(&retired);
    let owned_path = path.clone();
    let waiter = tokio::spawn(run_owned(owner, move || {
        let _ = entered.send(());
        released
            .recv()
            .map_err(|error| crate::SupervisorError::Invalid(error.to_string()))?;
        Ok(RetiredOwner {
            path: owned_path,
            retired_while_locked: retirement,
        })
    }));
    timeout(Duration::from_secs(5), entry).await??;
    waiter.abort();
    assert!(matches!(waiter.await, Err(error) if error.is_cancelled()));
    assert!(SingleInstanceLock::acquire(&path).is_err());
    release.send(())?;
    let _next_owner = timeout(Duration::from_secs(5), async {
        while !retired.load(Ordering::Acquire) {
            tokio::task::yield_now().await;
        }
        // The outcome destructor proves that it retired under the original
        // lock. Its following instance field may still be dropping; observe
        // actual flock retirement within this same five-second deadline.
        assert!(retired.load(Ordering::Acquire));
        loop {
            match SingleInstanceLock::acquire(&path) {
                Ok(next_owner) => return Ok::<_, crate::SupervisorError>(next_owner),
                Err(crate::SupervisorError::Io(error))
                    if error.kind() == std::io::ErrorKind::AddrInUse =>
                {
                    tokio::task::yield_now().await;
                }
                Err(error) => return Err(error),
            }
        }
    })
    .await??;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn failed_startup_keeps_original_flock_until_the_queued_error_is_observed() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("owner.lock");
    let owner = Arc::new(SingleInstanceLock::acquire(&path)?);
    let (entered, entry) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let waiter = tokio::spawn(run_owned(owner, move || {
        let _ = entered.send(());
        released
            .recv()
            .map_err(|error| crate::SupervisorError::Invalid(error.to_string()))?;
        Err::<(), _>(crate::SupervisorError::Invalid(
            "original startup work failed".into(),
        ))
    }));
    timeout(Duration::from_secs(5), entry).await??;
    assert!(SingleInstanceLock::acquire(&path).is_err());
    release.send(())?;
    let result = waiter.await??;
    assert!(result.outcome.is_err());
    assert!(SingleInstanceLock::acquire(&path).is_err());
    drop(result);
    SingleInstanceLock::acquire(&path)?;
    Ok(())
}
