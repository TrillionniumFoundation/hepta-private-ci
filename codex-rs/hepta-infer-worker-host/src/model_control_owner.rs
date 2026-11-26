//! Async model work and synchronous CPU work borrow the original single journal.
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_infer_core::SelfIterationModelErrorV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

pub(super) struct ModelControlOwner(pub(super) Arc<tokio::sync::Mutex<DurableInferenceControl>>);

impl ModelControlOwner {
    pub(super) async fn acquire(
        &self,
        budget: Duration,
    ) -> Result<tokio::sync::OwnedMutexGuard<DurableInferenceControl>, SelfIterationModelErrorV1>
    {
        tokio::time::timeout(budget, self.0.clone().lock_owned())
            .await
            .map_err(|_| SelfIterationModelErrorV1::TimedOut)
    }

    pub(super) fn try_acquire(
        &self,
    ) -> Result<tokio::sync::OwnedMutexGuard<DurableInferenceControl>, SelfIterationModelErrorV1>
    {
        self.0
            .clone()
            .try_lock_owned()
            .map_err(|_| SelfIterationModelErrorV1::Provider("original control owner busy".into()))
    }

    pub(super) fn record(
        &self,
        request: &str,
    ) -> Result<Option<NativeRunRecord>, SelfIterationModelErrorV1> {
        self.try_acquire()?
            .native_record_resolved(request)
            .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))
    }
}

#[cfg(test)]
#[path = "model_control_owner_tests.rs"]
mod tests;
