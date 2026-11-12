//! Original E/D and Trainer construction enclosed by one actual Prepared read.
//! All journal/witness operations remain real. The enclosing operation checks
//! the source again even when work fails; only owned capabilities escape it.

use super::*;
use crate::cell_composed_q24::OriginalPreparedReadV1;

pub(super) struct OriginalInitialOwnersV1 {
    pub(super) experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    pub(super) dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    pub(super) dataset_cut: LearningIterationSnapshotV1,
    pub(super) training:
        OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
}

pub(super) fn initialize_original_owners(
    prepared: Arc<CellQ24PreparedLearningV1>,
    sources: crate::OriginalCellQ24SourceInputsV1,
    verifier: LearningEvidenceVerifierV1,
    files: OriginalCellQ24TrainingInputsV1,
    mode: OriginalCellQ24LearningOpenV1,
) -> Result<OriginalInitialOwnersV1, Error> {
    let original = Arc::clone(&prepared);
    original
        .with_original_prepared_operation(move |read| {
            OriginalPreparedReadV1::require_prepared(read, &prepared).map_err(unavailable)?;
            let (experience, dataset) = sources.open_original_source_pair_in_operation(
                Arc::clone(&prepared),
                verifier,
                mode,
                read,
            )?;
            let mut experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> =
                experience;
            let mut dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> = dataset;
            let completed = match mode {
                OriginalCellQ24LearningOpenV1::Create => {
                    experience
                        .attest_experience_in_operation(read)
                        .map_err(unavailable)?;
                    dataset
                        .attest_dataset_in_operation(&mut experience, read)
                        .map_err(unavailable)?
                }
                OriginalCellQ24LearningOpenV1::Recover => dataset
                    .read_dataset_in_operation(&mut experience, read)
                    .map_err(unavailable)?,
            };
            let dataset_cut = completed.snapshot().clone();
            let (training, receipts) = files.open_original_training_pair_in_operation(
                &prepared,
                dataset_cut.clone(),
                mode,
                read,
            )?;
            let training = OriginalCellQ24TrainingStageV1::from_original_owners_in_operation(
                training,
                receipts,
                &dataset_cut,
                prepared.scope(),
                read,
            )
            .map_err(unavailable)?;
            OriginalPreparedReadV1::require_prepared(read, &prepared).map_err(unavailable)?;
            Ok(OriginalInitialOwnersV1 {
                experience,
                dataset,
                dataset_cut,
                training,
            })
        })
        .map_err(unavailable)?
}
