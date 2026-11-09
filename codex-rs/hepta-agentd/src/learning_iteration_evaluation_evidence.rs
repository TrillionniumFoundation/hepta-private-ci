//! Read original Evaluation attestations after validating the Cell qualification.
//! This path neither issues evidence nor executes a holdout.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::LearningIterationEvidenceClientV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;
use crate::CellLearningEvaluationErrorV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::prepare_cell_learning_evaluation_v1;

/// Original sealed inputs and current host trust. The clock is sampled here.
pub struct CellLearningEvaluationReadbackRequestV1<'a, S> {
    pub runner: &'a CellEvaluationRunnerV1<S>,
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub evaluation: &'a CellEvaluationReceiptV1,
    pub qualification: &'a CellEvaluationQualificationV1,
    pub context: &'a ProductQualificationContextV1,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub timing: ProductTimingEvidenceV1<'a>,
    pub verifier: &'a LearningEvidenceVerifierV1,
}

/// Authenticated at one clock observation. The ordinary worker still re-reads
/// current evidence before recording the receipt or restoring a history.
#[derive(Clone, Debug)]
pub struct AuthenticatedCellLearningEvaluationV1 {
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    verified_at_unix_seconds: u64,
}

impl AuthenticatedCellLearningEvaluationV1 {
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
    pub fn verified_at_unix_seconds(&self) -> u64 {
        self.verified_at_unix_seconds
    }
}

#[derive(Debug, thiserror::Error)]
pub enum CellLearningEvaluationReadbackErrorV1 {
    #[error("Cell evaluation preparation: {0}")]
    Preparation(#[from] CellLearningEvaluationErrorV1),
    #[error("original learning evidence: {0}")]
    Evidence(#[from] LearningIterationRuntimeErrorV1),
}

/// Read the original trainer and evaluator receipts on their already admitted
/// connections. Only receipt digests cross the wire; this never asks an owner
/// to sign arbitrary data. Missing, expired or uncertain evidence is an error,
/// including when the independently evaluated disposition is NoUpdate.
pub async fn read_cell_learning_evaluation_v1(
    request: CellLearningEvaluationReadbackRequestV1<'_, impl FinalHoldoutCasStoreV1>,
    trainer: &LearningIterationEvidenceClientV1,
    evaluator: &LearningIterationEvidenceClientV1,
) -> Result<AuthenticatedCellLearningEvaluationV1, CellLearningEvaluationReadbackErrorV1> {
    let prepare = |now| {
        let timing = match &request.timing {
            ProductTimingEvidenceV1::Qualification => ProductTimingEvidenceV1::Qualification,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: *minimum_window_micros,
            },
        };
        prepare_cell_learning_evaluation_v1(
            request.runner,
            request.snapshot,
            request.evaluation,
            request.qualification,
            &CellEvaluationQualificationRequestV1 {
                context: request.context,
                evidence: request.evidence,
                timing,
                verifier: request.verifier,
                now,
            },
        )
    };
    let receipt = prepare(now_unix_seconds()?)?;
    let training = request
        .snapshot
        .receipts
        .last()
        .filter(|receipt| receipt.observation.stage() == LearningIterationStageV1::Training)
        .ok_or(LearningIterationRuntimeErrorV1::WrongScope)?;
    let training_attestation = trainer.readback(request.snapshot, training).await?;
    let attestation = evaluator.readback(request.snapshot, &receipt).await?;
    let now = now_unix_seconds()?;
    // Revalidate after both waits without repeating the experiment or timestamp.
    if prepare(now)? != receipt {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    let generator = request
        .verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &training_attestation,
            &learning_iteration_receipt_signing_bytes_v1(training)
                .map_err(LearningIterationRuntimeErrorV1::from)?,
            now,
        )
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    let observer = request
        .verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &attestation,
            &learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(LearningIterationRuntimeErrorV1::from)?,
            now,
        )
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    if generator.principal() != &request.context.generator
        || observer.principal() != &request.context.evaluator
        || generator.principal().principal_id != request.snapshot.owners.trainer
        || observer.principal().principal_id != request.snapshot.owners.evaluator
    {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    verify_signed_actor_separation(&generator, &observer, now)
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    Ok(AuthenticatedCellLearningEvaluationV1 {
        receipt,
        attestation,
        verified_at_unix_seconds: now,
    })
}

fn now_unix_seconds() -> Result<u64, LearningIterationRuntimeErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| LearningIterationRuntimeErrorV1::OwnerUnavailable("current evaluation clock"))
}
