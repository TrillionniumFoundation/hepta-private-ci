//! Explicit installation of completed ordinary C owners into the learning
//! aggregate. Each original journal has its own chosen Create/Recover lifecycle.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24LearningOpenV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalCircuitFeatureLearningSourcesV1;
use crate::OriginalGenerationLearningReceiptConfigV1;
use crate::OriginalGenerationLearningReceiptOwnerV1;
use crate::OriginalGenerationLearningRoleV1;
use crate::OriginalGenerationLearningSigningFilesV1;
use crate::cell_q24_learning_owner_error::owner_error;

#[path = "circuit_feature_historical_handoff.rs"]
mod historical;
pub(crate) use historical::OriginalHistoricalCircuitFeatureLearningHandoffV1;

/// Original published Cell/source owners and the already enrolled Selector and
/// Observer capabilities. No field accepts a purported observation or grant.
pub struct OriginalCircuitFeatureLearningHandoffV1 {
    pub source: OriginalCircuitFeatureLearningSourcesV1,
    pub selection: OriginalGenerationLearningSigningFilesV1,
    pub next_use: OriginalGenerationLearningSigningFilesV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub selection_mode: OriginalCellQ24LearningOpenV1,
    pub next_use_mode: OriginalCellQ24LearningOpenV1,
}

impl OriginalCircuitFeatureLearningHandoffV1 {
    fn open(
        self,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
    ) -> Result<
        (
            OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
            OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
        ),
        Error,
    > {
        let config = |role, files: &OriginalGenerationLearningSigningFilesV1| {
            OriginalGenerationLearningReceiptConfigV1 {
                initial: initial.clone(),
                scope: scope.clone(),
                role,
                signer: files.signer.clone(),
                verifier: self.verifier.clone(),
                maximum_signature_lifetime_seconds: files.maximum_signature_lifetime_seconds,
            }
        };
        let selection_config = config(OriginalGenerationLearningRoleV1::Selection, &self.selection);
        let next_config = config(OriginalGenerationLearningRoleV1::NextUse, &self.next_use);
        let open = |files: OriginalGenerationLearningSigningFilesV1, config, source, mode| {
            match mode {
                OriginalCellQ24LearningOpenV1::Create => {
                    OriginalGenerationLearningReceiptOwnerV1::create_feature(
                        files.file,
                        files.witness,
                        config,
                        files.key,
                        source,
                    )
                }
                OriginalCellQ24LearningOpenV1::Recover => {
                    OriginalGenerationLearningReceiptOwnerV1::recover_feature(
                        files.file,
                        files.witness,
                        config,
                        files.key,
                        source,
                    )
                }
            }
            .map_err(owner_error)
        };
        let selection = open(
            self.selection,
            selection_config,
            self.source.clone(),
            self.selection_mode,
        )?;
        let next_use = open(self.next_use, next_config, self.source, self.next_use_mode)?;
        Ok((selection, next_use))
    }
}

impl OriginalCellQ24LearningStageOwnersV1 {
    /// Install actual ordinary C after its authenticated execution. Selection
    /// is read from the original published owner; NextUse reads the private Cell.
    /// Existing aggregate reconciliation rechecks all earlier original owners.
    pub async fn install_circuit_feature_generation(
        &self,
        snapshot: LearningIterationSnapshotV1,
        original: OriginalCircuitFeatureLearningHandoffV1,
    ) -> Result<(), Error> {
        let initial = self.prepared().initial().clone();
        let scope = self.prepared().scope().clone();
        if snapshot.request != initial.request || snapshot.owners != initial.owners {
            return Err(Error::WrongScope);
        }
        scope
            .validate_snapshot(&snapshot)
            .map_err(|_| Error::WrongScope)?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        self.require_current().await?;
        let (selection, next_use) =
            tokio::task::spawn_blocking(move || original.open(initial, scope))
                .await
                .map_err(|_| Error::CommitUncertain)??;
        self.install_generation(snapshot, selection, next_use).await
    }
}
