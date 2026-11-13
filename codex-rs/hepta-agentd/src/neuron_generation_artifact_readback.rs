//! Fixed concrete Artifact readers for generation publication. Update and
//! forward-recovery entry points still require the original writer. Only an
//! authenticated Root Initial client can construct the narrower read branch.

use super::*;

#[derive(Clone)]
pub(crate) enum GenerationArtifactOwnerV1 {
    Writer(Arc<Mutex<LearningArtifactOwnerService>>),
    #[cfg(target_os = "linux")]
    RootInitial(Arc<crate::root_generation_initial_client::OriginalInitialArtifactOwnerV1>),
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

    pub(crate) fn with_initial<R>(
        &self,
        action: impl FnOnce(InitialArtifactReadbackV1<'_>) -> Result<R, AgentdError>,
    ) -> Result<R, AgentdError> {
        match self {
            Self::Writer(original) => {
                let held = original.lock().map_err(invalid)?;
                action(InitialArtifactReadbackV1::Writer(&held))
            }
            #[cfg(target_os = "linux")]
            Self::RootInitial(original) => {
                crate::root_generation_initial_client::OriginalInitialArtifactOwnerV1::with_original(
                    original,
                    |reader| action(InitialArtifactReadbackV1::RootInitial(reader)),
                )
            }
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
