//! Original Artifact read access bound to the actual authenticated Initial
//! client object. Public trust/selection bytes are checked against Root's full
//! retained pin before opening the same physical CURRENT and withdrawals.

use super::*;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdRootProductionInputs;
use crate::AgentdSelectedGenerationV1;
use crate::RootArtifactPublicationInputsV1;
use crate::RootPublicationFinalUseConsumerV1;
use crate::neuron_generation_update_live::artifacts::GenerationArtifactOwnerV1;
use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;
use std::sync::Arc;
use std::sync::Weak;

pub(crate) struct OriginalInitialArtifactReadbackV1 {
    original: Weak<RootGenerationInitialClient>,
    profile: InitialProfile,
    mode: crate::RootGenerationInitialModeV1,
    reader: LearningArtifactReadViewV1,
}

impl RootGenerationInitialClient {
    /// Called only by the original production launch while it still owns its
    /// actual five-lane inputs. There is no caller-supplied FinalUse or clock.
    pub(crate) fn open_original_artifact_authorities(
        self: &Arc<Self>,
        root: &AgentdRootProductionInputs,
        inputs: RootArtifactPublicationInputsV1,
    ) -> Result<
        (
            AgentdGenerationUpdateAuthoritiesV1,
            AgentdSelectedGenerationV1,
        ),
        AgentdError,
    > {
        if self.fenced.load(Ordering::Acquire) {
            return Err(uncertain());
        }
        self.connection
            .require_same_original_session(&root.session)?;
        let (original, _) = self.connection.original_launch_binding();
        let (authority, consumer) = match self.profile.consumer_slot {
            RootPublicationFinalUseConsumerV1::Device => (&root.device, &original.consumers.device),
            RootPublicationFinalUseConsumerV1::Notes => (&root.notes, &original.consumers.notes),
        };
        if self.profile.local_consumer != consumer.local_state_dir {
            return Err(uncertain());
        }
        authority
            .current_external_frontier()
            .map_err(|_| uncertain())?;
        let clock = root.session.clock();
        let (reader, mut selected) = self.profile.open_matching_artifact_readback(
            inputs,
            original.consumer.uid,
            clock.now_unix_ms().map_err(|_| uncertain())?,
        )?;
        let readback = OriginalInitialArtifactReadbackV1 {
            original: Arc::downgrade(self),
            profile: self.profile.clone(),
            mode: self.mode,
            reader,
        };
        readback.revalidate(
            self,
            &mut selected,
            clock.now_unix_ms().map_err(|_| uncertain())?,
        )?;
        self.connection
            .require_same_original_session(&root.session)?;
        Ok((
            AgentdGenerationUpdateAuthoritiesV1 {
                artifacts: GenerationArtifactOwnerV1::RootInitial(Arc::new(Mutex::new(readback))),
                final_use: Arc::new(authority.clone()),
                clock,
            },
            selected,
        ))
    }
}

impl OriginalInitialArtifactReadbackV1 {
    pub(crate) fn revalidate(
        &self,
        client: &Arc<RootGenerationInitialClient>,
        selected: &mut AgentdSelectedGenerationV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        self.require_original_client(client)?;
        selected.revalidate_original_artifacts(&self.reader, now)?;
        self.require_original_client(client)
    }

    fn require_original_client(
        &self,
        client: &Arc<RootGenerationInitialClient>,
    ) -> Result<(), AgentdError> {
        let original = self.original.upgrade().ok_or_else(uncertain)?;
        if !Arc::ptr_eq(&original, client)
            || client.fenced.load(Ordering::Acquire)
            || client.profile != self.profile
            || client.mode != self.mode
        {
            return Err(uncertain());
        }
        client.connection.require_original_publication_session()
    }
}
