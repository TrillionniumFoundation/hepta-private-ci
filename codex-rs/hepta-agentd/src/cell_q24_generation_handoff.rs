//! One original published successor, with its existing role and storage inputs.
//! This cannot publish CURRENT, grant FinalUse or submit a generation request.

use std::fs::File;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use ed25519_dalek::SigningKey;

use crate::CellQ24PreparedLearningV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::OriginalCellQ24LearningOpenV1;
use crate::OriginalGenerationLearningReceiptConfigV1;
use crate::OriginalGenerationLearningReceiptOwnerV1;
use crate::OriginalGenerationLearningReceiptSourcesV1;
use crate::OriginalGenerationLearningRoleV1;

pub struct OriginalGenerationLearningSigningFilesV1 {
    pub file: File,
    pub witness: FileAnchorWitnessStore,
    pub signer: TrustedLearningSignerV1,
    pub key: SigningKey,
    pub maximum_signature_lifetime_seconds: u64,
}

/// Both receipt owners retain the same actual actor. An unpublished handle or
/// an arbitrary intent fails its protected readback before a receipt is issued.
pub struct OriginalCellQ24GenerationHandoffV1 {
    pub runtime: NeuronGenerationRuntimeHandleV2,
    pub baseline: CellBackendManifestV2,
    pub intent: CellGenerationIntentV2,
    pub selection: OriginalGenerationLearningSigningFilesV1,
    pub next_use: OriginalGenerationLearningSigningFilesV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub mode: OriginalCellQ24LearningOpenV1,
}

impl OriginalGenerationLearningSigningFilesV1 {
    fn open(
        self,
        config: OriginalGenerationLearningReceiptConfigV1,
        source: OriginalGenerationLearningReceiptSourcesV1,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>, Error> {
        match mode {
            OriginalCellQ24LearningOpenV1::Create => {
                OriginalGenerationLearningReceiptOwnerV1::create(
                    self.file,
                    self.witness,
                    config,
                    self.key,
                    source,
                )
            }
            OriginalCellQ24LearningOpenV1::Recover => {
                OriginalGenerationLearningReceiptOwnerV1::recover(
                    self.file,
                    self.witness,
                    config,
                    self.key,
                    source,
                )
            }
        }
        .map_err(|_| Error::OwnerUnavailable("original generation receipt journal"))
    }
}

impl OriginalCellQ24GenerationHandoffV1 {
    pub(crate) fn into_receipt_owners(
        self,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<
        (
            OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
            OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
        ),
        Error,
    > {
        let selection_config = OriginalGenerationLearningReceiptConfigV1 {
            initial: prepared.initial().clone(),
            scope: prepared.scope().clone(),
            role: OriginalGenerationLearningRoleV1::Selection,
            signer: self.selection.signer.clone(),
            verifier: self.verifier.clone(),
            maximum_signature_lifetime_seconds: self.selection.maximum_signature_lifetime_seconds,
        };
        let next_config = OriginalGenerationLearningReceiptConfigV1 {
            initial: prepared.initial().clone(),
            scope: prepared.scope().clone(),
            role: OriginalGenerationLearningRoleV1::NextUse,
            signer: self.next_use.signer.clone(),
            verifier: self.verifier,
            maximum_signature_lifetime_seconds: self.next_use.maximum_signature_lifetime_seconds,
        };
        let selection = self.selection.open(
            selection_config,
            OriginalGenerationLearningReceiptSourcesV1 {
                runtime: self.runtime.clone(),
                baseline: self.baseline.clone(),
                next_use: None,
            },
            self.mode,
        )?;
        let next_use = self.next_use.open(
            next_config,
            OriginalGenerationLearningReceiptSourcesV1 {
                runtime: self.runtime,
                baseline: self.baseline,
                next_use: Some(self.intent),
            },
            self.mode,
        )?;
        Ok((selection, next_use))
    }
}
