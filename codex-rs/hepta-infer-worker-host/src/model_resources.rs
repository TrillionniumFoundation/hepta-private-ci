//! Process-local accounting for the experimental driver. This is not a device
//! attestation, a durable reservation store, or permission to execute a model.

use std::sync::Arc;
use std::sync::Mutex;

use super::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub generation: u64,
    pub limit_bytes: u64,
    pub reserved_bytes: u64,
    pub reservations: usize,
    pub quarantined_reservations: usize,
    pub fenced: bool,
}

#[derive(Debug)]
pub(super) struct ResourceManager {
    state: Arc<Mutex<ResourceSnapshot>>,
}

impl ResourceManager {
    pub(super) fn new(generation: u64, limit_bytes: u64) -> Self {
        Self {
            state: Arc::new(Mutex::new(ResourceSnapshot {
                generation,
                limit_bytes,
                reserved_bytes: 0,
                reservations: 0,
                quarantined_reservations: 0,
                fenced: false,
            })),
        }
    }

    pub(super) fn reserve(&self, bytes: u64) -> Result<ResourceLease, Error> {
        let mut state = self.state.lock().map_err(|_| Error::ResourceAccounting)?;
        if state.fenced {
            return Err(Error::GenerationFenced);
        }
        let total = state
            .reserved_bytes
            .checked_add(bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        if total > state.limit_bytes {
            return Err(Error::ModelCapacity);
        }
        let count = state
            .reservations
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        state.reserved_bytes = total;
        state.reservations = count;
        Ok(ResourceLease {
            state: Arc::clone(&self.state),
            bytes,
            entered: false,
            released: false,
        })
    }

    pub(super) fn snapshot(&self) -> Result<ResourceSnapshot, Error> {
        self.state
            .lock()
            .map(|state| *state)
            .map_err(|_| Error::ResourceAccounting)
    }

    pub(super) fn fence(&self) -> Result<(), Error> {
        self.state
            .lock()
            .map_err(|_| Error::ResourceAccounting)?
            .fenced = true;
        Ok(())
    }
}

/// Drop returns only definitely-unused capacity. After physical entry, loss of
/// the guard quarantines the reservation and fences the generation instead.
#[derive(Debug)]
pub(super) struct ResourceLease {
    state: Arc<Mutex<ResourceSnapshot>>,
    bytes: u64,
    entered: bool,
    released: bool,
}

impl ResourceLease {
    pub(super) fn enter(&mut self) -> Result<(), Error> {
        let state = self.state.lock().map_err(|_| Error::ResourceAccounting)?;
        if state.fenced || self.entered || self.released {
            return Err(Error::GenerationFenced);
        }
        self.entered = true;
        Ok(())
    }

    pub(super) fn release_after_terminal(mut self) -> Result<(), Error> {
        self.release()
    }

    fn release(&mut self) -> Result<(), Error> {
        let mut state = self.state.lock().map_err(|_| Error::ResourceAccounting)?;
        let Some(bytes) = state.reserved_bytes.checked_sub(self.bytes) else {
            state.fenced = true;
            return Err(Error::ResourceAccounting);
        };
        let Some(count) = state.reservations.checked_sub(1) else {
            state.fenced = true;
            return Err(Error::ResourceAccounting);
        };
        state.reserved_bytes = bytes;
        state.reservations = count;
        self.released = true;
        Ok(())
    }
}

impl Drop for ResourceLease {
    fn drop(&mut self) {
        if self.released {
            return;
        }
        if !self.entered {
            let _ = self.release();
        } else if let Ok(mut state) = self.state.lock() {
            state.fenced = true;
            if let Some(count) = state.quarantined_reservations.checked_add(1) {
                state.quarantined_reservations = count;
            }
        }
    }
}

#[cfg(test)]
#[path = "model_resources_tests.rs"]
mod tests;
