use std::future::Future;
use std::task::Context;
use std::task::Waker;

use pretty_assertions::assert_eq;

use super::Error;
use super::OriginalStateSlot;

#[derive(Debug, Eq, PartialEq)]
struct OriginalState {
    failed: bool,
    records: Vec<u64>,
}

#[test]
fn original_state_is_exclusive_and_keeps_its_identity() -> Result<(), Error> {
    let slot = OriginalStateSlot::new(OriginalState {
        failed: false,
        records: vec![11],
    });
    let mut lease = slot.try_take()?;
    let address = std::ptr::from_ref(lease.state()?);
    assert!(matches!(slot.try_take(), Err(Error::QueueFull)));
    lease.state_mut()?.records.push(29);
    drop(lease);
    let lease = slot.try_take()?;
    assert!(std::ptr::eq(address, lease.state()?));
    assert_eq!(
        lease.state()?,
        &OriginalState {
            failed: false,
            records: vec![11, 29],
        }
    );
    Ok(())
}

#[test]
fn cancelled_original_operation_retains_its_failed_state() -> Result<(), Error> {
    let slot = OriginalStateSlot::new(OriginalState {
        failed: false,
        records: vec![17],
    });
    let mut operation = Box::pin(async {
        let mut lease = slot.try_take()?;
        lease.state_mut()?.failed = true;
        std::future::pending::<()>().await;
        lease.state_mut()?.failed = false;
        Ok::<(), Error>(())
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(operation.as_mut().poll(&mut context).is_pending());
    assert!(matches!(slot.try_take(), Err(Error::QueueFull)));
    drop(operation);
    let lease = slot.try_take()?;
    assert_eq!(
        lease.state()?,
        &OriginalState {
            failed: true,
            records: vec![17],
        }
    );
    Ok(())
}

#[test]
fn another_thread_cannot_take_a_live_original_state() -> Result<(), Error> {
    let slot = OriginalStateSlot::new(vec![19]);
    let lease = slot.try_take()?;
    let refused = std::thread::scope(|scope| {
        scope
            .spawn(|| matches!(slot.try_take(), Err(Error::QueueFull)))
            .join()
    })
    .map_err(|_| Error::CommitUncertain)?;
    assert!(refused);
    assert_eq!(lease.state()?, &vec![19]);
    drop(lease);
    assert_eq!(slot.try_take()?.state()?, &vec![19]);
    Ok(())
}

#[test]
fn poisoned_original_slot_never_recovers_authority() {
    let slot = OriginalStateSlot::new(vec![23]);
    let poisoned = std::panic::catch_unwind(|| {
        let guard = slot.state.lock();
        assert!(guard.is_ok());
        panic!("injected slot failure");
    });
    assert!(poisoned.is_err());
    assert!(matches!(slot.try_take(), Err(Error::CommitUncertain)));
}
