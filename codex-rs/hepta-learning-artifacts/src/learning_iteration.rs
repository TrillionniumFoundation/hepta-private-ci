//! Bounded, replayable learning coordination over existing owner receipts.
//!
//! The deployed bundle remains immutable. Agentd's opt-in owner authenticates
//! each observation and checkpoints before advancing. This authority-free core
//! consumes IterationEnvelopeV1 without changing the code-candidate ledger.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::CellBundleError;
use crate::CellCompatibilityBundleV1;
use crate::learning_iteration_digest::initial_digest;
use crate::learning_iteration_digest::receipt_digest;
use crate::learning_iteration_types::*;

const MAX_DATASET_ROWS: u32 = 1_000_000;
const MAX_DATASET_BYTES: u64 = 1 << 30;
const MAX_TRAINING_STEPS: u64 = 1_000_000;
const MAX_TRAINING_MILLISECONDS: u64 = 86_400_000;
const MAX_ARTIFACT_BYTES: u64 = 16 << 30;
const STAGES: [LearningIterationStageV1; 7] = [
    LearningIterationStageV1::Experience,
    LearningIterationStageV1::Dataset,
    LearningIterationStageV1::Training,
    LearningIterationStageV1::Evaluation,
    LearningIterationStageV1::Proposal,
    LearningIterationStageV1::Selection,
    LearningIterationStageV1::NextUse,
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningIterationError {
    InvalidEnvelope(String),
    InvalidBudget,
    EmptyEvidence,
    OwnerConflict,
    WrongOwner,
    WrongOperation,
    WrongStage,
    StalePredecessor,
    DeadlineExceeded,
    InvalidTimestamp,
    ContextMismatch,
    CapacityExceeded,
    Bundle(CellBundleError),
    SnapshotMismatch,
}
impl fmt::Display for LearningIterationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for LearningIterationError {}
impl From<CellBundleError> for LearningIterationError {
    fn from(error: CellBundleError) -> Self {
        Self::Bundle(error)
    }
}

#[derive(Clone, Debug)]
pub struct LearningIterationCoordinatorV1 {
    snapshot: LearningIterationSnapshotV1,
}

impl LearningIterationCoordinatorV1 {
    pub fn new(
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
    ) -> Result<Self, LearningIterationError> {
        request
            .envelope
            .validate()
            .map_err(LearningIterationError::InvalidEnvelope)?;
        request.selected_bundle.digest()?;
        if request.completed_task_receipt.is_zero()
            || request.selected_artifact_digest.is_zero()
            || owners.evidence_trust_digest.is_zero()
        {
            return Err(LearningIterationError::EmptyEvidence);
        }
        let b = &request.budget;
        if !(1..=MAX_DATASET_ROWS).contains(&b.maximum_dataset_rows)
            || !(1..=MAX_DATASET_BYTES).contains(&b.maximum_dataset_bytes)
            || !(1..=MAX_TRAINING_STEPS).contains(&b.maximum_training_steps)
            || !(1..=MAX_TRAINING_MILLISECONDS).contains(&b.maximum_training_milliseconds)
            || !(1..=MAX_ARTIFACT_BYTES).contains(&b.maximum_artifact_bytes)
        {
            return Err(LearningIterationError::InvalidBudget);
        }
        if owners.trainer == owners.evaluator
            || owners.trainer == owners.selector
            || owners.evaluator == owners.selector
            || owners.next_use_observer == owners.trainer
            || owners.next_use_observer == owners.selector
        {
            return Err(LearningIterationError::OwnerConflict);
        }
        let head_digest = initial_digest(&request, &owners)?;
        Ok(Self {
            snapshot: LearningIterationSnapshotV1 {
                request,
                owners,
                receipts: Vec::new(),
                head_digest,
            },
        })
    }

    /// The durable owner must additionally authenticate the current head in
    /// its independent rollback domain; replay alone cannot detect truncation.
    pub fn from_snapshot(
        snapshot: LearningIterationSnapshotV1,
    ) -> Result<Self, LearningIterationError> {
        if snapshot.receipts.len() > STAGES.len() {
            return Err(LearningIterationError::CapacityExceeded);
        }
        let mut coordinator = Self::new(snapshot.request.clone(), snapshot.owners.clone())?;
        for receipt in &snapshot.receipts {
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        if coordinator.snapshot != snapshot {
            return Err(LearningIterationError::SnapshotMismatch);
        }
        Ok(coordinator)
    }

    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub fn disposition(&self) -> LearningIterationDispositionV1 {
        if matches!(
            self.snapshot
                .receipts
                .last()
                .map(|receipt| &receipt.observation),
            Some(
                LearningIterationObservationV1::NextUse { .. }
                    | LearningIterationObservationV1::RetainedModelNextUse { .. }
            )
        ) {
            return LearningIterationDispositionV1::UsedByNextTask;
        }
        if self.snapshot.receipts.iter().any(|receipt| {
            matches!(
                receipt.observation,
                LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::NoUpdate,
                    ..
                } | LearningIterationObservationV1::Proposal {
                    disposition: LearningProposalDispositionV1::NoAdmissibleUpdate,
                    ..
                }
            )
        }) {
            LearningIterationDispositionV1::NoUpdate
        } else {
            LearningIterationDispositionV1::InProgress
        }
    }

    /// A no-update decision still requires independent selection and actual
    /// next-task use. A rejected trained candidate is never submitted as a
    /// generator's distinct NoAdmissibleUpdate proposal.
    pub fn next_stage(&self) -> Option<LearningIterationStageV1> {
        match self
            .snapshot
            .receipts
            .last()
            .map(|receipt| &receipt.observation)
        {
            None => Some(LearningIterationStageV1::Experience),
            Some(LearningIterationObservationV1::Experience { .. }) => {
                Some(LearningIterationStageV1::Dataset)
            }
            Some(LearningIterationObservationV1::Dataset { .. }) => {
                Some(LearningIterationStageV1::Training)
            }
            Some(LearningIterationObservationV1::Training { .. }) => {
                Some(LearningIterationStageV1::Evaluation)
            }
            Some(LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::Qualified,
                ..
            }) => Some(LearningIterationStageV1::Proposal),
            Some(LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            })
            | Some(LearningIterationObservationV1::Proposal { .. }) => {
                Some(LearningIterationStageV1::Selection)
            }
            Some(LearningIterationObservationV1::Selection { .. }) => {
                Some(LearningIterationStageV1::NextUse)
            }
            Some(
                LearningIterationObservationV1::NextUse { .. }
                | LearningIterationObservationV1::RetainedModelNextUse { .. },
            ) => None,
        }
    }

    /// The evaluated decision's bundle, not an adoption grant. NoUpdate keeps
    /// the exact deployed bundle; an update requires the anchored proposal.
    pub fn next_task_bundle(&self) -> Option<&CellCompatibilityBundleV1> {
        self.snapshot
            .receipts
            .iter()
            .rev()
            .find_map(|receipt| match &receipt.observation {
                LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::NoUpdate,
                    ..
                }
                | LearningIterationObservationV1::Proposal {
                    disposition: LearningProposalDispositionV1::NoAdmissibleUpdate,
                    ..
                } => Some(&self.snapshot.request.selected_bundle),
                LearningIterationObservationV1::Proposal {
                    disposition: LearningProposalDispositionV1::UpdateCandidates,
                    ..
                } => self.candidate(),
                LearningIterationObservationV1::Experience { .. }
                | LearningIterationObservationV1::Dataset { .. }
                | LearningIterationObservationV1::Training { .. }
                | LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::Qualified,
                    ..
                }
                | LearningIterationObservationV1::Selection { .. }
                | LearningIterationObservationV1::NextUse { .. }
                | LearningIterationObservationV1::RetainedModelNextUse { .. } => None,
            })
    }

    pub fn candidate(&self) -> Option<&CellCompatibilityBundleV1> {
        match self
            .snapshot
            .receipts
            .get(2)
            .map(|receipt| &receipt.observation)
        {
            Some(LearningIterationObservationV1::Training { candidate, .. }) => {
                Some(candidate.as_ref())
            }
            _ => None,
        }
    }

    /// Failure leaves the entire checkpoint unchanged. Exact replay emits no
    /// new work and stays readable after expiry.
    pub fn record(
        &mut self,
        receipt: LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> Result<Digest32, LearningIterationError> {
        if self.snapshot.receipts.last() == Some(&receipt) {
            return Ok(self.snapshot.head_digest);
        }
        let stage = self
            .next_stage()
            .ok_or(LearningIterationError::WrongStage)?;
        if stage != receipt.observation.stage() {
            return Err(LearningIterationError::WrongStage);
        }
        if receipt.operation_id != self.snapshot.request.operation_id {
            return Err(LearningIterationError::WrongOperation);
        }
        if &receipt.actor_id != self.snapshot.owners.owner(stage) {
            return Err(LearningIterationError::WrongOwner);
        }
        if receipt.predecessor != self.snapshot.head_digest {
            return Err(LearningIterationError::StalePredecessor);
        }
        if now_unix_seconds >= self.snapshot.request.envelope.expiry_unix_seconds {
            return Err(LearningIterationError::DeadlineExceeded);
        }
        if receipt.observed_unix_seconds == 0
            || receipt.observed_unix_seconds > now_unix_seconds
            || self
                .snapshot
                .receipts
                .last()
                .is_some_and(|last| last.observed_unix_seconds > receipt.observed_unix_seconds)
        {
            return Err(LearningIterationError::InvalidTimestamp);
        }
        if receipt.evidence_digest.is_zero() {
            return Err(LearningIterationError::EmptyEvidence);
        }
        self.validate_observation(&receipt.observation)?;
        let next_head = receipt_digest(&receipt)?;
        self.snapshot.receipts.push(receipt);
        self.snapshot.head_digest = next_head;
        Ok(next_head)
    }

    fn validate_observation(
        &self,
        observation: &LearningIterationObservationV1,
    ) -> Result<(), LearningIterationError> {
        let request = &self.snapshot.request;
        let b = &request.budget;
        let candidate_digest = self
            .candidate()
            .map(CellCompatibilityBundleV1::digest)
            .transpose()?;
        let next_task_bundle = self
            .next_task_bundle()
            .map(CellCompatibilityBundleV1::digest)
            .transpose()?;
        let valid = match observation {
            LearningIterationObservationV1::Experience {
                episode_digest,
                completed_task_receipt,
            } => {
                !episode_digest.is_zero()
                    && *completed_task_receipt == request.completed_task_receipt
            }
            LearningIterationObservationV1::Dataset {
                snapshot_digest,
                episode_digest,
                withdrawal_frontier,
                rows,
                bytes,
            } => {
                let source = self
                    .snapshot
                    .receipts
                    .first()
                    .map(|receipt| &receipt.observation);
                !snapshot_digest.is_zero()
                    && !withdrawal_frontier.is_zero()
                    && (1..=b.maximum_dataset_rows).contains(rows)
                    && (1..=b.maximum_dataset_bytes).contains(bytes)
                    && matches!(source, Some(LearningIterationObservationV1::Experience { episode_digest: expected, .. }) if episode_digest == expected)
            }
            LearningIterationObservationV1::Training {
                candidate,
                steps,
                milliseconds,
                artifact_bytes,
            } => {
                candidate.digest()?;
                let source = self
                    .snapshot
                    .receipts
                    .get(1)
                    .map(|receipt| &receipt.observation);
                let selected = request.selected_bundle.digest()?;
                candidate.artifact_id != request.selected_bundle.artifact_id
                    && request.selected_bundle.generation.next().ok() == Some(candidate.generation)
                    && candidate.rollback_predecessor == Some(selected)
                    && candidate.training_lineage.as_ref().is_some_and(|lineage| {
                        lineage.source_bundle == selected
                            && matches!(source, Some(LearningIterationObservationV1::Dataset { snapshot_digest, .. }) if lineage.dataset == *snapshot_digest)
                    })
                    && (1..=b.maximum_training_steps).contains(steps)
                    && (1..=b.maximum_training_milliseconds).contains(milliseconds)
                    && (1..=b.maximum_artifact_bytes).contains(artifact_bytes)
            }
            LearningIterationObservationV1::Evaluation {
                candidate_bundle,
                evaluation_profile,
                ..
            } => {
                candidate_digest == Some(*candidate_bundle)
                    && self
                        .candidate()
                        .and_then(|candidate| candidate.training_lineage.as_ref())
                        .is_some_and(|lineage| lineage.evaluation_profile == *evaluation_profile)
            }
            LearningIterationObservationV1::Proposal {
                candidate_bundle,
                proposal_id,
                composition_digest,
                ..
            } => {
                candidate_digest == Some(*candidate_bundle)
                    && proposal_id == &request.operation_id
                    && !composition_digest.is_zero()
            }
            LearningIterationObservationV1::Selection {
                candidate_bundle,
                selection_digest,
            } => next_task_bundle == Some(*candidate_bundle) && !selection_digest.is_zero(),
            LearningIterationObservationV1::NextUse {
                candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt,
            } => {
                next_task_bundle == Some(*candidate_bundle)
                    && candidate_digest == Some(*candidate_bundle)
                    && state_partition.principal_id == request.principal_id
                    && state_partition.agent_id == request.agent_id
                    && state_partition.cell_id == request.cell_id
                    && state_partition.run_id != request.source_run_id
                    && !checkpoint_digest.is_zero()
                    && matches!(self.snapshot.receipts.last().map(|receipt| &receipt.observation),
                        Some(LearningIterationObservationV1::Selection { selection_digest: expected, .. }) if selection_digest == expected)
                    && !committed_step_receipt.is_zero()
                    && !state_cutover_receipt.is_zero()
            }
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication,
            } => {
                next_task_bundle == Some(*retained_bundle)
                    && *retained_bundle == request.selected_bundle.digest()?
                    && state_partition.principal_id == request.principal_id
                    && state_partition.agent_id == request.agent_id
                    && state_partition.cell_id == request.cell_id
                    && state_partition.run_id != request.source_run_id
                    && !checkpoint_digest.is_zero()
                    && matches!(self.snapshot.receipts.last().map(|receipt| &receipt.observation),
                        Some(LearningIterationObservationV1::Selection { selection_digest: expected, .. }) if selection_digest == expected)
                    && !committed_step_receipt.is_zero()
                    && !task_owner_publication.is_zero()
            }
        };
        if !valid {
            return Err(LearningIterationError::ContextMismatch);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "learning_iteration_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "learning_iteration_retained_tests.rs"]
mod retained_tests;
