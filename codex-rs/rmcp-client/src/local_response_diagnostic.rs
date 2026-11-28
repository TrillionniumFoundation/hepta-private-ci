//! A local response failure belongs to one live request and one adapter instance.
//! Observers travel only in typed request extensions, never in JSON-RPC metadata.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::sync::Weak;

use rmcp::model::RequestId;

struct Binding {
    connection: Arc<()>,
    request_id: RequestId,
}

struct State {
    active: bool,
    binding: Option<Binding>,
    maximum_bytes: Option<usize>,
}

pub(crate) struct LocalResponseOwner(Arc<Mutex<State>>);

#[derive(Clone)]
pub(crate) struct LocalResponseObserver(Weak<Mutex<State>>);

pub(crate) struct BoundResponseObserver {
    owner: Weak<Mutex<State>>,
    connection: Arc<()>,
    request_id: RequestId,
}

impl LocalResponseOwner {
    pub(crate) fn new() -> Self {
        Self(Arc::new(Mutex::new(State {
            active: true,
            binding: None,
            maximum_bytes: None,
        })))
    }

    pub(crate) fn observer(&self) -> LocalResponseObserver {
        LocalResponseObserver(Arc::downgrade(&self.0))
    }

    // Consume the slot before returning it. Request IDs come from the actual
    // SDK handle, not from a response body or an application-supplied label.
    pub(crate) fn finish(self, request_id: &RequestId) -> Option<usize> {
        let mut state = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        let matches = state.active
            && state
                .binding
                .as_ref()
                .is_some_and(|binding| binding.request_id == *request_id);
        state.active = false;
        let maximum_bytes = state.maximum_bytes.take();
        drop(state);
        if matches { maximum_bytes } else { None }
    }
}

impl Drop for LocalResponseOwner {
    fn drop(&mut self) {
        let mut state = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        state.active = false;
        state.maximum_bytes = None;
    }
}

impl LocalResponseObserver {
    pub(crate) fn bind(
        &self,
        connection: &Arc<()>,
        request_id: &RequestId,
    ) -> Option<BoundResponseObserver> {
        let owner = self.0.upgrade()?;
        let mut state = owner.lock().unwrap_or_else(PoisonError::into_inner);
        if !state.active {
            return None;
        }
        if let Some(binding) = state.binding.as_ref() {
            if binding.request_id != *request_id || !Arc::ptr_eq(&binding.connection, connection) {
                // A reused extension must never attach a prior connection's
                // failure to a different request or recovery attempt.
                state.active = false;
                state.maximum_bytes = None;
                return None;
            }
        } else {
            state.binding = Some(Binding {
                connection: Arc::clone(connection),
                request_id: request_id.clone(),
            });
        }
        Some(BoundResponseObserver {
            owner: self.0.clone(),
            connection: Arc::clone(connection),
            request_id: request_id.clone(),
        })
    }
}

impl BoundResponseObserver {
    pub(crate) fn disqualify(self) {
        if let Some(owner) = self.owner.upgrade() {
            let mut state = owner.lock().unwrap_or_else(PoisonError::into_inner);
            state.active = false;
            state.maximum_bytes = None;
        }
    }

    // Only the adapter's typed, locally generated size error reaches this
    // method. The slot retains a numeric limit, never server bytes or text.
    pub(crate) fn record_response_too_large(&self, maximum_bytes: usize) {
        let Some(owner) = self.owner.upgrade() else {
            return;
        };
        let mut state = owner.lock().unwrap_or_else(PoisonError::into_inner);
        if state.active
            && state.binding.as_ref().is_some_and(|binding| {
                binding.request_id == self.request_id
                    && Arc::ptr_eq(&binding.connection, &self.connection)
            })
        {
            state.maximum_bytes.get_or_insert(maximum_bytes);
        }
    }
}

#[cfg(test)]
#[path = "local_response_diagnostic_tests.rs"]
mod tests;
