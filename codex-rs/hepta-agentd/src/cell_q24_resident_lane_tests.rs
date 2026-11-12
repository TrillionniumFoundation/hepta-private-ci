//! State-ownership mechanics only. These cases do not create owner authority.

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;

use pretty_assertions::assert_eq;

use super::Error;
use super::ResidentLane;

struct Original {
    identity: Box<u8>,
    failed: bool,
    dropped: Arc<AtomicUsize>,
}

impl Drop for Original {
    fn drop(&mut self) {
        self.dropped.fetch_add(1, Ordering::SeqCst);
    }
}

fn original(dropped: &Arc<AtomicUsize>, identity: u8) -> Original {
    Original {
        identity: Box::new(identity),
        failed: false,
        dropped: Arc::clone(dropped),
    }
}

#[tokio::test]
async fn cancelled_lease_returns_original_identity_and_failure_fence() -> anyhow::Result<()> {
    let dropped = Arc::new(AtomicUsize::new(0));
    let value = original(&dropped, 7);
    let identity = value.identity.as_ref() as *const u8 as usize;
    let lane = ResidentLane::new(value);
    let mut pending = Box::pin(async {
        let mut lease = lane.try_take()?;
        lease.state_mut()?.failed = true;
        std::future::pending::<()>().await;
        Ok::<(), Error>(())
    });
    let state = std::future::poll_fn(|cx| Poll::Ready(pending.as_mut().poll(cx))).await;
    assert!(state.is_pending());
    assert!(matches!(lane.try_take(), Err(Error::QueueFull)));
    // The original value is exclusively leased, but the storage mutex is free.
    assert!(lane.slot.try_lock().is_ok());
    drop(pending);
    assert_eq!(dropped.load(Ordering::SeqCst), 0);
    {
        let mut lease = lane.try_take()?;
        let original = lease.state_mut()?;
        assert!(original.failed);
        assert_eq!(original.identity.as_ref() as *const u8 as usize, identity);
        original.failed = false;
    }
    {
        let mut lease = lane.try_take()?;
        assert!(!lease.state_mut()?.failed);
    }
    drop(lane);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    Ok(())
}

#[test]
fn conflicting_return_fences_without_replacing_the_existing_value() -> anyhow::Result<()> {
    let dropped = Arc::new(AtomicUsize::new(0));
    let lane = ResidentLane::new(original(&dropped, 1));
    let lease = lane.try_take()?;
    {
        let mut slot = lane.slot.lock().map_err(|_| Error::CommitUncertain)?;
        slot.value = Some(Box::new(original(&dropped, 2)));
    }
    drop(lease);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert!(matches!(lane.try_take(), Err(Error::CommitUncertain)));
    {
        let slot = lane.slot.lock().map_err(|_| Error::CommitUncertain)?;
        assert!(slot.fenced);
        assert_eq!(slot.value.as_ref().map(|value| *value.identity), Some(2));
    }
    drop(lane);
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
    Ok(())
}

#[test]
fn poisoned_return_drops_original_and_never_reopens_admission() -> anyhow::Result<()> {
    let dropped = Arc::new(AtomicUsize::new(0));
    let lane = Arc::new(ResidentLane::new(original(&dropped, 3)));
    let lease = lane.try_take()?;
    let shared = Arc::clone(&lane);
    let worker = std::thread::spawn(move || {
        let _slot = match shared.slot.lock() {
            Ok(slot) => slot,
            Err(_) => return,
        };
        panic!("intentional poison while the original value is leased");
    });
    assert!(worker.join().is_err());
    drop(lease);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert!(matches!(lane.try_take(), Err(Error::CommitUncertain)));
    Ok(())
}
