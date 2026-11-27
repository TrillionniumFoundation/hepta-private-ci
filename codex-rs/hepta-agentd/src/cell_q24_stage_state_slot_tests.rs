use std::future::Future;
use std::future::pending;
use std::panic::catch_unwind;
use std::panic::resume_unwind;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use pretty_assertions::assert_eq;

use super::Error;
use super::StageSlot;

#[derive(Debug, Eq, PartialEq)]
struct Continuation {
    failed: bool,
    initial: Option<Box<u64>>,
    observations: Vec<u64>,
}

#[test]
fn lease_retains_original_state_across_a_returned_operation() -> Result<(), Error> {
    let original = Box::new(7_u64);
    let original_address = std::ptr::from_ref(original.as_ref());
    let slot = StageSlot::new(Continuation {
        failed: false,
        initial: Some(original),
        observations: Vec::new(),
    });
    let mut operation = slot.try_take()?;
    operation.state_mut()?.failed = true;
    operation.state_mut()?.observations.push(1);

    // Borrowing the state ending does not release operation-level custody.
    assert!(matches!(slot.try_take(), Err(Error::QueueFull)));
    // Actual state ownership, rather than a held mutex guard, fences admission.
    {
        let stored = slot.state.try_lock().map_err(|_| Error::CommitUncertain)?;
        assert!(stored.is_none());
    }
    let mut returned_evidence = operation;
    assert!(matches!(slot.try_take(), Err(Error::QueueFull)));
    returned_evidence.state_mut()?.observations.push(2);
    returned_evidence.state_mut()?.failed = false;
    drop(returned_evidence);

    let mut retained = slot.try_take()?;
    let state = retained.state_mut()?;
    assert_eq!(
        state,
        &Continuation {
            failed: false,
            initial: Some(Box::new(7)),
            observations: vec![1, 2],
        }
    );
    let original = state.initial.as_ref().ok_or(Error::CommitUncertain)?;
    assert!(std::ptr::eq(original.as_ref(), original_address));
    Ok(())
}

#[test]
fn cancelling_a_pending_operation_keeps_failure_and_consumed_channel() -> Result<(), Error> {
    let slot = StageSlot::new(Continuation {
        failed: false,
        initial: Some(Box::new(9)),
        observations: Vec::new(),
    });
    let mut future = Box::pin(async {
        let mut operation = slot.try_take()?;
        let state = operation.state_mut()?;
        state.failed = true;
        let _original_channel = state.initial.take().ok_or(Error::CommitUncertain)?;
        state.observations.push(1);
        pending::<()>().await;
        Ok::<(), Error>(())
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut context).is_pending());
    assert!(matches!(slot.try_take(), Err(Error::QueueFull)));
    drop(future);

    let mut retained = slot.try_take()?;
    assert_eq!(
        retained.state_mut()?,
        &Continuation {
            failed: true,
            initial: None,
            observations: vec![1],
        }
    );
    Ok(())
}

#[test]
fn error_return_preserves_the_modified_continuation() -> Result<(), Error> {
    let slot = StageSlot::new(Continuation {
        failed: false,
        initial: Some(Box::new(11)),
        observations: Vec::new(),
    });
    let mut future = Box::pin(async {
        let mut operation = slot.try_take()?;
        let state = operation.state_mut()?;
        state.failed = true;
        state.initial.take().ok_or(Error::CommitUncertain)?;
        state.observations.push(1);
        Err::<(), Error>(Error::CommitUncertain)
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(matches!(
        future.as_mut().poll(&mut context),
        Poll::Ready(Err(Error::CommitUncertain))
    ));
    drop(future);

    let mut retained = slot.try_take()?;
    assert_eq!(
        retained.state_mut()?,
        &Continuation {
            failed: true,
            initial: None,
            observations: vec![1],
        }
    );
    Ok(())
}

#[test]
fn poisoned_slot_never_reissues_a_retained_continuation() -> Result<(), Error> {
    let slot = StageSlot::new(Continuation {
        failed: false,
        initial: Some(Box::new(13)),
        observations: Vec::new(),
    });
    let mut operation = slot.try_take()?;
    operation.state_mut()?.failed = true;
    let poisoned = catch_unwind(|| {
        let guard = slot.state.lock();
        assert!(guard.is_ok());
        let _guard = guard.ok();
        resume_unwind(Box::new("private slot poison fixture"));
    });
    assert!(poisoned.is_err());
    drop(operation);
    assert!(matches!(slot.try_take(), Err(Error::CommitUncertain)));
    assert!(matches!(slot.try_take(), Err(Error::CommitUncertain)));
    Ok(())
}
