//! Preserve durable uncertainty across original typed owner and I/O wrappers.
//! Classification inspects types and sources, never error strings or receipts.

use std::error::Error as StdError;

use codex_hepta_intelligence_eval::FencedHoldoutError;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_neuron::CellGenerationErrorV2;

use crate::CellQ24ModelProposalErrorV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

pub(crate) fn owner_error(error: impl StdError + 'static) -> Error {
    if is_commit_uncertain(&error) {
        Error::CommitUncertain
    } else {
        Error::OwnerUnavailable("original Q24 learning owner")
    }
}

pub(crate) fn is_commit_uncertain(error: &(dyn StdError + 'static)) -> bool {
    if matches!(
        error.downcast_ref::<CellQ24ModelProposalErrorV1>(),
        Some(CellQ24ModelProposalErrorV1::Pending | CellQ24ModelProposalErrorV1::CommitUncertain)
    ) || matches!(
        error.downcast_ref::<CellQ24TrainingOwnerErrorV1>(),
        Some(CellQ24TrainingOwnerErrorV1::Pending | CellQ24TrainingOwnerErrorV1::CommitUncertain)
    ) || matches!(
        error.downcast_ref::<LearningOriginalOwnerErrorV1>(),
        Some(LearningOriginalOwnerErrorV1::Pending | LearningOriginalOwnerErrorV1::CommitUncertain)
    ) || matches!(
        error.downcast_ref::<OriginalCellQ24TrainingStageErrorV1>(),
        Some(
            OriginalCellQ24TrainingStageErrorV1::Busy
                | OriginalCellQ24TrainingStageErrorV1::CommitUncertain
        )
    ) || matches!(
        error.downcast_ref::<ProductEvaluationExecutionStoreErrorV1>(),
        Some(ProductEvaluationExecutionStoreErrorV1::Indeterminate)
    ) || matches!(
        error.downcast_ref::<ProductEvaluationExecutionErrorV1>(),
        Some(ProductEvaluationExecutionErrorV1::Pending)
    ) || matches!(
        error.downcast_ref::<ProductProviderErrorV1>(),
        Some(ProductProviderErrorV1::Indeterminate)
    ) || matches!(
        error.downcast_ref::<ProductEvidenceSinkErrorV1>(),
        Some(ProductEvidenceSinkErrorV1::Indeterminate)
    ) || matches!(
        error.downcast_ref::<FencedHoldoutError>(),
        Some(
            FencedHoldoutError::Indeterminate
                | FencedHoldoutError::Store(FinalHoldoutCasStoreError::Indeterminate)
        )
    ) || matches!(
        error.downcast_ref::<FinalHoldoutCasStoreError>(),
        Some(FinalHoldoutCasStoreError::Indeterminate)
    ) || matches!(
        error.downcast_ref::<CellGenerationErrorV2>(),
        Some(CellGenerationErrorV2::Pending | CellGenerationErrorV2::CommitUncertain)
    ) || matches!(error.downcast_ref::<Error>(), Some(Error::CommitUncertain))
    {
        return true;
    }
    if let Some(crate::AgentdError::Io(io)) = error.downcast_ref::<crate::AgentdError>()
        && is_commit_uncertain(io)
    {
        return true;
    }
    // std::io::Error::source need not expose the contained error itself. The
    // factory deliberately retains its original typed error in get_ref().
    if let Some(io) = error.downcast_ref::<std::io::Error>()
        && let Some(inner) = io.get_ref()
        && is_commit_uncertain(inner)
    {
        return true;
    }
    error.source().is_some_and(is_commit_uncertain)
}

#[cfg(test)]
#[path = "cell_q24_learning_owner_error_tests.rs"]
mod tests;
