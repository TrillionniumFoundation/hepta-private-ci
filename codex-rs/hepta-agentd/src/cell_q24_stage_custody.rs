//! Private ownership of one original stage state between synchronous slot moves.
//! Admission remains occupied while the same boxed state crosses async work.
//! Returning that mutated state never restores a consumed inner channel.

use tokio::sync::Mutex;
use tokio::sync::Semaphore;
use tokio::sync::SemaphorePermit;

use super::Error;

pub(super) struct OriginalStageSlot<T> {
    admission: Semaphore,
    value: Mutex<Option<Box<T>>>,
}

#[must_use]
pub(super) struct OriginalStageLease<'a, T> {
    slot: &'a OriginalStageSlot<T>,
    value: Option<Box<T>>,
    // Drop restores the value before this admission is released.
    _admission: SemaphorePermit<'a>,
}

impl<T> OriginalStageSlot<T> {
    pub(super) fn new(value: T) -> Self {
        Self {
            admission: Semaphore::new(/*permits*/ 1),
            value: Mutex::new(Some(Box::new(value))),
        }
    }

    pub(super) fn try_lease(&self) -> Result<OriginalStageLease<'_, T>, Error> {
        // This is immediate admission, just like the former try_lock. There
        // is no wait, new queue, or permit-changing API.
        let admission = self.admission.try_acquire().map_err(|_| Error::QueueFull)?;
        let value = {
            let mut slot = self.value.try_lock().map_err(|_| Error::QueueFull)?;
            slot.take().ok_or(Error::CommitUncertain)?
        };
        Ok(OriginalStageLease {
            slot: self,
            value: Some(value),
            _admission: admission,
        })
    }
}

impl<T> OriginalStageLease<'_, T> {
    pub(super) fn value(&self) -> Result<&T, Error> {
        self.value.as_deref().ok_or(Error::CommitUncertain)
    }

    pub(super) fn value_mut(&mut self) -> Result<&mut T, Error> {
        self.value.as_deref_mut().ok_or(Error::CommitUncertain)
    }
}

impl<T> Drop for OriginalStageLease<'_, T> {
    fn drop(&mut self) {
        let Some(value) = self.value.take() else {
            return;
        };
        // Every slot user first needs the same held admission. The normal
        // restore therefore cannot compete with another take or restore.
        let Ok(mut slot) = self.slot.value.try_lock() else {
            return;
        };
        if slot.is_some() {
            // Conflicting state is an internal fence, never a replacement
            // capability. Drop both values after releasing the slot guard.
            let conflicting = slot.take();
            drop(slot);
            drop(conflicting);
            return;
        }
        // Return the same allocation with its current failed/request bits,
        // receipt pins, budgets, and None for every consumed inner capability.
        *slot = Some(value);
    }
}

#[cfg(test)]
#[path = "cell_q24_stage_custody_tests.rs"]
mod tests;
