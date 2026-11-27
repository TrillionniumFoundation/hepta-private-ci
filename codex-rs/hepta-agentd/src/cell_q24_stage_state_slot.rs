//! Exclusive original continuation custody without a mutex guard across await.
//!
//! The short mutex only moves state into or out of one borrowed lease. An empty
//! slot remains unavailable for the whole operation, including returned evidence.
//! Drop restores the same modified state; it never resets failure bits or rebuilds
//! consumed channels. The caller alone clears its failure bit after final checks.

use std::sync::Mutex;
use std::sync::TryLockError;

use super::Error;

pub(super) struct StageSlot<T> {
    state: Mutex<Option<T>>,
}

#[must_use]
pub(super) struct StageLease<'a, T> {
    slot: &'a StageSlot<T>,
    state: Option<T>,
}

impl<T> StageSlot<T> {
    pub(super) fn new(state: T) -> Self {
        Self {
            state: Mutex::new(Some(state)),
        }
    }

    pub(super) fn try_take(&self) -> Result<StageLease<'_, T>, Error> {
        let state = {
            let mut slot = match self.state.try_lock() {
                Ok(slot) => slot,
                Err(TryLockError::WouldBlock) => return Err(Error::QueueFull),
                Err(TryLockError::Poisoned(_)) => return Err(Error::CommitUncertain),
            };
            slot.take().ok_or(Error::QueueFull)?
        };
        Ok(StageLease {
            slot: self,
            state: Some(state),
        })
    }
}

impl<T> StageLease<'_, T> {
    pub(super) fn state_mut(&mut self) -> Result<&mut T, Error> {
        self.state.as_mut().ok_or(Error::CommitUncertain)
    }
}

impl<T> Drop for StageLease<'_, T> {
    fn drop(&mut self) {
        // No await, owner callback, authentication or I/O runs under this lock.
        // A poisoned slot stays poisoned; never turn it into a fresh admission.
        if let Ok(mut slot) = self.slot.state.lock()
            && slot.is_none()
        {
            *slot = self.state.take();
        }
    }
}

#[cfg(test)]
#[path = "cell_q24_stage_state_slot_tests.rs"]
mod tests;
