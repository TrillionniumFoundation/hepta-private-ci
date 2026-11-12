//! Separate original Root initial-publication purpose. The root host supplies
//! real artifact, target-file and consumer observers; peer bytes can only
//! request the exact reserved preparation or its original publication.

use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::RootFinalUseObserverV1;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellGenerationJournalObserverV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::HostAuthorityService;
pub(crate) use super::generation_publication::original_root;
use crate::AgentdSelectedGenerationV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::types::CurrentHead;

#[path = "authority_host_generation_initial_inputs.rs"]
mod inputs;
pub use inputs::RootGenerationInitialEnrollmentV1;
pub use inputs::RootGenerationInitialModeV1;
#[path = "authority_host_data_refusal.rs"]
mod data_refusal;
#[path = "authority_host_generation_initial_enrollment.rs"]
mod enrollment;
#[path = "authority_host_historical_source_pin.rs"]
pub(crate) mod historical_source_pin;
pub use historical_source_pin::RootHistoricalSourceInputsV1;
#[path = "authority_host_historical_source_handoff.rs"]
mod historical_source_handoff;
#[path = "authority_host_run_start_retention.rs"]
pub(crate) mod run_start_retention;
#[path = "authority_host_generation_initial_transport.rs"]
mod transport;
pub(crate) use transport::Command;
pub(crate) use transport::Request;
pub(crate) use transport::Response;
#[cfg(test)]
pub(crate) use transport::drop_next_test_publication_ack;

pub(crate) const PURPOSE: &str = "runtime.cell-generation.initial-publication.v1";
pub(crate) const SOCKET: &str = "cell-generation-initial-v1.sock";

/// Immutable deployment description. Registration still requires actual Root
/// custody and original capabilities; this description grants no authority.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostGenerationInitialDeploymentV1 {
    pub(crate) operation: String,
    pub(crate) target: CellGenerationOwnerBindingV1,
    pub(crate) target_context: String,
}

impl HostGenerationInitialDeploymentV1 {
    pub fn new(
        operation: String,
        target: &codex_hepta_neuron::CellGenerationObserverConfigV1,
    ) -> io::Result<Self> {
        StableId::new(&operation).map_err(io::Error::other)?;
        if target.generation.initial.revision != 0
            || !target.generation.initial.prefix.is_empty()
            || target.generation.initial.stopped
        {
            return Err(io::Error::other(
                "original selected initial genesis required",
            ));
        }
        Ok(Self {
            operation,
            target_context: target_context(target)?,
            target: CellGenerationOwnerBindingV1::new(&target.generation, target.journal_records)
                .map_err(io::Error::other)?,
        })
    }
}

pub(crate) fn target_context(
    config: &codex_hepta_neuron::CellGenerationObserverConfigV1,
) -> io::Result<String> {
    let binding = CellGenerationOwnerBindingV1::new(&config.generation, config.journal_records)
        .map_err(io::Error::other)?;
    let records = u64::try_from(config.witness_records).map_err(io::Error::other)?;
    Ok(Digest32::of_parts(&[
        b"hepta.root.generation-initial.target-context.v1\0",
        &binding.digest().map_err(io::Error::other)?,
        config.witness_scope.scope_digest.as_array(),
        config.witness_scope.objective_digest.as_array(),
        &config.witness_generation.get().to_be_bytes(),
        &records.to_be_bytes(),
    ])
    .to_string())
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InitialProfile {
    pub(crate) purpose: String,
    pub(crate) deployment: HostGenerationInitialDeploymentV1,
    pub(crate) writer: String,
    pub(crate) identity: String,
    pub(crate) target_files: String,
    pub(crate) artifacts: inputs::ArtifactPin,
    pub(crate) consumer_trust: String,
    pub(crate) consumer_slot: crate::RootPublicationFinalUseConsumerV1,
    pub(crate) local_consumer: PathBuf,
    pub(crate) prepared: CurrentHead,
    pub(crate) intent: String,
    pub(crate) selection: String,
    pub(crate) final_use: FinalUseBinding,
    pub(crate) binding: String,
}

impl InitialProfile {
    pub(crate) fn digest(&self) -> io::Result<String> {
        let mut value = self.clone();
        value.binding.clear();
        Ok(Digest32::of_parts(&[
            b"hepta.root.generation-initial.profile.v1\0",
            &serde_json::to_vec(&value).map_err(io::Error::other)?,
        ])
        .to_string())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct InitialRecord {
    profile: InitialProfile,
    fenced: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InitialBootstrap {
    pub(crate) purpose: String,
    pub(crate) deployment: HostGenerationInitialDeploymentV1,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: CognitiveCheckpointPeerLifetime,
    pub(crate) identity: HostAuthorityRegisteredIdentity,
    pub(crate) writer: String,
    pub(crate) socket: PathBuf,
}

/// Original sealed purpose route; no Root directory or signer is transferred.
pub struct RootGenerationInitialOfferV1 {
    pub(crate) bootstrap: File,
}

pub(crate) struct RegisteredGenerationInitial {
    pub(crate) profile: InitialProfile,
    mode: RootGenerationInitialModeV1,
    profile_store: Arc<HostAuthorityFrontierStore<InitialRecord>>,
    profile_owner: String,
    root: Arc<RootAuthorityDirectory>,
    current: Mutex<Option<NeuronGenerationCurrentOwnerV1>>,
    target: CellGenerationJournalObserverV1,
    artifacts: LearningArtifactReadViewV1,
    selected: Mutex<AgentdSelectedGenerationV1>,
    consumer: RootFinalUseObserverV1,
}

impl RegisteredGenerationInitial {
    fn require_profile(&self) -> io::Result<()> {
        if self
            .profile_store
            .load(&self.profile_owner)
            .map_err(io::Error::other)?
            != (InitialRecord {
                profile: self.profile.clone(),
                fenced: false,
            })
            || self.profile.digest()? != self.profile.binding
            || self.target.files_binding().to_string() != self.profile.target_files
        {
            return Err(io::Error::other("original initial enrollment changed"));
        }
        Ok(())
    }

    fn require_selection(&self, now: u64) -> io::Result<()> {
        let result = (|| {
            let mut selected: std::sync::MutexGuard<'_, AgentdSelectedGenerationV1> = self
                .selected
                .try_lock()
                .map_err(|_| io::Error::other("original selection busy"))?;
            selected
                .revalidate_original_artifacts(&self.artifacts, now)
                .map_err(io::Error::other)?;
            if selected.observation().digest().to_string() != self.profile.selection {
                return Err(io::Error::other("original initial selection changed"));
            }
            Ok(())
        })();
        if result.is_err() {
            self.fence()?;
        }
        result
    }

    fn require_genesis(&self) -> io::Result<()> {
        let result = (|| {
            let observed = self.target.observe().map_err(io::Error::other)?;
            if !observed.is_genesis()
                || observed.owner_binding() != &self.profile.deployment.target
                || observed.observation().owner_checkpoint()
                    != self.profile.deployment.target.genesis_checkpoint()
            {
                return Err(io::Error::other(
                    "original physical initial genesis required",
                ));
            }
            Ok(())
        })();
        if result.is_err() {
            self.fence()?;
        }
        result
    }

    fn require_target(&self, fresh: bool) -> io::Result<()> {
        let result = if fresh {
            self.target.require_original_unwritten()
        } else {
            self.target.require_original_unwritten_or_genesis()
        }
        .map_err(io::Error::other);
        if result.is_err() {
            self.fence()?;
        }
        result
    }

    fn observe_published_target(&self) -> io::Result<()> {
        let result = self.target.observe().map(|_| ()).map_err(io::Error::other);
        if result.is_err() {
            self.fence()?;
        }
        result
    }

    fn verify_recorded_use(
        &self,
        signed: &SignedFinalUseGrant,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> io::Result<codex_hepta_contracts::FinalUseRevocations> {
        let result = self.verify_retained(signed, witness);
        if result.is_err() {
            self.fence()?;
        }
        result
    }

    fn verify_retained(
        &self,
        signed: &SignedFinalUseGrant,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> io::Result<codex_hepta_contracts::FinalUseRevocations> {
        self.consumer
            .verify_original_retained_use(signed, &self.profile.final_use, witness)
            .map_err(io::Error::other)
    }

    fn fence(&self) -> io::Result<()> {
        fence_initial_record(&self.profile_store, &self.profile_owner)
    }
}

pub(crate) fn head_digest(head: &Option<CurrentHead>) -> io::Result<String> {
    Ok(Digest32::of_parts(&[
        b"hepta.root.generation-initial.current.v1\0",
        &serde_json::to_vec(head).map_err(io::Error::other)?,
    ])
    .to_string())
}

fn fence_initial_record(
    store: &HostAuthorityFrontierStore<InitialRecord>,
    owner: &str,
) -> io::Result<()> {
    let before = store.load(owner).map_err(io::Error::other)?;
    if !before.fenced {
        let mut next = before.clone();
        next.fenced = true;
        store
            .compare_and_set(owner, &before, &next)
            .map_err(io::Error::other)?;
    }
    if !store.load(owner).map_err(io::Error::other)?.fenced {
        return Err(io::Error::other("initial enrollment fencing uncertain"));
    }
    Ok(())
}
