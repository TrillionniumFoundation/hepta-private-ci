//! Load concrete generation owners from existing protected Root state. Only
//! original constructors verify the records; decoding is not authorization.

use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::read_dataset_withdrawal_snapshot;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::HostAuthorityService;
use super::RootHostInitialGenerationInputsV1;
use super::RootHostInitialGenerationRecoveryV1;
use super::invalid;
use crate::AgentdError;
use crate::authority_host_config::read_root_json;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_selection::AgentdGenerationSelectionFilesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "authority_host_generation_input_types.rs"]
mod types;
#[path = "authority_host_generation_input_files.rs"]
mod files;
use types::ConsumerTrustModel;
use types::GenerationDeploymentFile;
use types::OperationFile;

/// Actual supervisor-owned files, adopted before opening any further files.
/// They carry no selection, publication or permission until original loading.
pub struct RootHostInitialGenerationFilesV1 {
    pub registry_snapshot: File,
    pub selected_payload: File,
    pub withdrawal_snapshot: File,
    pub target_journal: File,
    pub target_witness: File,
}

#[derive(Clone, Copy)]
pub(crate) enum LoadPurpose {
    Fresh,
    Recover,
}

pub(crate) enum LoadedOriginalGeneration {
    Fresh(RootHostInitialGenerationInputsV1<FileAnchorWitnessStore>),
    Recover(RootHostInitialGenerationRecoveryV1<FileAnchorWitnessStore>),
}

impl HostAuthorityService {
    pub(crate) fn load_original_initial_generation_inputs(
        &self,
        original_state: &Path,
        deployment: &Path,
        original_files: RootHostInitialGenerationFilesV1,
        purpose: LoadPurpose,
        end: Instant,
    ) -> Result<LoadedOriginalGeneration, AgentdError> {
        require_before(end)?;
        let value: GenerationDeploymentFile = read_root_json(deployment)?;
        if value.schema_version != 1
            || value.purpose != "hepta.root.initial-generation.existing-inputs.v1"
            || !matches!((purpose, &value.operation),
                (LoadPurpose::Fresh, OperationFile::Fresh { .. })
                | (LoadPurpose::Recover, OperationFile::Recover { .. }))
        {
            return Err(invalid("original generation deployment purpose differs"));
        }
        files::require_descriptors(&original_files, purpose)?;
        files::require_artifact_directory(original_state, &value.artifacts.state_directory)?;
        files::require_existing_consumer(original_state, &value.consumer.state_directory)?;
        if value.artifacts.state_directory == value.consumer.state_directory {
            return Err(invalid("Artifact and FinalUse retain separate original stores"));
        }
        let root = Arc::clone(self.resident_store_root.as_ref()
            .ok_or_else(|| invalid("the same original Root directory must be retained"))?);
        if self.root_registry.is_none() {
            return Err(invalid("the same original lease Registry must be retained"));
        }
        let RootHostInitialGenerationFilesV1 {
            registry_snapshot, selected_payload, withdrawal_snapshot, target_journal, target_witness,
        } = original_files;
        let trust = value.artifacts.trust.original()?;
        let verifier = ArtifactSelectionVerifierV1::new(value.selection.trust.original()?, &trust)
            .map_err(invalid)?;
        let signed_selection = value.selection.signed.original()?;
        let writer_lease = value.artifacts.writer_lease.original()?;
        let required_current_head = value.artifacts.required_current_head.original()?;
        let withdrawal_registry = read_dataset_withdrawal_snapshot(
            withdrawal_snapshot, value.artifacts.withdrawal_snapshot.original(),
        ).map_err(invalid)?;
        require_before(end)?;
        let artifacts = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: value.artifacts.state_directory,
            trust,
            writer_lease,
            required_current_head: Some(required_current_head),
            withdrawal_registry,
            storage_binding: Digest32::from_array(value.artifacts.storage_binding),
            now: self.clock.now_unix_ms().map_err(invalid)?,
        }).map_err(invalid)?;
        let selected = AgentdSelectedGenerationV1::load(
            &artifacts, verifier, signed_selection,
            AgentdGenerationSelectionFilesV1 { registry_snapshot, payload: selected_payload },
            self.clock.now_unix_ms().map_err(invalid)?,
        )?;
        require_before(end)?;
        // The protected file names an already existing generation nonce owner.
        // The original issuer verifier binds its grant signer to this key id,
        // and FinalUse::claim binds that signer to the nonce owner in BOTH trust
        // models. Keep the explicit owner id and check this original relation.
        let key = self.issuer.trust_key()?;
        let head = self.issuer.revocations()?;
        let owner_id = value.consumer.owner_id;
        if owner_id != key.key_id
            || matches!(&value.operation, OperationFile::Fresh { signed, .. } if signed.grant.signer_id != owner_id)
        {
            return Err(invalid("the existing generation consumer differs from the original grant signer"));
        }
        let frontier = Arc::new(HostAuthorityFrontierStore::<FinalUseFrontier>::open(
            root, owner_id.clone(),
        ).map_err(invalid)?);
        if frontier.load(&owner_id).map_err(invalid)? != value.consumer.required_external_frontier {
            return Err(invalid("the existing generation consumer frontier differs from its complete pin"));
        }
        let final_use = match value.consumer.trust_model {
            ConsumerTrustModel::SingleCurrentIssuer => {
                FinalUseAuthority::open_state_dir_with_trust(
                    &value.consumer.state_directory, owner_id, key.verifying_key,
                    head.clone(), self.clock.clone(), frontier,
                )
            }
            ConsumerTrustModel::CurrentIssuerKeyRing => FinalUseAuthority::open_state_dir_with_issuer_keys(
                &value.consumer.state_directory, owner_id,
                vec![key], head.clone(), self.clock.clone(), frontier,
            ),
        }.map_err(invalid)?;
        if final_use.current_external_frontier().map_err(invalid)? != value.consumer.required_external_frontier
            || final_use.revocation_head().map_err(invalid)? != head
            || self.issuer.revocations()? != head
        {
            return Err(invalid("the original issuer or consumer changed while loading"));
        }
        require_before(end)?;
        let configuration = value.target.configuration;
        let binding = CellGenerationOwnerBindingV1::new(&configuration, value.target.maximum_records)
            .map_err(invalid)?;
        // Fresh input may initialize the header of its explicitly supplied
        // empty witness. Recovery was rejected before any such original open.
        let witness = FileAnchorWitnessStore::open(
            target_witness,
            JournalScope {
                scope_digest: Digest32::from_array(binding.digest().map_err(invalid)?),
                objective_digest: Digest32::from_array(configuration.task_digest),
            },
            Generation::new(configuration.initial.generation).map_err(invalid)?,
            value.target.maximum_witness_records,
        ).map_err(invalid)?;
        let target = AgentdGenerationUpdateTargetV1 {
            file: target_journal, witness, config: configuration,
            max_records: value.target.maximum_records,
        };
        let artifacts = Arc::new(Mutex::new(artifacts));
        let final_use = Arc::new(final_use);
        require_before(end)?;
        Ok(match value.operation {
            OperationFile::Fresh { operation_id, signed } => LoadedOriginalGeneration::Fresh(
                RootHostInitialGenerationInputsV1 {
                    artifacts, final_use, selected, target,
                    request: AgentdGenerationUpdateRequestV1 { operation_id }, signed,
                },
            ),
            OperationFile::Recover { operation_id, intent_digest } => LoadedOriginalGeneration::Recover(
                RootHostInitialGenerationRecoveryV1 {
                    artifacts, final_use, selected, target,
                    recovery: AgentdGenerationUpdateRecoveryV1 {
                        operation_id, intent_digest: Digest32::from_array(intent_digest),
                    },
                },
            ),
        })
    }
}

fn require_before(end: Instant) -> Result<(), AgentdError> {
    // SAFETY: these calls inspect only the actual current process credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 || Instant::now() >= end {
        return Err(invalid("the original Root input-loading window ended"));
    }
    Ok(())
}
