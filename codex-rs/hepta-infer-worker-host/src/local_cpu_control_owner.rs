//! CPU stages borrow the original model journal; a busy model owner stops
//! admission without creating another writer or waiting across async work.
use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;

pub(super) enum CpuControlOwner {
    Legacy(Arc<Mutex<DurableInferenceControl>>),
    #[cfg(target_os = "linux")]
    Shared(Arc<tokio::sync::Mutex<DurableInferenceControl>>),
}
pub(super) enum CpuControlLease<'a> {
    Legacy(std::sync::MutexGuard<'a, DurableInferenceControl>),
    #[cfg(target_os = "linux")]
    Shared(tokio::sync::OwnedMutexGuard<DurableInferenceControl>),
}
impl CpuControlOwner {
    pub(super) fn try_lock(&self) -> Result<CpuControlLease<'_>, Error> {
        match self {
            Self::Legacy(owner) => owner
                .try_lock()
                .map(CpuControlLease::Legacy)
                .map_err(|_| Error::WriterUnavailable),
            #[cfg(target_os = "linux")]
            Self::Shared(owner) => owner
                .clone()
                .try_lock_owned()
                .map(CpuControlLease::Shared)
                .map_err(|_| Error::WriterUnavailable),
        }
    }

    pub(super) fn busy_error(&self) -> codex_hepta_neuron::NeuronModelError {
        match self {
            Self::Legacy(_) => codex_hepta_neuron::NeuronModelError::Indeterminate,
            #[cfg(target_os = "linux")]
            Self::Shared(_) => codex_hepta_neuron::NeuronModelError::Unavailable,
        }
    }
}
impl Deref for CpuControlLease<'_> {
    type Target = DurableInferenceControl;
    fn deref(&self) -> &Self::Target {
        match self {
            Self::Legacy(owner) => owner,
            #[cfg(target_os = "linux")]
            Self::Shared(owner) => owner,
        }
    }
}
impl DerefMut for CpuControlLease<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        match self {
            Self::Legacy(owner) => owner,
            #[cfg(target_os = "linux")]
            Self::Shared(owner) => owner,
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "local_cpu_control_owner_tests.rs"]
mod tests;
