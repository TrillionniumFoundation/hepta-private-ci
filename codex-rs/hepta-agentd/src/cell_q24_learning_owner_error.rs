//! Preserve durable uncertainty across original typed owner and I/O wrappers.
//! Classification inspects types and sources, never error strings or receipts.

use std::error::Error as StdError;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;

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
