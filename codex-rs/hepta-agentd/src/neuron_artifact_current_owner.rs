//! The installed consumer borrows a current view; it never needs a Root writer
//! lease when artifacts are published by an independently protected owner.
use super::*;
use codex_hepta_agent_components::learning_artifacts::ArtifactOwnerHostError;
#[cfg(target_os = "linux")]
use codex_hepta_agent_components::learning_artifacts::ReadOnlyArtifactCurrentOwnerV1;
use std::sync::MutexGuard;

#[derive(Clone)]
pub(super) enum CurrentOwner {
    Writer(Arc<Mutex<LearningArtifactOwnerHost>>),
    #[cfg(target_os = "linux")]
    ReadOnly(Arc<Mutex<ReadOnlyArtifactCurrentOwnerV1>>),
}
pub(super) enum CurrentReadGuard<'a> {
    Writer(MutexGuard<'a, LearningArtifactOwnerHost>),
    #[cfg(target_os = "linux")]
    ReadOnly(MutexGuard<'a, ReadOnlyArtifactCurrentOwnerV1>),
}
impl CurrentOwner {
    pub(super) fn lock(&self) -> Result<CurrentReadGuard<'_>, NeuronAdmissionError> {
        match self {
            Self::Writer(owner) => owner
                .try_lock()
                .map(CurrentReadGuard::Writer)
                .map_err(|_| NeuronAdmissionError::Unavailable),
            #[cfg(target_os = "linux")]
            Self::ReadOnly(owner) => owner
                .try_lock()
                .map(CurrentReadGuard::ReadOnly)
                .map_err(|_| NeuronAdmissionError::Unavailable),
        }
    }
}
impl CurrentReadGuard<'_> {
    pub(super) fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        match self {
            Self::Writer(owner) => owner.current_registry_view(now),
            #[cfg(target_os = "linux")]
            Self::ReadOnly(owner) => owner.current_registry_view(now),
        }
    }
}
