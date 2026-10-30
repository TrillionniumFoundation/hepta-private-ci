use std::future::Future;
use std::pin::Pin;
use std::sync::Mutex;

type CompletionBarrier = Pin<Box<dyn Future<Output = ()> + Send + 'static>>;

#[derive(Default)]
struct WakeState {
    running: bool,
    pending: Option<CompletionBarrier>,
}

/// Coalesces completion observations for a single deferred worker.
///
/// Each capture must observe every owner still pending at the time it runs.
/// Capture and replacement are serialized, so a delayed older capture cannot
/// overwrite a newer one. The worker must drain with `next_barrier` until it
/// returns `None`, including after its ordinary admission attempt. This type
/// observes completion only; it neither proves idleness nor grants admission.
#[derive(Default)]
pub struct CoalescingWake {
    state: Mutex<WakeState>,
}

impl CoalescingWake {
    /// Registers an observation and returns whether the caller must start the
    /// worker. `capture` runs synchronously under a short lock and must not
    /// reenter this coalescer or wait for asynchronous work.
    pub fn register_with<F, B>(&self, capture: F) -> bool
    where
        F: FnOnce() -> B,
        B: Future<Output = ()> + Send + 'static,
    {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.pending = Some(Box::pin(capture()));
        if state.running {
            return false;
        }
        state.running = true;
        true
    }

    /// Takes the newest observation, or atomically retires the worker when no
    /// observation remains. Never hold this lock while awaiting the barrier or
    /// performing admission: a successor callback must remain able to register.
    pub fn next_barrier(&self) -> Option<CompletionBarrier> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(barrier) = state.pending.take() {
            return Some(barrier);
        }
        state.running = false;
        None
    }
}

#[cfg(test)]
#[path = "coalescing_wake_tests.rs"]
mod tests;
