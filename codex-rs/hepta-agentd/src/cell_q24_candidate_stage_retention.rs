//! A completed independent B NoUpdate keeps its actual Candidate and four-cut
//! evidence. The original Version, Selector and C channels move once from the
//! common admission; this continuation never supplies their signing custody.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::super::auth as common_auth;
use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1 as Owners;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitEvaluatedCompletionReadinessClientV1;
use crate::OriginalCircuitEvaluatedNextUseCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitRetainedVersionClientV1;

#[path = "cell_q24_candidate_stage_retention_attestations.rs"]
mod attestations;
#[path = "cell_q24_candidate_stage_retention_auth.rs"]
mod auth;
#[path = "cell_q24_candidate_stage_retention_binding.rs"]
mod binding;
#[path = "cell_q24_candidate_stage_retention_next_use.rs"]
mod next_use;
#[path = "cell_q24_candidate_stage_retention_selection.rs"]
mod selection;

/// Only the common continuation constructs this private move. These are the
/// same channels whose pidfds, frame limits and deadlines were bound at intake.
pub(in super::super) struct EvaluatedChannels {
    pub(in super::super) version: HostAuthorityPeerChannel,
    pub(in super::super) selector: HostAuthorityPeerChannel,
    pub(in super::super) next_use: HostAuthorityPeerChannel,
    pub(in super::super) readiness: HostAuthorityPeerChannel,
}

#[derive(Clone, Eq, PartialEq)]
struct Predecessors {
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    evaluation: OriginalCellEvaluationCommandReceiptV1,
}

#[derive(Clone, Eq, PartialEq)]
struct ReceiptPin {
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    signature: SignedLearningEvidenceV1,
    selection_binding: Digest32,
}

pub(super) struct EvaluatedLane {
    version: Option<OriginalCircuitRetainedVersionClientV1>,
    selector: Option<OriginalCircuitEvaluatedSelectionCommandClientV1>,
    next_use: Option<OriginalCircuitEvaluatedNextUseCommandClientV1>,
    readiness: Option<OriginalCircuitEvaluatedCompletionReadinessClientV1>,
    selector_initial: Option<HostAuthorityPeerChannel>,
    next_use_initial: Option<HostAuthorityPeerChannel>,
    readiness_initial: Option<HostAuthorityPeerChannel>,
    predecessors: Option<Predecessors>,
    selection: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
    completion: Option<ReceiptPin>,
    version_requests: usize,
    selection_requested: bool,
    completion_requested: bool,
    failed: bool,
}

impl EvaluatedLane {
    pub(super) fn new() -> Self {
        Self {
            version: None,
            selector: None,
            next_use: None,
            readiness: None,
            selector_initial: None,
            next_use_initial: None,
            readiness_initial: None,
            predecessors: None,
            selection: None,
            completion: None,
            version_requests: 0,
            selection_requested: false,
            completion_requested: false,
            failed: false,
        }
    }

    fn require_predecessors(&self, current: &Predecessors) -> Result<(), Error> {
        if self
            .predecessors
            .as_ref()
            .is_some_and(|saved| saved != current)
        {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn take_version_request(&mut self) -> Result<(), Error> {
        if self.version_requests >= 128 {
            return Err(Error::OwnerUnavailable(
                "original evaluated Version frame budget",
            ));
        }
        self.version_requests += 1;
        Ok(())
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Action {
    Execute,
    Readback,
}

/// Branch selection alone grants nothing. Each effect/read validates the full
/// coordinator and then obtains the opaque original D/T/B through live I/O.
pub(super) fn is_evaluated_retention(snapshot: &LearningIterationSnapshotV1) -> bool {
    snapshot.training_no_update_v2().is_none()
        && matches!(
            snapshot.receipts.get(3).map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            })
        )
}

impl Owners {
    pub(crate) fn require_evaluated_retention_stage(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: Stage,
    ) -> Result<(), Error> {
        if !is_evaluated_retention(snapshot) {
            return Err(Error::OwnerUnavailable(
                "original Candidate selection and adoption route is absent",
            ));
        }
        self.evaluated_retention_prefix(snapshot)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if coordinator.next_stage() != Some(stage)
            || !matches!(
                (stage, snapshot.receipts.len()),
                (Stage::Selection, 4) | (Stage::NextUse, 5)
            )
        {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

    fn evaluated_retention_prefix(
        &self,
        supplied: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        let training = self.training_prefix(supplied)?;
        if !(4..=6).contains(&supplied.receipts.len()) || !is_evaluated_retention(supplied) {
            return Err(Error::WrongScope);
        }
        let mut original = LearningIterationCoordinatorV1::from_snapshot(training)?;
        let evaluation = &supplied.receipts[3];
        original.record(evaluation.clone(), evaluation.observed_unix_seconds)?;
        if original.next_stage() != Some(Stage::Selection) || original.candidate().is_none() {
            return Err(Error::WrongScope);
        }
        self.common
            .material
            .scope
            .validate_snapshot(original.snapshot())?;
        Ok(original.snapshot().clone())
    }

    async fn evaluated_predecessors(
        &self,
        four_cut: &LearningIterationSnapshotV1,
    ) -> Result<Predecessors, Error> {
        let (dataset, training, evaluation) = self
            .read_original_evaluation_with_originals(four_cut)
            .await?
            .into_parts();
        let training_cut = self.training_prefix(four_cut)?;
        let mut common_lease = self.common.continuation.try_take()?;
        let common = common_lease.state_mut()?;
        // The awaited original Evaluation read already finished its final
        // actual E/D/T pass. Consume exactly those opaque originals, and keep
        // the existing fresh full-prefix authentication without another I/O.
        // This common lane still contains only the original E/D/T identities.
        if common.original_dataset.as_ref() != Some(&dataset)
            || common.original_training.as_ref() != Some(&training)
        {
            return Err(Error::CommitUncertain);
        }
        if evaluation.snapshot() != four_cut
            || evaluation.training_attestation() != training.attestation()
        {
            return Err(Error::WrongScope);
        }
        let fresh =
            common_auth::require_material(&self.common.material, self.common.initial_binding)?;
        common_auth::verify_prefix(&self.common.material, &training_cut, common, fresh)?;
        self.verify_original_evaluation(four_cut, &training_cut, &training, &evaluation, fresh)?;
        self.require_live_deadline()?;
        Ok(Predecessors {
            dataset,
            training,
            evaluation,
        })
    }

    pub(super) async fn execute_original_evaluated_retention(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: Stage,
    ) -> Result<LearningIterationReceiptV1, Error> {
        if self.common.origin != Origin::Fresh
            || LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()
                != Some(stage)
        {
            return Err(Error::WrongScope);
        }
        match stage {
            Stage::Selection => Ok(self
                .original_evaluated_selection(snapshot, Action::Execute)
                .await?
                .receipt()
                .clone()),
            Stage::NextUse => Ok(self
                .original_evaluated_next_use(snapshot, Action::Execute)
                .await?
                .receipt()
                .clone()),
            _ => Err(Error::WrongScope),
        }
    }

    pub(super) async fn read_original_evaluated_retention(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        self.evaluated_retention_prefix(snapshot)?;
        match snapshot.receipts.len() {
            4 => {
                self.read_original_evaluation(snapshot).await?;
            }
            5 => {
                self.original_evaluated_selection(snapshot, Action::Readback)
                    .await?;
            }
            6 => {
                self.original_evaluated_next_use(snapshot, Action::Readback)
                    .await?;
            }
            _ => return Err(Error::WrongScope),
        }
        Ok(())
    }

    pub(super) async fn evaluated_retention_attestation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let (receipt, signature) = match expected.observation.stage() {
            Stage::Selection => {
                let original = self
                    .original_evaluated_selection(snapshot, Action::Readback)
                    .await?;
                (original.receipt().clone(), original.attestation().clone())
            }
            Stage::NextUse => {
                let original = self
                    .original_evaluated_next_use(snapshot, Action::Readback)
                    .await?;
                (original.receipt().clone(), original.attestation().clone())
            }
            _ => return Err(Error::WrongScope),
        };
        if &receipt != expected {
            return Err(Error::WrongScope);
        }
        Ok(signature)
    }
}
