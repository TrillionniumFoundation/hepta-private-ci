//! One original owner fence: concurrent verification, exclusive administration.
use super::AuthorityLeaseError;
use super::State;
use std::ops::Deref;
use std::sync::RwLock;
use std::sync::RwLockReadGuard;
use std::sync::RwLockWriteGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(super) struct LeaseState {
    state: RwLock<State>,
    read_panicked: AtomicBool,
}

impl LeaseState {
    pub(super) fn new(state: State) -> Self {
        Self {
            state: RwLock::new(state),
            read_panicked: AtomicBool::new(false),
        }
    }

    pub(super) fn read(&self) -> Result<LeaseReadGuard<'_>, AuthorityLeaseError> {
        let state = self
            .state
            .read()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        if state.failed || self.read_panicked.load(Ordering::Acquire) {
            return Err(AuthorityLeaseError::Unavailable);
        }
        Ok(LeaseReadGuard {
            state,
            read_panicked: &self.read_panicked,
        })
    }

    pub(super) fn write(&self) -> Result<RwLockWriteGuard<'_, State>, AuthorityLeaseError> {
        let state = self
            .state
            .write()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        if state.failed || self.read_panicked.load(Ordering::Acquire) {
            return Err(AuthorityLeaseError::Unavailable);
        }
        Ok(state)
    }
}

/// RwLock only poisons on a writer panic. Preserve the original Mutex's
/// fail-closed behavior for a panic during any verifier or dispatch callback.
pub(super) struct LeaseReadGuard<'a> {
    state: RwLockReadGuard<'a, State>,
    read_panicked: &'a AtomicBool,
}

impl Deref for LeaseReadGuard<'_> {
    type Target = State;
    fn deref(&self) -> &State {
        &self.state
    }
}

impl Drop for LeaseReadGuard<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.read_panicked.store(true, Ordering::Release);
        }
    }
}
