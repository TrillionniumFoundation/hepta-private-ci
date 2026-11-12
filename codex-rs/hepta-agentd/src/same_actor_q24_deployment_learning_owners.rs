//! Original Observer/Generator/Selector resources opened only after the real
//! same-session scoped handoff. Prepared is the exact object from A's producer;
//! its Dataset, targets and Training batch are never deserialized here.

use std::sync::Arc;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use serde::Deserialize;
use serde::Serialize;

use super::OriginalDeploymentLearning;
use super::OriginalSignedOwnerFilesData;
use super::require_original_key;
use super::super::deployment_error;
use super::super::files::MutableFileData;
use super::super::files::OriginalDeploymentFiles;
use super::super::witness::OriginalWitnessData;
use super::super::witness::require_fresh_original_file;
use crate::AgentdError;
use crate::CellQ24LocalPolicyV1;
use crate::CellQ24PreparedLearningV1;
use crate::OriginalCellQ24LearningInputsV1;
use crate::OriginalCellQ24LearningOpenV1;
use crate::OriginalCellQ24LocalDecisionFilesV1;
use crate::OriginalCellQ24SourceFilesV1;
use crate::OriginalCellQ24SourceInputsV1;
use crate::OriginalCellQ24SourceJournalV1;
use crate::OriginalCellQ24TrainingFilesV1;
use crate::OriginalCellQ24TrainingInputsV1;
use crate::same_actor_q24_phase::OriginalSameActorLearningInputsV1;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(in crate::same_actor_q24_deployment) enum OriginalLocalPolicyData {
    AdoptQualified,
    RetainCurrent,
    DeferQualified,
}

impl OriginalLocalPolicyData {
    fn original(self) -> CellQ24LocalPolicyV1 {
        match self {
            Self::AdoptQualified => CellQ24LocalPolicyV1::AdoptQualified,
            Self::RetainCurrent => CellQ24LocalPolicyV1::RetainCurrent,
            Self::DeferQualified => CellQ24LocalPolicyV1::DeferQualified,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in crate::same_actor_q24_deployment) struct OriginalLearningOwnersData {
    pub experience: OriginalSignedOwnerFilesData,
    pub dataset: OriginalSignedOwnerFilesData,
    pub training: MutableFileData,
    pub training_witness: OriginalWitnessData,
    pub training_receipts: OriginalSignedOwnerFilesData,
    pub local: OriginalSignedOwnerFilesData,
    pub local_policy: OriginalLocalPolicyData,
    pub queue_capacity: usize,
    pub successor_queue_capacity: usize,
}

impl OriginalLearningOwnersData {
    pub(super) fn require_fresh(&self) -> Result<(), AgentdError> {
        self.experience.require_fresh()?;
        self.dataset.require_fresh()?;
        require_fresh_original_file(&self.training)?;
        require_fresh_original_file(&self.training_witness.file)?;
        self.training_receipts.require_fresh()?;
        self.local.require_fresh()?;
        Ok(())
    }
}

impl OriginalDeploymentLearning {
    pub(in crate::same_actor_q24_deployment) fn open_original_scoped_inputs(
        &self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<OriginalSameActorLearningInputsV1, AgentdError> {
        let data = &self.data.owners;
        data.require_fresh()?;
        files.require_original_context()?;
        prepared.revalidate_source().map_err(deployment_error)?;
        let experience = self.open_original_observer(&data.experience, files, now)?;
        let dataset = self.open_original_observer(&data.dataset, files, now)?;
        let training_signer = self.require_original_signer(
            &data.training_receipts.principal, LearningEvidenceRoleV1::Generator, now,
        )?;
        let training_key = files.read_original_signing_key(&data.training_receipts.key)?;
        require_original_key(&training_signer, &training_key)?;
        let training = files.open_original_owner(&data.training)?;
        let training_witness = data.training_witness.open_original(files)?;
        let receipts = files.open_original_owner(&data.training_receipts.journal)?;
        let receipt_witness = data.training_receipts.witness.open_original(files)?;
        let local_signer = self.require_original_signer(
            &data.local.principal, LearningEvidenceRoleV1::Selector, now,
        )?;
        let local_key = files.read_original_signing_key(&data.local.key)?;
        require_original_key(&local_signer, &local_key)?;
        let local_journal = files.open_original_owner(&data.local.journal)?;
        let local_witness = data.local.witness.open_original(files)?;
        prepared.revalidate_source().map_err(deployment_error)?;
        files.require_original_context()?;
        Ok(OriginalSameActorLearningInputsV1 {
            original: OriginalCellQ24LearningInputsV1 {
                prepared,
                sources: OriginalCellQ24SourceInputsV1::Files(OriginalCellQ24SourceFilesV1 {
                    experience, dataset,
                }),
                training: OriginalCellQ24TrainingInputsV1::Files(OriginalCellQ24TrainingFilesV1 {
                    training, training_witness, receipts, receipt_witness,
                    signer: training_signer, key: training_key,
                    verifier: self.verifier.clone(),
                    maximum_signature_lifetime_seconds:
                        data.training_receipts.maximum_signature_lifetime_seconds,
                }),
                local: OriginalCellQ24LocalDecisionFilesV1 {
                    journal: local_journal, witness: local_witness,
                    policy: data.local_policy.original(), signer: local_signer, key: local_key,
                    maximum_signature_lifetime_seconds:
                        data.local.maximum_signature_lifetime_seconds,
                    mode: OriginalCellQ24LearningOpenV1::Create,
                },
                verifier: self.verifier.clone(),
                mode: OriginalCellQ24LearningOpenV1::Create,
                queue_capacity: data.queue_capacity,
            },
            successor_queue_capacity: data.successor_queue_capacity,
        })
    }

    fn open_original_observer(
        &self,
        data: &OriginalSignedOwnerFilesData,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<OriginalCellQ24SourceJournalV1, AgentdError> {
        data.require_fresh()?;
        let signer = self.require_original_signer(
            &data.principal, LearningEvidenceRoleV1::Observer, now,
        )?;
        let key = files.read_original_signing_key(&data.key)?;
        require_original_key(&signer, &key)?;
        let journal = files.open_original_owner(&data.journal)?;
        let witness = data.witness.open_original(files)?;
        files.require_original_context()?;
        Ok(OriginalCellQ24SourceJournalV1 {
            journal, witness, signer, key,
            maximum_signature_lifetime_seconds: data.maximum_signature_lifetime_seconds,
        })
    }
}
