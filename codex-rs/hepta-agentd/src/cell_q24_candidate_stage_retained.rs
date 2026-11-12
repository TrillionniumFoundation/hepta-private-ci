//! The complete evaluated NoUpdate continuation is distinct from the legacy
//! TrainingNoUpdate lane. Its only channels were admitted at initial handoff.
//! A four-cut result selects this protocol; actual original owners admit work.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;

use super::super::auth;
use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1 as Owners;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitCompletionReadinessClientV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitNextUseCommandClientV1;
use crate::OriginalCircuitNextUseCommandReceiptV1;
use crate::OriginalCircuitRetainedVersionClientV1;
use crate::OriginalCircuitSelectionCommandClientV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;

#[path = "cell_q24_candidate_stage_retained_readback.rs"]
mod readback;
#[path = "cell_q24_candidate_stage_retained_execute.rs"]
mod execution;

struct OriginalPins {
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    evaluation: OriginalCellEvaluationCommandReceiptV1,
    context: OriginalCircuitEvaluatedRetentionContextV1,
}

pub(super) struct EvaluatedContinuation {
    pins: Option<OriginalPins>,
    version: Option<OriginalCircuitRetainedVersionClientV1>,
    selector_initial: Option<HostAuthorityPeerChannel>,
    selector: Option<OriginalCircuitSelectionCommandClientV1>,
    next_use_initial: Option<HostAuthorityPeerChannel>,
    next_use: Option<OriginalCircuitNextUseCommandClientV1>,
    readiness_initial: Option<HostAuthorityPeerChannel>,
    readiness: Option<OriginalCircuitCompletionReadinessClientV1>,
    selection: Option<OriginalCircuitSelectionCommandReceiptV1>,
    completion: Option<OriginalCircuitNextUseCommandReceiptV1>,
    failed: bool,
}

impl EvaluatedContinuation {
    pub(super) fn new() -> Self {
        Self {
            pins: None, version: None, selector_initial: None, selector: None,
            next_use_initial: None, next_use: None, readiness_initial: None,
            readiness: None, selection: None, completion: None, failed: false,
        }
    }

    async fn refresh(&mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1) -> Result<(), Error> {
        let expected = evaluated_prefix(snapshot)?;
        let started = auth::now()?;
        let evaluation = owners.read_original_evaluation(snapshot).await?;
        if evaluation.snapshot() != &expected {
            return Err(Error::WrongScope);
        }
        let (dataset, training) = {
            let common = owners.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
            (common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone(),
             common.original_training.as_ref().ok_or(Error::CommitUncertain)?.clone())
        };
        // Only the first fresh handoff can establish new-work eligibility.
        // Later equality checks use the read-only constructor and leave the
        // original stored capability and all execution checks unchanged.
        let context = match (owners.common.origin, self.pins.is_some()) {
            (Origin::Fresh, false) => OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
                owners.common.material.scope.clone(), owners.common.material.verifier.clone(), &training, &evaluation),
            _ => OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
                owners.common.material.scope.clone(), owners.common.material.verifier.clone(), &training, &evaluation),
        }.map_err(|_| Error::OwnerUnavailable("complete original evaluated NoUpdate predecessors"))?;
        let fresh = auth::require_material(&owners.common.material, owners.common.initial_binding)?;
        auth::require_clock(started, fresh)?;
        owners.require_live_deadline()?;
        if let Some(prior) = &self.pins {
            if prior.dataset != dataset || prior.training != training || prior.evaluation != evaluation
                || prior.context.receipt_context_binding() != context.receipt_context_binding() {
                return Err(Error::CommitUncertain);
            }
        } else {
            let channels = owners.common.continuation.try_lock().map_err(|_| Error::QueueFull)?
                .take_evaluated_retained_channels(&owners.common, &context)?;
            let version = match owners.common.origin {
                Origin::Fresh => OriginalCircuitRetainedVersionClientV1::bind_original_evaluated_stage_channel(
                    channels.version, &owners.common.material, &dataset, &training, &evaluation),
                Origin::Recovered => OriginalCircuitRetainedVersionClientV1::recover_original_evaluated_stage_channel(
                    channels.version, &owners.common.material, &dataset, &training, &evaluation),
            }.map_err(|_| Error::OwnerUnavailable("same original evaluated Version channel"))?;
            self.version = Some(version);
            self.selector_initial = Some(channels.selector);
            self.next_use_initial = Some(channels.next_use);
            self.readiness_initial = Some(channels.readiness);
            self.pins = Some(OriginalPins { dataset, training, evaluation, context });
        }
        Ok(())
    }

    fn bind_selector(&mut self, owners: &Owners) -> Result<(), Error> {
        if self.selector.is_none() {
            let pins = self.pins.as_ref().ok_or(Error::CommitUncertain)?;
            self.selector = Some(OriginalCircuitSelectionCommandClientV1::bind_original_evaluated_stage_channel(
                self.selector_initial.take().ok_or(Error::CommitUncertain)?, &owners.common.material,
                &pins.dataset, &pins.training, &pins.evaluation, owners.common.origin,
            ).map_err(auth::selector_failure)?);
        }
        Ok(())
    }

    fn bind_next_use(&mut self, owners: &Owners) -> Result<(), Error> {
        let pins = self.pins.as_ref().ok_or(Error::CommitUncertain)?;
        let selection = self.selection.as_ref().ok_or(Error::CommitUncertain)?;
        if self.next_use.is_none() {
            self.next_use = Some(OriginalCircuitNextUseCommandClientV1::bind_original_evaluated_stage_channel(
                self.next_use_initial.take().ok_or(Error::CommitUncertain)?, &owners.common.material,
                &pins.dataset, selection, owners.common.origin,
            ).map_err(auth::next_use_failure)?);
        }
        if self.readiness.is_none() {
            let original = selection.evaluated_receipt().map_err(auth::selector_failure)?;
            self.readiness = Some(OriginalCircuitCompletionReadinessClientV1::bind_original_evaluated_stage_channel(
                self.readiness_initial.take().ok_or(Error::CommitUncertain)?, &owners.common.material,
                &pins.dataset, &original,
            ).map_err(|_| Error::OwnerUnavailable("same original evaluated C readiness channel"))?);
        }
        Ok(())
    }
}

pub(super) fn is_evaluated_no_update(snapshot: &LearningIterationSnapshotV1) -> bool {
    matches!(snapshot.receipts.get(3).map(|receipt| &receipt.observation),
        Some(LearningIterationObservationV1::Evaluation { disposition: LearningEvaluationDispositionV1::NoUpdate, .. }))
}

fn evaluated_prefix(snapshot: &LearningIterationSnapshotV1) -> Result<LearningIterationSnapshotV1, Error> {
    let complete = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    if !is_evaluated_no_update(snapshot) || !(4..=6).contains(&snapshot.receipts.len())
        || snapshot.training_no_update_v2().is_some() {
        return Err(Error::WrongScope);
    }
    let mut original = LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for receipt in &snapshot.receipts[..4] {
        original.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    if original.next_stage() != Some(Stage::Selection) || original.candidate() != complete.candidate()
        || original.next_task_bundle() != Some(&snapshot.request.selected_bundle)
        || original.candidate().is_none_or(|candidate| candidate == &snapshot.request.selected_bundle) {
        return Err(Error::WrongScope);
    }
    let expected = match snapshot.receipts.len() { 4 => Some(Stage::Selection), 5 => Some(Stage::NextUse), _ => None };
    if complete.next_stage() != expected || complete.next_task_bundle() != Some(&snapshot.request.selected_bundle) {
        return Err(Error::WrongScope);
    }
    Ok(original.snapshot().clone())
}

impl Owners {
    /// Protocol selection only; all authority/current-owner checks occur at the
    /// actual effect edge. No Candidate Adopt path is admitted by this method.
    pub(crate) fn require_evaluated_retained_stage(snapshot: &LearningIterationSnapshotV1, stage: Stage) -> Result<(), Error> {
        evaluated_prefix(snapshot)?;
        if !matches!(stage, Stage::Selection | Stage::NextUse)
            || LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage() != Some(stage) {
            return Err(Error::WrongScope);
        }
        Ok(())
    }
}
