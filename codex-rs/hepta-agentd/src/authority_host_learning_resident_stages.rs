//! The only two original ordinary role bundles accepted by the Root factory.
//! This enum is private to the resident host. No caller-supplied implementation,
//! callback, Arc owner handle or branch tag can enter the coordinator.

use std::sync::Arc;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::LearningIterationStageOwnerPortsV1;
use crate::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCellQ24NoUpdateStageOwnersV1;
use crate::PreparedLearningIterationProposalV1;
use crate::RootResidentLearningEffectGateV3;
use crate::learning_iteration_evidence_client::OriginalCandidateOperationEvidence;

/// Construction is only the corresponding concrete, consuming public factory.
pub(super) enum ResidentOriginalStageOwnersV3 {
    NoUpdate(OriginalCellQ24NoUpdateStageOwnersV1),
    Candidate(OriginalCellQ24CandidateStageOwnersV1),
}

/// A single admitted continuation owns this value until its Root checkpoint.
/// No resident field, transport reply or recovered request can retain it.
pub(super) struct ResidentStageCompletion<'a> {
    pub(super) receipt: LearningIterationReceiptV1,
    pub(super) candidate: Option<OriginalCandidateOperationEvidence<'a>>,
}

impl ResidentOriginalStageOwnersV3 {
    pub(super) fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        match self {
            Self::NoUpdate(stages) => OriginalCellQ24NoUpdateStageOwnersV1::require_initial(
                stages, initial, scope, verifier,
            ),
            Self::Candidate(stages) => OriginalCellQ24CandidateStageOwnersV1::require_initial(
                stages, initial, scope, verifier,
            ),
        }
    }

    pub(super) fn install_fresh_resident_gate(
        &mut self,
        gate: Arc<RootResidentLearningEffectGateV3>,
    ) -> Result<(), Error> {
        match self {
            Self::NoUpdate(stages) => {
                OriginalCellQ24NoUpdateStageOwnersV1::install_fresh_resident_gate(stages, gate)
            }
            Self::Candidate(stages) => {
                OriginalCellQ24CandidateStageOwnersV1::install_fresh_resident_gate(stages, gate)
            }
        }
    }

    /// A branch choice neither adds a producer nor expands the original Root
    /// grant. Candidate Evaluation contacts its original material and the
    /// separately delivered original B/retention Evaluator command capability.
    pub(super) fn require_stage(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: Stage,
    ) -> Result<(), Error> {
        match stage {
            Stage::Evaluation | Stage::Proposal => match self {
                Self::NoUpdate(_) => Err(Error::OwnerUnavailable(
                    "resident NoUpdate profile has no Candidate Evaluation or Model route",
                )),
                Self::Candidate(_) => Ok(()),
            },
            Stage::Selection | Stage::NextUse
                if matches!(self, Self::Candidate(_))
                    && snapshot.training_no_update_v2().is_none() =>
            {
                Err(Error::OwnerUnavailable(
                    "original Candidate selection and adoption route is absent",
                ))
            }
            Stage::Experience
            | Stage::Dataset
            | Stage::Training
            | Stage::Selection
            | Stage::NextUse => Ok(()),
        }
    }

    pub(super) async fn read_original_candidate_evidence(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCandidateOperationEvidence<'_>, Error> {
        match self {
            Self::Candidate(stages) => {
                OriginalCellQ24CandidateStageOwnersV1::read_original_evidence(stages, snapshot).await
            }
            Self::NoUpdate(_) => Err(Error::OwnerUnavailable("NoUpdate has no Candidate evidence")),
        }
    }

    pub(super) async fn execute_original_stage(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: Stage,
    ) -> Result<ResidentStageCompletion<'_>, Error> {
        if let Self::Candidate(stages) = self
            && (matches!(stage, Stage::Evaluation | Stage::Proposal)
                || matches!(stage, Stage::Selection | Stage::NextUse)
                    && snapshot.training_no_update_v2().is_none())
        {
            let candidate = OriginalCellQ24CandidateStageOwnersV1::execute_original_evidence(
                stages, snapshot, stage,
            ).await?;
            return Ok(ResidentStageCompletion {
                receipt: candidate.receipt().clone(),
                candidate: Some(candidate),
            });
        }
        let receipt = LearningIterationStageOwnerPortsV1::execute_stage(self, snapshot, stage).await?;
        Ok(ResidentStageCompletion { receipt, candidate: None })
    }

    pub(super) fn consume_original_candidate_evidence(
        &self,
        original: OriginalCandidateOperationEvidence<'_>,
        snapshot: &LearningIterationSnapshotV1,
        observed: u64,
    ) -> Result<(Vec<SignedLearningEvidenceV1>, Option<crate::OriginalCellQ24ModelCommandReceiptV1>), Error> {
        match self {
            Self::Candidate(stages) => OriginalCandidateOperationEvidence::into_original_parts(original, stages, snapshot, observed),
            Self::NoUpdate(_) => Err(Error::WrongScope),
        }
    }
}

impl LearningIterationStageOwnerPortsV1 for ResidentOriginalStageOwnersV3 {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        match self {
            Self::NoUpdate(stages) => {
                LearningIterationStageOwnerPortsV1::validate_recovery(stages, snapshot)
            }
            Self::Candidate(stages) => {
                LearningIterationStageOwnerPortsV1::validate_recovery(stages, snapshot)
            }
        }
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: Stage,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        match self {
            Self::NoUpdate(stages) => {
                LearningIterationStageOwnerPortsV1::execute_stage(stages, snapshot, stage)
            }
            Self::Candidate(stages) => {
                LearningIterationStageOwnerPortsV1::execute_stage(stages, snapshot, stage)
            }
        }
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        match self {
            Self::NoUpdate(stages) => {
                LearningIterationStageOwnerPortsV1::prepare_proposal(stages, snapshot)
            }
            Self::Candidate(stages) => {
                LearningIterationStageOwnerPortsV1::prepare_proposal(stages, snapshot)
            }
        }
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        match self {
            Self::NoUpdate(stages) => LearningIterationStageOwnerPortsV1::receipt_attestation(
                stages,
                snapshot,
                receipt,
                now_unix_seconds,
            ),
            Self::Candidate(stages) => LearningIterationStageOwnerPortsV1::receipt_attestation(
                stages,
                snapshot,
                receipt,
                now_unix_seconds,
            ),
        }
    }
}
