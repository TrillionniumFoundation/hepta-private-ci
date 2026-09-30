//! Exclusive journal ownership without a mutex guard spanning an async turn.
//! Cancellation returns the same durable owner before admitting another caller.

use std::sync::Mutex;

use codex_hepta_agentd::AgentdError;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use tokio::sync::Semaphore;
use tokio::sync::SemaphorePermit;

pub(super) struct NativeIntelligenceControlOwnerV1 {
    control: Mutex<Option<DurableInferenceControl>>,
    admission: Semaphore,
}

impl NativeIntelligenceControlOwnerV1 {
    pub(super) fn new(control: DurableInferenceControl) -> Self {
        Self {
            control: Mutex::new(Some(control)),
            admission: Semaphore::new(1),
        }
    }

    pub(super) fn checkout(&self) -> Result<NativeIntelligenceControlCheckoutV1<'_>, AgentdError> {
        let permit = self.admission.try_acquire().map_err(|_| {
            AgentdError::Protocol("native execution journal busy; retry the same run".to_string())
        })?;
        let control = self
            .control
            .lock()
            .map_err(|_| AgentdError::Protocol("native execution journal poisoned".to_string()))?
            .take()
            .ok_or_else(|| {
                AgentdError::Protocol("native execution journal unavailable".to_string())
            })?;
        Ok(NativeIntelligenceControlCheckoutV1 {
            owner: self,
            control: Some(control),
            _permit: permit,
        })
    }
}

pub(super) struct NativeIntelligenceControlCheckoutV1<'a> {
    owner: &'a NativeIntelligenceControlOwnerV1,
    pub(super) control: Option<DurableInferenceControl>,
    _permit: SemaphorePermit<'a>,
}

impl Drop for NativeIntelligenceControlCheckoutV1<'_> {
    fn drop(&mut self) {
        // A poisoned slot still retains its journal, but subsequent checkout
        // rejects the poison. Restore before releasing the admission permit.
        let mut slot = self
            .owner
            .control
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *slot = self.control.take();
    }
}

#[cfg(test)]
#[path = "native_intelligence_control_tests.rs"]
mod tests;
