//! Exclusive resident state moves outside short synchronous lock scopes.
//! A lease owns the original non-Clone channels. Returning it preserves every
//! retained identity and cancellation fence; no I/O runs under a MutexGuard.

use std::sync::Mutex;
use std::sync::TryLockError;

use super::Error;

struct Slot<T> {
    value: Option<Box<T>>,
    fenced: bool,
}

pub(super) struct ResidentLane<T> {
    slot: Mutex<Slot<T>>,
}

pub(super) struct ResidentLaneLease<'a, T> {
    owner: &'a ResidentLane<T>,
    value: Option<Box<T>>,
}

impl<T> ResidentLane<T> {
    pub(super) fn new(value: T) -> Self {
        Self {
            slot: Mutex::new(Slot {
                value: Some(Box::new(value)),
                fenced: false,
            }),
        }
    }

    pub(super) fn try_take(&self) -> Result<ResidentLaneLease<'_, T>, Error> {
        let value = {
            let mut slot = match self.slot.try_lock() {
                Ok(slot) => slot,
                Err(TryLockError::WouldBlock) => return Err(Error::QueueFull),
                Err(TryLockError::Poisoned(_)) => return Err(Error::CommitUncertain),
            };
            if slot.fenced {
                return Err(Error::CommitUncertain);
            }
            slot.value.take().ok_or(Error::QueueFull)?
        };
        Ok(ResidentLaneLease {
            owner: self,
            value: Some(value),
        })
    }

    #[cfg(test)]
    pub(super) fn get_mut(&mut self) -> Result<&mut T, Error> {
        let slot = self.slot.get_mut().map_err(|_| Error::CommitUncertain)?;
        if slot.fenced {
            return Err(Error::CommitUncertain);
        }
        slot.value.as_deref_mut().ok_or(Error::CommitUncertain)
    }
}

impl<T> ResidentLaneLease<'_, T> {
    pub(super) fn state_mut(&mut self) -> Result<&mut T, Error> {
        self.value.as_deref_mut().ok_or(Error::CommitUncertain)
    }
}

impl<T> Drop for ResidentLaneLease<'_, T> {
    fn drop(&mut self) {
        // This private lock protects only Option moves and fence bits. It is
        // never held by I/O or exposed to a caller. Poison keeps admission
        // closed; a conflicting return fences the slot without replacing it.
        let value = self.value.take();
        let Ok(mut slot) = self.owner.slot.lock() else {
            return;
        };
        if slot.fenced || slot.value.is_some() || value.is_none() {
            slot.fenced = true;
            return;
        }
        slot.value = value;
    }
}

#[cfg(test)]
#[path = "cell_q24_resident_lane_tests.rs"]
mod tests;
