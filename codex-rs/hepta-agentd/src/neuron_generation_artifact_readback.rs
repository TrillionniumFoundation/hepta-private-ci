//! Fixed concrete Artifact readers for generation publication. Update and
//! forward-recovery entry points still require the original writer. Only an
//! authenticated Root Initial client can construct the narrower read branch.

use super::*;
use std::sync::MutexGuard;

#[derive(Clone)]
pub(crate) enum GenerationArtifactOwnerV1 {
    Writer(Arc<Mutex<LearningArtifactOwnerService>>),
    #[cfg(target_os = "linux")]
    RootInitial(
        Arc<Mutex<crate::root_generation_initial_client::OriginalInitialArtifactReadbackV1>>,
    ),
}

pub(crate) enum InitialArtifactGuardV1<'a> {
    Writer(MutexGuard<'a, LearningArtifactOwnerService>),
    #[cfg(target_os = "linux")]
    RootInitial(
        MutexGuard<'a, crate::root_generation_initial_client::OriginalInitialArtifactReadbackV1>,
    ),
}

pub(crate) enum InitialArtifactReadbackV1<'a> {
    Writer(&'a LearningArtifactOwnerService),
    #[cfg(target_os = "linux")]
    RootInitial(&'a crate::root_generation_initial_client::OriginalInitialArtifactReadbackV1),
}

pub(crate) struct InitialArtifactPublicationV1<'a> {
    pub(crate) artifacts: InitialArtifactReadbackV1<'a>,
    pub(crate) authority: &'a FinalUseAuthority,
    pub(crate) signed: &'a SignedFinalUseGrant,
    pub(crate) clock: &'a dyn AuthorityClock,
}

impl GenerationArtifactOwnerV1 {
    pub(crate) fn writer(&self) -> Result<&Arc<Mutex<LearningArtifactOwnerService>>, AgentdError> {
        match self {
            Self::Writer(original) => Ok(original),
            #[cfg(target_os = "linux")]
            Self::RootInitial(_) => Err(invalid(
                "Root Initial Artifact reader cannot authorize an update or local CURRENT",
            )),
        }
    }

    pub(crate) fn lock_initial(&self) -> Result<InitialArtifactGuardV1<'_>, AgentdError> {
        match self {
            Self::Writer(original) => Ok(InitialArtifactGuardV1::Writer(
                original.lock().map_err(invalid)?,
            )),
            #[cfg(target_os = "linux")]
            Self::RootInitial(original) => Ok(InitialArtifactGuardV1::RootInitial(
                original.try_lock().map_err(invalid)?,
            )),
        }
    }
}

impl InitialArtifactGuardV1<'_> {
    pub(crate) fn readback(&self) -> InitialArtifactReadbackV1<'_> {
        match self {
            Self::Writer(original) => InitialArtifactReadbackV1::Writer(original),
            #[cfg(target_os = "linux")]
            Self::RootInitial(original) => InitialArtifactReadbackV1::RootInitial(original),
        }
    }
}

impl InitialArtifactReadbackV1<'_> {
    pub(crate) fn revalidate_owner(
        &self,
        current: &NeuronGenerationCurrentOwnerV1,
        selected: &mut AgentdSelectedGenerationV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        #[cfg(not(target_os = "linux"))]
        let _ = current;
        match self {
            Self::Writer(original) => selected.revalidate(original, now),
            #[cfg(target_os = "linux")]
            Self::RootInitial(original) => {
                current.revalidate_original_initial_artifacts(original, selected, now)
            }
        }
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn revalidate_initial_client(
        &self,
        client: &Arc<crate::root_generation_initial_client::RootGenerationInitialClient>,
        selected: &mut AgentdSelectedGenerationV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        match self {
            Self::Writer(original) => selected.revalidate(original, now),
            Self::RootInitial(original) => {
                let original: &crate::root_generation_initial_client::OriginalInitialArtifactReadbackV1 = original;
                original.revalidate(client, selected, now)
            }
        }
    }
}
