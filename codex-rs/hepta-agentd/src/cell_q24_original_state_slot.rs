//! Move the one original state out before I/O; the small slot mutex is never
//! held by an async continuation. A borrowed lease returns that same state.

use std::sync::Mutex;
use std::sync::TryLockError;

use super::Error;

pub(super) struct OriginalStateSlot<T> {
    state: Mutex<Option<Box<T>>>,
}

pub(super) struct OriginalStateLease<'a, T> {
    slot: &'a OriginalStateSlot<T>,
    state: Option<Box<T>>,
}

impl<T> OriginalStateSlot<T> {
    pub(super) fn new(state: T) -> Self {
        Self {
            state: Mutex::new(Some(Box::new(state))),
        }
    }

    #[cfg(test)]
    pub(super) fn get_mut(&mut self) -> Result<&mut T, Error> {
        self.state
            .get_mut()
            .map_err(|_| Error::CommitUncertain)?
            .as_deref_mut()
            .ok_or(Error::CommitUncertain)
    }

    pub(super) fn try_take(&self) -> Result<OriginalStateLease<'_, T>, Error> {
        let mut slot = self.state.try_lock().map_err(|error| match error {
            TryLockError::WouldBlock => Error::QueueFull,
            TryLockError::Poisoned(_) => Error::CommitUncertain,
        })?;
        let state = slot.take().ok_or(Error::QueueFull)?;
        Ok(OriginalStateLease {
            slot: self,
            state: Some(state),
        })
    }
}

impl<T> OriginalStateLease<'_, T> {
    pub(super) fn state(&self) -> Result<&T, Error> {
        self.state.as_deref().ok_or(Error::CommitUncertain)
    }

    pub(super) fn state_mut(&mut self) -> Result<&mut T, Error> {
        self.state.as_deref_mut().ok_or(Error::CommitUncertain)
    }
}

impl<T> Drop for OriginalStateLease<'_, T> {
    fn drop(&mut self) {
        // No slot access suspends or invokes external code. On poisoning, keep
        // the slot unavailable and drop the capabilities instead of recovering.
        if let Ok(mut slot) = self.slot.state.lock()
            && slot.is_none()
        {
            *slot = self.state.take();
        }
    }
}

#[cfg(test)]
#[path = "cell_q24_original_state_slot_tests.rs"]
mod tests;
