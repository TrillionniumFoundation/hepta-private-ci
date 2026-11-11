//! Original host-owned files consumed after the actual Observer Dataset cut.
//! Create and recovery are explicit; neither mode provisions a key or witness.

use std::fs::File;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use ed25519_dalek::SigningKey;

use crate::AgentdRootQ24ModelFactoryV1;
use crate::CellQ24LocalPolicyV1;
use crate::CellQ24PreparedLearningV1;
use crate::CellQ24TrainingOwnerV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24LocalDecisionConfigV1;
use crate::OriginalCellQ24LocalDecisionOwnerV1;
use crate::OriginalCellQ24SourceFilesV1;
use crate::OriginalCellQ24SourceReceiptOwnerV1;
use crate::OriginalCellQ24SourceStageV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingStageV1;
use crate::cell_q24_learning_owner_error::owner_error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalCellQ24LearningOpenV1 {
    Create,
    Recover,
}

pub struct OriginalCellQ24LocalDecisionFilesV1 {
    pub journal: File,
    pub witness: FileAnchorWitnessStore,
    pub policy: CellQ24LocalPolicyV1,
    pub signer: TrustedLearningSignerV1,
    pub key: SigningKey,
    pub maximum_signature_lifetime_seconds: u64,
    /// Explicit journal lifecycle, independent of whether later missing stages
    /// may execute. This permits recovery after another owner's genesis fails.
    pub mode: OriginalCellQ24LearningOpenV1,
}

/// The host may explicitly recover one journal and create the other after a
/// partial genesis. A Missing error never chooses a lifecycle automatically.
pub enum OriginalCellQ24SourceInputsV1 {
    Files(OriginalCellQ24SourceFilesV1),
    Owners {
        experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
        dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    },
}

impl OriginalCellQ24SourceInputsV1 {
    pub(crate) fn open_original_source_pair(
        self,
        prepared: std::sync::Arc<CellQ24PreparedLearningV1>,
        verifier: LearningEvidenceVerifierV1,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<
        (
            OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
            OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
        ),
        Error,
    > {
        let (experience, dataset) = match self {
            Self::Files(files) => {
                let files: OriginalCellQ24SourceFilesV1 = files;
                match mode {
                    OriginalCellQ24LearningOpenV1::Create => {
                        files.create(std::sync::Arc::clone(&prepared), verifier)
                    }
                    OriginalCellQ24LearningOpenV1::Recover => {
                        files.recover(std::sync::Arc::clone(&prepared), verifier)
                    }
                }
                .map_err(owner_error)?
            }
            Self::Owners {
                experience,
                dataset,
            } => (experience, dataset),
        };
        let experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> = experience;
        let dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> = dataset;
        experience
            .require_prepared(&prepared, OriginalCellQ24SourceStageV1::Experience)
            .map_err(owner_error)?;
        dataset
            .require_prepared(&prepared, OriginalCellQ24SourceStageV1::Dataset)
            .map_err(owner_error)?;
        Ok((experience, dataset))
    }
}

/// Actual capabilities provided by the original embedded production host.
/// The ordinary CLI has no way to construct these from descriptor JSON alone.
pub struct OriginalCellQ24LearningInputsV1 {
    pub prepared: std::sync::Arc<CellQ24PreparedLearningV1>,
    pub sources: OriginalCellQ24SourceInputsV1,
    pub training: OriginalCellQ24TrainingInputsV1,
    pub local: OriginalCellQ24LocalDecisionFilesV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub mode: OriginalCellQ24LearningOpenV1,
    pub queue_capacity: usize,
}

impl OriginalCellQ24LocalDecisionFilesV1 {
    pub(crate) fn open_original_local_decision(
        self,
        prepared: &CellQ24PreparedLearningV1,
        verifier: LearningEvidenceVerifierV1,
        factory: &AgentdRootQ24ModelFactoryV1,
    ) -> Result<OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore>, Error> {
        let config = OriginalCellQ24LocalDecisionConfigV1 {
            initial: prepared.initial().clone(),
            scope: prepared.scope().clone(),
            policy: self.policy,
            signer: self.signer,
            verifier,
            maximum_signature_lifetime_seconds: self.maximum_signature_lifetime_seconds,
        };
        match self.mode {
            OriginalCellQ24LearningOpenV1::Create => OriginalCellQ24LocalDecisionOwnerV1::create(
                self.journal,
                self.witness,
                config,
                self.key,
                factory,
            ),
            OriginalCellQ24LearningOpenV1::Recover => OriginalCellQ24LocalDecisionOwnerV1::recover(
                self.journal,
                self.witness,
                config,
                self.key,
                factory,
            ),
        }
        .map_err(owner_error)
    }
}

pub struct OriginalCellQ24TrainingFilesV1 {
    pub training: File,
    pub training_witness: FileAnchorWitnessStore,
    pub receipts: File,
    pub receipt_witness: FileAnchorWitnessStore,
    pub signer: TrustedLearningSignerV1,
    pub key: SigningKey,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// Original typed owners also allow explicit trainer-recover / receipt-create
/// after a partial genesis. The actual Dataset and native provenance are still
/// checked before assembly; neither a receipt nor an HQ24 tag supplies them.
pub enum OriginalCellQ24TrainingInputsV1 {
    Files(OriginalCellQ24TrainingFilesV1),
    Owners {
        training: CellQ24TrainingOwnerV1<FileAnchorWitnessStore>,
        receipts: OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>,
    },
}

impl OriginalCellQ24TrainingInputsV1 {
    pub(crate) fn open_original_training_pair(
        self,
        prepared: &CellQ24PreparedLearningV1,
        dataset: LearningIterationSnapshotV1,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<
        (
            CellQ24TrainingOwnerV1<FileAnchorWitnessStore>,
            OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>,
        ),
        Error,
    > {
        prepared
            .training_material(dataset.clone(), prepared.scope().clone())
            .map_err(|_| Error::WrongScope)?;
        let (training, receipts) = match self {
            Self::Files(files) => files.open(prepared, dataset.clone(), mode)?,
            Self::Owners { training, receipts } => (training, receipts),
        };
        OriginalCellQ24TrainingStageV1::require_original_pair(
            &training,
            &receipts,
            &dataset,
            prepared.scope(),
        )
        .map_err(owner_error)?;
        Ok((training, receipts))
    }
}

impl OriginalCellQ24TrainingFilesV1 {
    pub(crate) fn open(
        self,
        prepared: &CellQ24PreparedLearningV1,
        dataset: LearningIterationSnapshotV1,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<
        (
            CellQ24TrainingOwnerV1<FileAnchorWitnessStore>,
            OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>,
        ),
        Error,
    > {
        let material = prepared
            .training_material(dataset.clone(), prepared.scope().clone())
            .map_err(|_| Error::WrongScope)?;
        let training: CellQ24TrainingOwnerV1<FileAnchorWitnessStore> = match mode {
            OriginalCellQ24LearningOpenV1::Create => CellQ24TrainingOwnerV1::create(
                self.training,
                self.training_witness,
                material.plan,
                material.batch,
                material.rule,
            ),
            OriginalCellQ24LearningOpenV1::Recover => CellQ24TrainingOwnerV1::recover(
                self.training,
                self.training_witness,
                material.plan,
                material.batch,
                material.rule,
            ),
        }
        .map_err(owner_error)?;
        training
            .require_original_dataset_provenance()
            .map_err(|_| Error::OwnerUnavailable("original training Dataset capability"))?;
        let signing = OriginalCellQ24TrainingSigningConfigV1 {
            dataset,
            scope: prepared.scope().clone(),
            signer: self.signer,
            verifier: self.verifier,
            maximum_signature_lifetime_seconds: self.maximum_signature_lifetime_seconds,
        };
        let receipts = match mode {
            OriginalCellQ24LearningOpenV1::Create => OriginalCellQ24TrainingReceiptOwnerV1::create(
                self.receipts,
                self.receipt_witness,
                signing,
                self.key,
            ),
            OriginalCellQ24LearningOpenV1::Recover => {
                OriginalCellQ24TrainingReceiptOwnerV1::recover(
                    self.receipts,
                    self.receipt_witness,
                    signing,
                    self.key,
                )
            }
        }
        .map_err(owner_error)?;
        Ok((training, receipts))
    }
}
