//! Private Version dispatch. The original three-cut context is unchanged.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;

use super::super::context::PublicationAccess;
use super::Error;
use super::context::OriginalVersionCut;
use super::evaluated_context::OriginalEvaluatedVersionCut;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCircuitEvaluatedLearningReadContextV1;
use crate::OriginalCircuitLearningReadContextV1;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum VersionPurpose {
    TrainingNoUpdate,
    Evaluated,
}

pub(super) enum VersionCut {
    TrainingNoUpdate(OriginalVersionCut),
    Evaluated(OriginalEvaluatedVersionCut),
}

impl VersionCut {
    pub(super) fn purpose(&self) -> VersionPurpose {
        match self {
            Self::TrainingNoUpdate(_) => VersionPurpose::TrainingNoUpdate,
            Self::Evaluated(_) => VersionPurpose::Evaluated,
        }
    }

    pub(super) fn dataset(&self) -> &OriginalCellQ24MaterialCommandReceiptV1 {
        match self {
            Self::TrainingNoUpdate(original) => &original.dataset,
            Self::Evaluated(original) => &original.dataset,
        }
    }

    pub(super) fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        match self {
            Self::TrainingNoUpdate(original) => &original.training.training,
            Self::Evaluated(original) => original.evaluated.snapshot(),
        }
    }

    pub(super) fn initial_binding(&self) -> Digest32 {
        match self {
            Self::TrainingNoUpdate(original) => original.initial_binding,
            Self::Evaluated(original) => original.initial_binding,
        }
    }

    pub(super) fn decision(
        &self,
        at: u64,
        access: PublicationAccess,
    ) -> Result<LearningIterationCoordinatorV1, Error> {
        match self {
            Self::TrainingNoUpdate(original) => Ok(original.training.authenticate(at, access)?),
            Self::Evaluated(original) => Ok(original.evaluated.authenticate(at, access)?),
        }
    }

    pub(super) fn require_fresh(
        &self,
        started: u64,
        access: PublicationAccess,
    ) -> Result<(), Error> {
        match self {
            Self::TrainingNoUpdate(original) => original.require_fresh(started, access),
            Self::Evaluated(original) => original.require_fresh(started, access),
        }
    }

    pub(super) fn duplicate_response_pin(&self) -> Self {
        match self {
            Self::TrainingNoUpdate(original) => {
                Self::TrainingNoUpdate(original.duplicate_response_pin())
            }
            Self::Evaluated(original) => Self::Evaluated(original.duplicate_response_pin()),
        }
    }

    pub(super) fn legacy_reader(&self) -> Result<OriginalCircuitLearningReadContextV1, Error> {
        let Self::TrainingNoUpdate(cut) = self else {
            return Err(Error::Binding("original three-cut Version read purpose"));
        };
        Ok(OriginalCircuitLearningReadContextV1 {
            prefix: cut.training.training.clone(),
            scope: cut.training.scope.clone(),
            verifier: cut.training.verifier.clone(),
            training_evidence: cut.training.training_evidence.clone(),
            selection_evidence: None,
        })
    }

    pub(super) fn evaluated_reader(
        &self,
    ) -> Result<OriginalCircuitEvaluatedLearningReadContextV1, Error> {
        let Self::Evaluated(cut) = self else {
            return Err(Error::Binding(
                "original four-cut evaluated Version read purpose",
            ));
        };
        OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(
            cut.evaluated.clone_for_original_receipt(),
        )
        .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))
    }
}
