//! Explicit recovery of the original Selection/NextUse signatures using the
//! same Root's read-only completed successor. There is no Create lifecycle.

use super::*;
use crate::OriginalHistoricalCircuitFeatureSourcesV1;

pub(crate) struct OriginalHistoricalCircuitFeatureLearningHandoffV1 {
    pub(crate) source: OriginalHistoricalCircuitFeatureSourcesV1,
    pub(crate) selection: OriginalGenerationLearningSigningFilesV1,
    pub(crate) next_use: OriginalGenerationLearningSigningFilesV1,
    pub(crate) verifier: LearningEvidenceVerifierV1,
}

impl OriginalHistoricalCircuitFeatureLearningHandoffV1 {
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
        let selection = OriginalGenerationLearningReceiptOwnerV1::recover_historical_feature(
            self.selection.file,
            self.selection.witness,
            selection_config,
            self.selection.key,
            self.source.clone(),
        )
        .map_err(owner_error)?;
        let next_use = OriginalGenerationLearningReceiptOwnerV1::recover_historical_feature(
            self.next_use.file,
            self.next_use.witness,
            next_config,
            self.next_use.key,
            self.source,
        )
        .map_err(owner_error)?;
        Ok((selection, next_use))
    }
}

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) async fn install_historical_circuit_feature_generation(
        &self,
        snapshot: LearningIterationSnapshotV1,
        original: OriginalHistoricalCircuitFeatureLearningHandoffV1,
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
