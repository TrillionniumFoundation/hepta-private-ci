//! Open-only assembly from the frozen Root locations and actual late material.

use std::io;
use std::sync::Arc;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use super::data::*;
use super::files::OriginalFile;
use crate::AgentdGenerationSelectionFilesV1;
use crate::RootArtifactPublicationInputsV1;
use crate::RootGenerationJournalInputsV1;
use crate::RootGenerationPublicationEnrollmentV1;
use crate::RootGenerationPublicationModeV1;

pub(super) struct OriginalInputs {
    pub current: Arc<RootAuthorityDirectory>,
    pub previous_journal: OriginalFile, pub previous_witness: OriginalFile,
    pub target_journal: OriginalFile, pub target_witness: OriginalFile,
    pub withdrawal: OriginalFile,
}

impl OriginalInputs {
    pub(super) fn require_original_inputs(&self) -> io::Result<()> {
        for file in [&self.previous_journal, &self.previous_witness,
            &self.target_journal, &self.target_witness, &self.withdrawal] {
            file.require_original_file()?;
        }
        Ok(())
    }

    pub(super) fn enrollment_inputs(
        &self, data: &DeploymentData, material: &LateMaterial, consumer_uid: u32,
    ) -> io::Result<(RootGenerationPublicationEnrollmentV1, Vec<OriginalFile>)> {
        self.require_original_inputs()?;
        if material.schema_version != 1 { return Err(io::Error::other("late material version differs")); }
        let trust = data.owner_trust.original_owner_trust()?;
        let selector = data.selector_trust.original_selector(&trust)?;
        let retained_current = data.retained_current.original_current()?;
        let withdrawal_floor = read_dataset_withdrawal_snapshot(self.withdrawal.original_descriptor()?, DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::from_array(data.withdrawal.binding),
            scope_digest: Digest32::from_array(data.withdrawal.scope),
            head_digest: Digest32::from_array(data.withdrawal.head),
            file_digest: Digest32::from_array(data.withdrawal.file_digest),
            records: data.withdrawal.records, encoded_bytes: data.withdrawal.encoded_bytes,
        }).map_err(io::Error::other)?;
        let selected = material.selection.original_selection()?;
        // Locators come from the same actual read-view; late JSON cannot add paths.
        let now: u64 = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
            .map_err(io::Error::other)?.as_millis().try_into().map_err(io::Error::other)?;
        let reader: LearningArtifactReadViewV1 = LearningArtifactReadViewV1::open_original(
            data.artifact_root.clone(), consumer_uid, trust.clone(), retained_current.clone(), now,
        ).map_err(io::Error::other)?.with_original_withdrawal_floor(
            Digest32::from_array(data.storage_binding), withdrawal_floor.clone(),
        ).map_err(io::Error::other)?;
        let paths = reader.locate_selected_original_files(&selector, &selected, now).map_err(io::Error::other)?;
        let registry = OriginalFile::open_original(&paths.0)?;
        let payload = OriginalFile::open_original(&paths.1)?;
        if reader.locate_selected_original_files(&selector, &selected, now).map_err(io::Error::other)? != paths {
            return Err(io::Error::other("original selected files changed during capture"));
        }
        let inputs = RootGenerationPublicationEnrollmentV1 {
            mode: match data.mode { Mode::Reserve => RootGenerationPublicationModeV1::Reserve, Mode::Recover => RootGenerationPublicationModeV1::Recover },
            current_directory: Arc::clone(&self.current),
            previous: RootGenerationJournalInputsV1 {
                journal: self.previous_journal.original_descriptor()?, witness: self.previous_witness.original_descriptor()?,
                config: data.previous.original_observer_config()?,
            },
            target: RootGenerationJournalInputsV1 {
                journal: self.target_journal.original_descriptor()?, witness: self.target_witness.original_descriptor()?,
                config: material.target.original_observer_config()?,
            },
            artifacts: RootArtifactPublicationInputsV1 {
                root: data.artifact_root.clone(), trust, retained_current,
                storage_binding: Digest32::from_array(data.storage_binding), withdrawal_floor,
                selector, signed_selection: selected,
                files: AgentdGenerationSelectionFilesV1 {
                    registry_snapshot: registry.original_descriptor()?, payload: payload.original_descriptor()?,
                },
            },
            consumer: data.consumer, consumer_state_root: data.consumer_state_root.clone(),
            issuer_keys: data.issuer_keys.iter().map(|key| FinalUseIssuerTrustKey {
                key_id: key.key_id.clone(), verifying_key: key.verifying_key,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            }).collect(),
        };
        self.require_original_inputs()?;
        Ok((inputs, vec![registry, payload]))
    }
}
