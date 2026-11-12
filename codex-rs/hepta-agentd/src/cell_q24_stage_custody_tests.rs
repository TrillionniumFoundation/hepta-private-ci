//! In-memory custody regressions. These construct no owner or authority.

use std::future::Future;
use std::future::pending;
use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use pretty_assertions::assert_eq;

use super::Error;
use super::OriginalStageSlot;

#[derive(Debug, Eq, PartialEq)]
struct Capability(u64);

#[derive(Debug, Eq, PartialEq)]
struct State {
    initial: [Option<Capability>; 4],
    channel: Option<Capability>,
    failed: bool,
    selection_requested: bool,
    completion_requested: bool,
    version_requests: usize,
    retained: Vec<u8>,
}

fn initial_state() -> State {
    State {
        initial: [
            Some(Capability(11)),
            Some(Capability(12)),
            Some(Capability(13)),
            Some(Capability(14)),
        ],
        channel: Some(Capability(21)),
        failed: false,
        selection_requested: false,
        completion_requested: false,
        version_requests: 7,
        retained: vec![31, 32],
    }
}

#[test]
fn another_thread_is_rejected_while_original_state_is_owned() -> Result<(), Error> {
    let slot = OriginalStageSlot::new(initial_state());
    let lease = slot.try_lease()?;
    let address = std::ptr::from_ref(lease.value()?);
    std::thread::scope(|scope| {
        let competing = scope.spawn(|| matches!(slot.try_lease(), Err(Error::QueueFull)));
        assert_eq!(competing.join().ok(), Some(true));
    });
    drop(lease);
    let next = slot.try_lease()?;
    assert_eq!(std::ptr::from_ref(next.value()?), address);
    assert_eq!(next.value()?, &initial_state());
    Ok(())
}

#[test]
fn an_error_keeps_partial_one_way_consumption_in_the_same_allocation() -> Result<(), Error> {
    let mut expected = initial_state();
    expected.initial[1] = None;
    let slot = OriginalStageSlot::new(expected);
    let address = {
        let lease = slot.try_lease()?;
        std::ptr::from_ref(lease.value()?)
    };
    let failed = || -> Result<(), Error> {
        let mut lease = slot.try_lease()?;
        let state = lease.value_mut()?;
        state.failed = true;
        state.selection_requested = true;
        state.version_requests += 1;
        let _first = state.initial[0].take().ok_or(Error::CommitUncertain)?;
        let _second = state.initial[1].take().ok_or(Error::CommitUncertain)?;
        Ok(())
    };
    assert!(matches!(failed(), Err(Error::CommitUncertain)));
    let lease = slot.try_lease()?;
    let mut expected = initial_state();
    expected.initial[0] = None;
    expected.initial[1] = None;
    expected.failed = true;
    expected.selection_requested = true;
    expected.version_requests = 8;
    assert_eq!(std::ptr::from_ref(lease.value()?), address);
    assert_eq!(lease.value()?, &expected);
    Ok(())
}

#[test]
fn cancelling_a_polled_future_returns_mutated_state_without_its_channel() -> Result<(), Error> {
    let slot = OriginalStageSlot::new(initial_state());
    let address = AtomicUsize::new(/*v*/ 0);
    let resumed = AtomicBool::new(/*v*/ false);
    let mut operation = Box::pin(async {
        let mut lease = slot.try_lease()?;
        address.store(std::ptr::from_ref(lease.value()?) as usize, Ordering::SeqCst);
        let state = lease.value_mut()?;
        state.failed = true;
        state.selection_requested = true;
        state.completion_requested = true;
        state.version_requests += 1;
        let channel = state.channel.take().ok_or(Error::CommitUncertain)?;
        pending::<()>().await;
        resumed.store(/*val*/ true, Ordering::SeqCst);
        drop(channel);
        Ok::<(), Error>(())
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(matches!(operation.as_mut().poll(&mut context), Poll::Pending));
    assert!(matches!(slot.try_lease(), Err(Error::QueueFull)));
    drop(operation);
    let lease = slot.try_lease()?;
    let mut expected = initial_state();
    expected.channel = None;
    expected.failed = true;
    expected.selection_requested = true;
    expected.completion_requested = true;
    expected.version_requests = 8;
    assert_eq!(
        std::ptr::from_ref(lease.value()?) as usize,
        address.load(Ordering::SeqCst)
    );
    assert_eq!(lease.value()?, &expected);
    assert!(!resumed.load(Ordering::SeqCst));
    Ok(())
}

#[test]
fn refusing_the_second_lease_returns_the_first_without_rebuilding_it() -> Result<(), Error> {
    let common = OriginalStageSlot::new(initial_state());
    let candidate = OriginalStageSlot::new(initial_state());
    let address = {
        let lease = common.try_lease()?;
        std::ptr::from_ref(lease.value()?)
    };
    let occupied = candidate.try_lease()?;
    let attempt = || -> Result<(), Error> {
        let _common = common.try_lease()?;
        let _candidate = candidate.try_lease()?;
        Ok(())
    };
    assert!(matches!(attempt(), Err(Error::QueueFull)));
    let restored = common.try_lease()?;
    assert_eq!(std::ptr::from_ref(restored.value()?), address);
    assert_eq!(restored.value()?, &initial_state());
    drop(occupied);
    Ok(())
}

#[test]
fn original_scope_release_allows_a_later_phase_with_the_same_state() -> Result<(), Error> {
    let slot = OriginalStageSlot::new(initial_state());
    let address;
    {
        let mut lease = slot.try_lease()?;
        address = std::ptr::from_ref(lease.value()?);
        lease.value_mut()?.failed = true;
    }
    // Model's predecessor phase must be able to observe the released state.
    {
        let lease = slot.try_lease()?;
        assert!(lease.value()?.failed);
        assert_eq!(std::ptr::from_ref(lease.value()?), address);
    }
    {
        let mut lease = slot.try_lease()?;
        lease.value_mut()?.retained.push(33);
        lease.value_mut()?.failed = false;
    }
    let lease = slot.try_lease()?;
    let mut expected = initial_state();
    expected.retained.push(33);
    assert_eq!(std::ptr::from_ref(lease.value()?), address);
    assert_eq!(lease.value()?, &expected);
    Ok(())
}

struct ReleaseProbe {
    slot: Weak<OriginalStageSlot<ReleaseProbe>>,
    dropped: Arc<AtomicUsize>,
    admission_released_early: Arc<AtomicBool>,
}

impl Drop for ReleaseProbe {
    fn drop(&mut self) {
        if let Some(slot) = self.slot.upgrade()
            && slot.admission.available_permits() != 0
        {
            self.admission_released_early.store(/*val*/ true, Ordering::SeqCst);
        }
        self.dropped.fetch_add(/*val*/ 1, Ordering::SeqCst);
    }
}

#[test]
fn an_internal_restore_conflict_retires_both_values_before_releasing_admission() -> Result<(), Error> {
    let dropped = Arc::new(AtomicUsize::new(/*v*/ 0));
    let admission_released_early = Arc::new(AtomicBool::new(/*v*/ false));
    let slot = Arc::new(OriginalStageSlot::new(ReleaseProbe {
        slot: Weak::new(),
        dropped: Arc::clone(&dropped),
        admission_released_early: Arc::clone(&admission_released_early),
    }));
    let mut lease = slot.try_lease()?;
    lease.value_mut()?.slot = Arc::downgrade(&slot);
    // Deliberate test-only corruption while this test owns the sole admission.
    // Production has no access to the private slot or permit-changing methods.
    *slot.value.try_lock().map_err(|_| Error::QueueFull)? = Some(Box::new(ReleaseProbe {
        slot: Arc::downgrade(&slot),
        dropped: Arc::clone(&dropped),
        admission_released_early: Arc::clone(&admission_released_early),
    }));
    drop(lease);
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
    assert!(!admission_released_early.load(Ordering::SeqCst));
    assert!(matches!(slot.try_lease(), Err(Error::CommitUncertain)));
    Ok(())
}
