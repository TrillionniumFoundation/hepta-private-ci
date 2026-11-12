//! Closed sum of the two concrete original cohort owners. A mode cannot be
//! changed by a caller, and no metadata can construct either read capability.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::CellEvaluationPlanV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationPanelTaskV1;
use crate::OriginalCircuitEvaluationCohortCurrentV1;
use crate::OriginalCircuitEvaluationCohortReadbackV1;
use crate::OriginalCircuitEvaluationProviderErrorV1 as Error;
use super::OriginalCircuitOnPolicyCohortCurrentV1;
use super::OriginalCircuitOnPolicyCohortReadbackV1;

pub struct OriginalCellEvaluationCohortCustodyV1 {
    original: OriginalCohort,
}

enum OriginalCohort {
    Shared(OriginalCircuitEvaluationCohortReadbackV1),
    Paired(OriginalCircuitOnPolicyCohortReadbackV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OriginalCellEvaluationCohortCurrentV1 {
    observed: OriginalCurrent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum OriginalCurrent {
    Shared(OriginalCircuitEvaluationCohortCurrentV1),
    Paired(OriginalCircuitOnPolicyCohortCurrentV1),
}

impl From<OriginalCircuitEvaluationCohortReadbackV1> for OriginalCellEvaluationCohortCustodyV1 {
    fn from(original: OriginalCircuitEvaluationCohortReadbackV1) -> Self {
        Self { original: OriginalCohort::Shared(original) }
    }
}

impl From<OriginalCircuitOnPolicyCohortReadbackV1> for OriginalCellEvaluationCohortCustodyV1 {
    fn from(original: OriginalCircuitOnPolicyCohortReadbackV1) -> Self {
        Self { original: OriginalCohort::Paired(original) }
    }
}

impl OriginalCellEvaluationCohortCurrentV1 {
    pub(crate) fn binding(&self) -> Digest32 {
        match &self.observed {
            OriginalCurrent::Shared(value) => value.binding(),
            OriginalCurrent::Paired(value) => value.binding(),
        }
    }
}

impl OriginalCellEvaluationCohortCustodyV1 {
    pub(crate) fn read_current(&mut self) -> Result<OriginalCellEvaluationCohortCurrentV1, Error> {
        let observed = match &mut self.original {
            OriginalCohort::Shared(owner) => OriginalCurrent::Shared(
                OriginalCircuitEvaluationCohortReadbackV1::read_current(owner)?),
            OriginalCohort::Paired(owner) => OriginalCurrent::Paired(
                OriginalCircuitOnPolicyCohortReadbackV1::read_current(owner)?),
        };
        Ok(OriginalCellEvaluationCohortCurrentV1 { observed })
    }

    pub(crate) fn require_original_member(
        &self,
        registration: &OriginalCellEvaluationPanelRegistrationV1,
        task: &OriginalCellEvaluationPanelTaskV1,
        training: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        plan: &CellEvaluationPlanV1,
        training_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        use codex_hepta_intelligence_eval::ProductComparisonModeV1;
        match (&self.original, plan.product_plan().comparison_mode()) {
            (OriginalCohort::Shared(_), ProductComparisonModeV1::SharedBehavior)
            | (OriginalCohort::Paired(_), ProductComparisonModeV1::PairedOnPolicy(_)) => (),
            _ => return Err(Error::Binding("same original provider and frozen comparison mode")),
        }
        match &self.original {
            OriginalCohort::Shared(owner) => OriginalCircuitEvaluationCohortReadbackV1::require_original_member(
                owner, registration, task, training, scope, plan, training_evidence, verifier),
            OriginalCohort::Paired(owner) => OriginalCircuitOnPolicyCohortReadbackV1::require_original_member(
                owner, registration, task, training, scope, plan, training_evidence, verifier),
        }
    }

    pub(crate) fn authenticate_current(
        &mut self,
        observed: &OriginalCellEvaluationCohortCurrentV1,
        current: u64,
    ) -> Result<(), Error> {
        match (&mut self.original, &observed.observed) {
            (OriginalCohort::Shared(owner), OriginalCurrent::Shared(value)) =>
                OriginalCircuitEvaluationCohortReadbackV1::authenticate_current(owner, value, current),
            (OriginalCohort::Paired(owner), OriginalCurrent::Paired(value)) =>
                OriginalCircuitOnPolicyCohortReadbackV1::authenticate_current(owner, value, current),
            _ => Err(Error::Binding("same original cohort mode and actual current observation")),
        }
    }

    pub(crate) fn original_model_commitment(
        &self,
        observed: &OriginalCellEvaluationCohortCurrentV1,
    ) -> Result<(Vec<u8>, Vec<u8>, SignedLearningEvidenceV1), Error> {
        match (&self.original, &observed.observed) {
            (OriginalCohort::Shared(owner), OriginalCurrent::Shared(value)) =>
                OriginalCircuitEvaluationCohortReadbackV1::original_model_commitment(owner, value),
            (OriginalCohort::Paired(owner), OriginalCurrent::Paired(value)) =>
                OriginalCircuitOnPolicyCohortReadbackV1::original_model_commitment(owner, value),
            _ => Err(Error::Binding("same original cohort mode and material observation")),
        }
    }
}

#[cfg(test)]
impl OriginalCellEvaluationCohortCustodyV1 {
    pub(crate) fn fixture_bytes(&mut self) -> anyhow::Result<[Vec<u8>; 2]> {
        match &mut self.original {
            OriginalCohort::Shared(owner) => owner.fixture_bytes(),
            OriginalCohort::Paired(owner) => owner.fixture_bytes(),
        }
    }
}
