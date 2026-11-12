//! Fixed original Evaluation context and opaque command result.
//! No constructor accepts future B rows, Product declarations or a result.

use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCellEvaluationPanelErrorV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationQualificationErrorV1;
use crate::OriginalCellEvaluationReceiptErrorV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellEvaluationCommandErrorV1 {
    #[error("original Evaluation context: {0}")]
    Binding(&'static str),
    #[error("original Evaluation channel is unavailable")]
    Unavailable,
    #[error("original Evaluation effect is uncertain; read the original operation")]
    CommitUncertain,
    #[error("original Evaluation is readback only")]
    ReadbackRequired,
    #[error("original Evaluation owner is occupied")]
    Busy,
    #[error("original Evaluation publication is missing")]
    Missing,
    #[error("original Evaluation publication is pending")]
    Pending,
    #[error("original Evaluation predecessors are unavailable")]
    PredecessorUnavailable,
    #[error("original Evaluation work deadline expired")]
    DeadlineExceeded,
    #[error("original Evaluation transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Evaluation receipt: {0}")]
    Receipt(#[from] OriginalCellEvaluationReceiptErrorV1),
    #[error("original Evaluation panel: {0}")]
    Panel(#[from] OriginalCellEvaluationPanelErrorV1),
    #[error("original Qualification: {0}")]
    Qualification(#[from] OriginalCellEvaluationQualificationErrorV1),
    #[error("original owner journal: {0}")]
    Journal(#[from] LearningOriginalOwnerErrorV1),
    #[error("original Evaluation iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Evaluation evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Evaluation snapshot: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original Evaluation encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCellEvaluationCommandErrorV1;

#[derive(Clone)]
pub(super) struct Context {
    pub(super) training: LearningIterationSnapshotV1,
    pub(super) scope: FrozenLearningScopeV2,
    pub(super) registration: OriginalCellEvaluationPanelRegistrationV1,
    pub(super) training_evidence: SignedLearningEvidenceV1,
    pub(super) verifier: LearningEvidenceVerifierV1,
}

impl Context {
    pub(super) fn from_original_training(
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        verifier: LearningEvidenceVerifierV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Self, Error> {
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
            || coordinator.snapshot().receipts.len() != 2
        {
            return Err(Error::Binding("original Dataset before actual Candidate"));
        }
        coordinator.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        Self::from_checkpoint(
            coordinator.snapshot().clone(),
            scope,
            registration,
            training.attestation().clone(),
            verifier,
        )
    }

    pub(super) fn from_checkpoint(
        training: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        training_evidence: SignedLearningEvidenceV1,
        verifier: LearningEvidenceVerifierV1,
    ) -> Result<Self, Error> {
        let original = Self {
            training,
            scope,
            registration,
            training_evidence,
            verifier,
        };
        original.authenticate(super::now()?)?;
        Ok(original)
    }

    pub(super) fn authenticate(&self, current: u64) -> Result<VerifiedLearningEvidenceV1, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(self.training.clone())?;
        self.scope.validate_snapshot(&self.training)?;
        let receipt = self
            .training
            .receipts
            .last()
            .ok_or(Error::Binding("original Training cut"))?;
        if self.training.receipts.len() != 3
            || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
            || !matches!(
                &receipt.observation,
                LearningIterationObservationV1::Training { .. }
            )
            || self.training.request.evaluation_profile != self.registration.evaluation_profile()
            || self.training.owners.evidence_trust_digest != self.verifier.trust_digest()
            || self.training.request.envelope.objective_digest != self.verifier.objective_digest()
            || receipt.actor_id != self.training.owners.trainer
            || receipt.observed_unix_seconds != self.training_evidence.issued_at
            || receipt.observed_unix_seconds > current
        {
            return Err(Error::Binding(
                "actual Candidate, nonempty original panel and full Training",
            ));
        }
        let training = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &self.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            current,
        )?;
        if training.principal().principal_id != self.training.owners.trainer {
            return Err(Error::Binding("original Generator identity"));
        }
        Ok(training)
    }

    pub(super) fn binding(&self, current: u64) -> Result<Digest32, Error> {
        self.authenticate(current)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-cell-evaluation-command.v1\0",
            &encode_original_owner_snapshot_v1(&self.training)?,
            self.scope.binding().as_array(),
            self.registration.evaluation_profile().as_array(),
            self.verifier.trust_digest().as_array(),
            self.verifier.scope_digest().as_array(),
            self.verifier.objective_digest().as_array(),
            &self.training_evidence.signing_bytes(),
            &self.training_evidence.signature,
        ]))
    }

    pub(super) fn initial(&self) -> Result<LearningIterationSnapshotV1, Error> {
        Ok(LearningIterationCoordinatorV1::new(
            self.training.request.clone(),
            self.training.owners.clone(),
        )?
        .snapshot()
        .clone())
    }
}

/// This is the result of one original host read. It grants no model creation,
/// version adoption, publication or FinalUse authority and is not a lease.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellEvaluationCommandReceiptV1 {
    pub(super) snapshot: LearningIterationSnapshotV1,
    pub(super) receipt: LearningIterationReceiptV1,
    pub(super) attestation: SignedLearningEvidenceV1,
    pub(super) training_evidence: SignedLearningEvidenceV1,
}
impl OriginalCellEvaluationCommandReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
    pub fn training_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.training_evidence
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub(super) fn authenticate_receipt(
    context: &Context,
    receipt: LearningIterationReceiptV1,
    signed: SignedLearningEvidenceV1,
    current: u64,
) -> Result<OriginalCellEvaluationCommandReceiptV1, Error> {
    let generator = context.authenticate(current)?;
    let original = LearningIterationCoordinatorV1::from_snapshot(context.training.clone())?;
    let candidate = original
        .candidate()
        .ok_or(Error::Binding("actual trained Candidate"))?
        .digest()
        .map_err(LearningIterationError::from)?;
    if !matches!(&receipt.observation,
        LearningIterationObservationV1::Evaluation { candidate_bundle, evaluation_profile, .. }
        if *candidate_bundle == candidate
            && *evaluation_profile == context.registration.evaluation_profile())
        || receipt.operation_id != context.training.request.operation_id
        || receipt.predecessor != context.training.head_digest
        || receipt.actor_id != context.training.owners.evaluator
        || receipt.observed_unix_seconds > signed.issued_at
        || receipt.observed_unix_seconds > current
    {
        return Err(Error::Binding(
            "original Evaluation over the exact Candidate and panel",
        ));
    }
    let evaluator = context.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &learning_iteration_receipt_signing_bytes_v1(&receipt)?,
        current,
    )?;
    if evaluator.principal().principal_id != context.training.owners.evaluator {
        return Err(Error::Binding("original independent Evaluator"));
    }
    verify_signed_actor_separation(&generator, &evaluator, current)?;
    let mut coordinator = original;
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    context.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(OriginalCellEvaluationCommandReceiptV1 {
        snapshot: coordinator.snapshot().clone(),
        receipt,
        attestation: signed,
        training_evidence: context.training_evidence.clone(),
    })
}
