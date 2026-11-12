//! Read-only original Initial input assembly after the real consumer is ready.
//! Paths and public data are checked again by the original same-Root enrollment.

use super::data::InitialDeploymentData;
use super::shared_files::OriginalFile;
use crate::AgentdGenerationSelectionFilesV1;
use crate::RootArtifactPublicationInputsV1;
use crate::RootGenerationInitialEnrollmentV1;
use crate::RootGenerationJournalInputsV1;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::DatasetWithdrawalSnapshotReceiptV1;
use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;
use codex_hepta_learning_artifacts::read_dataset_withdrawal_snapshot;
use codex_hepta_types::Digest32;
use std::io;
use std::sync::Arc;

pub(super) struct InitialOriginalFiles {
    pub learning_trust: Option<Arc<super::RootInitialLearningTrustFilesV1>>,
    pub current: Arc<RootAuthorityDirectory>,
    pub target_journal: OriginalFile,
    pub target_witness: OriginalFile,
    pub withdrawal: OriginalFile,
}

impl InitialOriginalFiles {
    pub(super) fn require_initial_files(&self) -> io::Result<()> {
        if let Some(trust) = &self.learning_trust {
            trust.require_original_files()?;
        }
        self.target_journal.require_original_file()?;
        self.target_witness.require_original_file()?;
        self.withdrawal.require_original_file()
    }

    pub(super) fn initial_enrollment_inputs(
        &self,
        data: &InitialDeploymentData,
        consumer_uid: u32,
    ) -> io::Result<(RootGenerationInitialEnrollmentV1, Vec<OriginalFile>)> {
        self.require_initial_files()?;
        let trust = data.owner_trust.original_owner_trust()?;
        let selector = data.selector_trust.original_selector(&trust)?;
        let retained_current = data.retained_current.original_current()?;
        let withdrawal_floor = read_dataset_withdrawal_snapshot(
            self.withdrawal.original_descriptor()?,
            DatasetWithdrawalSnapshotReceiptV1 {
                binding: Digest32::from_array(data.withdrawal.binding),
                scope_digest: Digest32::from_array(data.withdrawal.scope),
                head_digest: Digest32::from_array(data.withdrawal.head),
                file_digest: Digest32::from_array(data.withdrawal.file_digest),
                records: data.withdrawal.records,
                encoded_bytes: data.withdrawal.encoded_bytes,
            },
        )
        .map_err(io::Error::other)?;
        let selected = data.selection.original_selection()?;
        let now: u64 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_millis()
            .try_into()
            .map_err(io::Error::other)?;
        let reader: LearningArtifactReadViewV1 = LearningArtifactReadViewV1::open_original(
            data.artifact_root.clone(),
            consumer_uid,
            trust.clone(),
            retained_current.clone(),
            now,
        )
        .map_err(io::Error::other)?
        .with_original_withdrawal_floor(
            Digest32::from_array(data.storage_binding),
            withdrawal_floor.clone(),
        )
        .map_err(io::Error::other)?;
        let paths = reader
            .locate_selected_original_files(&selector, &selected, now)
            .map_err(io::Error::other)?;
        let registry = OriginalFile::open_original(&paths.0)?;
        let payload = OriginalFile::open_original(&paths.1)?;
        if reader
            .locate_selected_original_files(&selector, &selected, now)
            .map_err(io::Error::other)?
            != paths
        {
            return Err(io::Error::other("original Initial selected files changed"));
        }
        let inputs = RootGenerationInitialEnrollmentV1 {
            learning_trust: self.learning_trust.clone(),
            mode: data.mode,
            current_directory: Arc::clone(&self.current),
            target: RootGenerationJournalInputsV1 {
                journal: self.target_journal.original_descriptor()?,
                witness: self.target_witness.original_descriptor()?,
                config: data.target.original_observer_config()?,
            },
            artifacts: RootArtifactPublicationInputsV1 {
                root: data.artifact_root.clone(),
                trust,
                retained_current,
                storage_binding: Digest32::from_array(data.storage_binding),
                withdrawal_floor,
                selector,
                signed_selection: selected,
                files: AgentdGenerationSelectionFilesV1 {
                    registry_snapshot: registry.original_descriptor()?,
                    payload: payload.original_descriptor()?,
                },
            },
            consumer: data.consumer,
            consumer_state_root: data.consumer_state_root.clone(),
            issuer_keys: data
                .issuer_keys
                .iter()
                .map(|key| FinalUseIssuerTrustKey {
                    key_id: key.key_id.clone(),
                    verifying_key: key.verifying_key,
                    not_before_authority_epoch: key.not_before_authority_epoch,
                    not_after_authority_epoch: key.not_after_authority_epoch,
                })
                .collect(),
        };
        self.require_initial_files()?;
        Ok((inputs, vec![registry, payload]))
    }
}
