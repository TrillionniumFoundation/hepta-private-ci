//! One operation under the original Root writer. Registry and journal read
//! views are actual original capabilities; wire data selects no owner or CAS.

use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::path::PathBuf;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootFinalUseObserverV1;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellGenerationJournalObserverV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::HostAuthorityService;
use super::RegisteredHostLearningCheckpointV1;
use crate::AgentdSelectedGenerationV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::types::CurrentHead;
use crate::neuron_generation_current::types::UpdateIntent;

#[path = "authority_host_generation_publication_enrollment.rs"]
mod enrollment;
pub use enrollment::RootArtifactPublicationInputsV1;
pub use enrollment::RootGenerationJournalInputsV1;
pub use enrollment::RootGenerationPublicationEnrollmentV1;
pub use enrollment::RootGenerationPublicationModeV1;
pub use enrollment::RootPublicationFinalUseConsumerV1;

#[path = "authority_host_generation_publication_transport.rs"]
mod transport;
pub(crate) use transport::Command;
pub(crate) use transport::Request;
pub(crate) use transport::Response;

pub(crate) const PURPOSE: &str = "runtime.learning.cell-generation.publication.v1";
pub(crate) const SOCKET: &str = "cell-generation-publication-v1.sock";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PublicationProfile {
    pub(crate) purpose: String,
    pub(crate) learning_operation: String,
    pub(crate) initial: String,
    pub(crate) scope: String,
    pub(crate) writer: String,
    pub(crate) identity: String,
    pub(crate) decision: String,
    pub(crate) previous_files: String,
    pub(crate) target_files: String,
    pub(crate) artifacts: ArtifactRegistrationPin,
    pub(crate) consumer_trust: String,
    pub(crate) consumer_slot: RootPublicationFinalUseConsumerV1,
    pub(crate) local_consumer: PathBuf,
    pub(crate) intent: UpdateIntent,
    pub(crate) binding: String,
}

impl PublicationProfile {
    pub(crate) fn digest(&self) -> io::Result<String> {
        let mut value = self.clone();
        value.binding.clear();
        Ok(Digest32::of_parts(&[
            b"hepta.root.generation-publication.profile.v1\0",
            &serde_json::to_vec(&value).map_err(io::Error::other)?,
        ]).to_string())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ArtifactRegistrationPin {
    root: PathBuf,
    trust: String,
    storage: String,
    retained_current: String,
    withdrawal_floor: String,
    selection: String,
    selector_trust: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PublicationRecord {
    profile: PublicationProfile,
    fenced: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PublicationBootstrap {
    pub(crate) purpose: String,
    pub(crate) learning_operation: String,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: CognitiveCheckpointPeerLifetime,
    pub(crate) identity: HostAuthorityRegisteredIdentity,
    pub(crate) initial: String,
    pub(crate) scope: String,
    pub(crate) writer: String,
    pub(crate) socket: PathBuf,
}

/// The original purpose-bound route. It transfers no Root directory or writer
/// descriptor. A live enrolled response is still required to construct CURRENT.
pub struct RootGenerationPublicationOfferV1 {
    pub(crate) bootstrap: File,
}

pub(crate) struct RegisteredGenerationPublication {
    pub(crate) profile: PublicationProfile,
    profile_store: HostAuthorityFrontierStore<PublicationRecord>,
    profile_owner: String,
    decision: LearningIterationSnapshotV1,
    current: NeuronGenerationCurrentOwnerV1,
    previous: CellGenerationJournalObserverV1,
    target: CellGenerationJournalObserverV1,
    artifacts: LearningArtifactReadViewV1,
    selected: Mutex<AgentdSelectedGenerationV1>,
    consumer: RootFinalUseObserverV1,
}

impl RegisteredGenerationPublication {
    fn require_profile(&self) -> io::Result<()> {
        if self.profile_store.load(&self.profile_owner).map_err(io::Error::other)? != (PublicationRecord { profile: self.profile.clone(), fenced: false })
            || self.profile.digest()? != self.profile.binding
            || self.previous.files_binding().to_string() != self.profile.previous_files
            || self.target.files_binding().to_string() != self.profile.target_files
        {
            return Err(io::Error::other("original publication enrollment changed"));
        }
        Ok(())
    }

    fn require_history(&self, learning: &RegisteredHostLearningCheckpointV1, scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2) -> io::Result<()> {
        let actual = learning.backend.restore(&self.decision.request).map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("original Root learning checkpoint missing"))?;
        scope.validate_snapshot(&actual).map_err(io::Error::other)?;
        if actual.request != self.decision.request || actual.owners != self.decision.owners
            || !actual.receipts.starts_with(&self.decision.receipts)
        {
            return Err(io::Error::other("original Root decision checkpoint differs"));
        }
        Ok(())
    }

    fn require_selection(&self, now: u64) -> io::Result<()> {
        let result = (|| {
            let mut selected: std::sync::MutexGuard<'_, AgentdSelectedGenerationV1> = self.selected
                .try_lock().map_err(|_| io::Error::other("original selection busy"))?;
            selected.revalidate_original_artifacts(&self.artifacts, now).map_err(io::Error::other)?;
            if selected.observation().digest().into_array() != self.profile.intent.selection {
                return Err(io::Error::other("original selection cut changed"));
            }
            Ok(())
        })();
        if result.is_err() {
            // This operation is frozen to one selection. A later original
            // frontier/refusal cannot be forgotten by reopening the Root slot.
            fence_record(&self.profile_store, &self.profile_owner)?;
        }
        result
    }

    fn require_previous(&self) -> io::Result<()> {
        let observed = self.previous.observe().map_err(io::Error::other)?;
        let intent = &self.profile.intent;
        if !observed.is_drained() || observed.owner_binding() != &intent.previous
            || observed.observation().owner_checkpoint().into_array() != intent.previous_checkpoint
            || observed.observation().digest().map_err(io::Error::other)? != intent.previous_observation
        {
            return Err(io::Error::other("original drained predecessor changed"));
        }
        Ok(())
    }

    fn require_genesis(&self) -> io::Result<()> {
        let observed = self.target.observe().map_err(io::Error::other)?;
        if !observed.is_genesis() || observed.owner_binding() != &self.profile.intent.target
            || observed.observation().owner_checkpoint().into_array() != self.profile.intent.genesis_checkpoint
        {
            return Err(io::Error::other("actual original target genesis required"));
        }
        Ok(())
    }

    fn verify_retained(
        &self,
        signed: &SignedFinalUseGrant,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> io::Result<codex_hepta_contracts::FinalUseRevocations> {
        self.consumer.verify_original_retained_use(
            signed, &self.profile.intent.binding().map_err(io::Error::other)?, witness,
        ).map_err(io::Error::other)
    }
}

pub(crate) fn head_digest(head: &CurrentHead) -> io::Result<String> {
    Ok(Digest32::of_parts(&[
        b"hepta.root.generation-publication.current.v1\0",
        &serde_json::to_vec(head).map_err(io::Error::other)?,
    ]).to_string())
}

pub(crate) fn original_root() -> io::Result<()> {
    // SAFETY: these calls only observe the actual process credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::other("original Root process required"));
    }
    Ok(())
}

fn fence_record(
    store: &HostAuthorityFrontierStore<PublicationRecord>,
    owner: &str,
) -> io::Result<()> {
    let before = store.load(owner).map_err(io::Error::other)?;
    if !before.fenced {
        let mut next = before.clone();
        next.fenced = true;
        store.compare_and_set(owner, &before, &next).map_err(io::Error::other)?;
    }
    if !store.load(owner).map_err(io::Error::other)?.fenced {
        return Err(io::Error::other("original publication fencing is uncertain"));
    }
    Ok(())
}
