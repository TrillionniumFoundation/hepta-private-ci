//! Own the current-control session across awaits without holding a mutex guard.
//! Returning a lease preserves consumed enrollment even on error or cancellation.

use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::TryLockError;

use tokio_util::sync::CancellationToken;

use crate::AgentdNativeMemoryCurrentContextV1;
use crate::AgentdNativeMemoryPreparedReadV1;
use crate::AgentdNativeMemoryShadowOwner;
use crate::NativeMemoryShadowReadV1;

#[derive(Default)]
pub(super) struct Session {
    pub(super) prepared: Option<(String, AgentdNativeMemoryPreparedReadV1)>,
    pub(super) attempted: bool,
    pub(super) result: Option<(
        Arc<AgentdNativeMemoryShadowOwner<AgentdNativeMemoryCurrentContextV1>>,
        NativeMemoryShadowReadV1,
    )>,
}

pub(super) struct SessionSlot {
    slot: Mutex<Option<Session>>,
    cancellation: CancellationToken,
}

impl SessionSlot {
    pub(super) fn new(cancellation: CancellationToken) -> Self {
        Self {
            slot: Mutex::new(Some(Session::default())),
            cancellation,
        }
    }

    pub(super) fn claim(&self) -> Result<SessionLease<'_>, String> {
        if self.cancellation.is_cancelled() {
            return Err("current process runtime is closed".into());
        }
        let mut slot = match self.slot.try_lock() {
            Ok(slot) => slot,
            Err(TryLockError::WouldBlock) => return Err("current session is busy".into()),
            Err(TryLockError::Poisoned(_)) => {
                self.cancellation.cancel();
                return Err("current session is poisoned".into());
            }
        };
        if self.cancellation.is_cancelled() {
            return Err("current process runtime is closed".into());
        }
        let session = slot.take().ok_or("current session is busy")?;
        Ok(SessionLease {
            owner: self,
            session: Some(session),
        })
    }
}

pub(super) struct SessionLease<'a> {
    owner: &'a SessionSlot,
    session: Option<Session>,
}

impl Deref for SessionLease<'_> {
    type Target = Session;

    fn deref(&self) -> &Self::Target {
        self.session
            .as_ref()
            .expect("a live lease owns its session")
    }
}

impl DerefMut for SessionLease<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.session
            .as_mut()
            .expect("a live lease owns its session")
    }
}

impl Drop for SessionLease<'_> {
    fn drop(&mut self) {
        // Acquisition only moves an Option under this short synchronous lock.
        // Do not use try_lock here: a contending claim must not lose spent state.
        let mut slot = match self.owner.slot.lock() {
            Ok(slot) => slot,
            Err(poisoned) => {
                self.owner.cancellation.cancel();
                // Preserve the state for inspection, but never clear the poison.
                poisoned.into_inner()
            }
        };
        if slot.is_some() {
            self.owner.cancellation.cancel();
            return;
        }
        let Some(session) = self.session.take() else {
            self.owner.cancellation.cancel();
            return;
        };
        *slot = Some(session);
    }
}

#[cfg(test)]
#[path = "native_memory_host_session_tests.rs"]
mod tests;
