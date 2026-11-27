//! Translate an original signed Cell qualification into an unsigned learning
//! observation. The original stage owners must still attest this exact receipt;
//! this adapter cannot sign, execute training, select or publish a generation.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::revalidate_product_qualification_v1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_types::Digest32;

use crate::CellEvaluationErrorV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;

#[derive(Debug, thiserror::Error)]
pub enum CellLearningEvaluationErrorV1 {
    #[error("learning evaluation binding: {0}")]
    Binding(&'static str),
    #[error("original evaluation has insufficient evidence for a learning decision")]
    InsufficientEvidence,
    #[error("learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("Cell evaluation: {0}")]
    Cell(#[from] CellEvaluationErrorV1),
    #[error("product qualification: {0}")]
    Product(#[from] ProductEvaluationError),
}

/// Revalidate original qualification evidence under the host's current trust
/// and clock, then bind its decision to the exact Training predecessor. No
/// caller-supplied disposition, candidate digest or new observation time is
/// accepted. Repeating this read at a later valid clock returns the same bytes.
///
/// Insufficient evidence remains an error without an Evaluation receipt; only
/// a complete, ineligible evaluation can advance the unchanged model as NoUpdate.
///
/// The observation time is the original evaluator signature's issue time.
/// Recovery may revalidate after the work deadline; this does not renew that
/// deadline or authorize a new stage. The iteration worker must obtain the
/// original Training and Evaluation receipt attestations and check their role
/// separation before advancing its protected checkpoint.
pub fn prepare_cell_learning_evaluation_v1(
    runner: &CellEvaluationRunnerV1<impl FinalHoldoutCasStoreV1>,
    snapshot: &LearningIterationSnapshotV1,
    receipt: &CellEvaluationReceiptV1,
    qualification: &CellEvaluationQualificationV1,
    request: &CellEvaluationQualificationRequestV1<'_>,
) -> Result<LearningIterationReceiptV1, CellLearningEvaluationErrorV1> {
    use CellLearningEvaluationErrorV1::Binding;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation) {
        return Err(Binding("Evaluation requires the original Training cut"));
    }
    let candidate = coordinator
        .candidate()
        .ok_or(Binding("trained candidate"))?;
    let candidate_digest = candidate.digest().map_err(LearningIterationError::from)?;
    let baseline = &snapshot.request.selected_bundle;
    let baseline_digest = baseline.digest().map_err(LearningIterationError::from)?;
    let training = snapshot
        .receipts
        .last()
        .ok_or(Binding("Training receipt"))?;
    let training_digest =
        Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(training)?);
    let comparison = qualification.comparison();
    let product = qualification.product();
    // The Product signature authenticates a decision, but does not prove that
    // the temporal result used the durable signed original execution owner.
    receipt.require_original_signed_execution(&product.evaluator)?;
    if comparison != receipt.plan().record()
        || product.temporal_execution_digest != receipt.temporal().execution_digest
        || comparison.learning_evaluation_profile
            != Some(snapshot.request.evaluation_profile.into_array())
        || candidate
            .training_lineage
            .as_ref()
            .map(|lineage| lineage.evaluation_profile)
            != Some(snapshot.request.evaluation_profile)
        || comparison.candidate.manifest.bundle_digest != candidate_digest.into_array()
        || comparison.fixed_expert.manifest.bundle_digest != baseline_digest.into_array()
        || comparison.comparison.candidate.training_receipt_digest != training_digest.into_array()
        || comparison.comparison.candidate.participant_id != candidate.artifact_id
        || comparison.comparison.fixed_expert.participant_id != baseline.artifact_id
        || product.candidate_id != candidate.artifact_id
        || product.decision.decision.baseline_id != baseline.artifact_id
        || product.generator.principal_id != snapshot.owners.trainer
        || product.evaluator.principal_id != snapshot.owners.evaluator
        || product.objective_digest != snapshot.request.envelope.objective_digest
        || product.decision.trust_digest != snapshot.owners.evidence_trust_digest
        || request.verifier.trust_digest() != snapshot.owners.evidence_trust_digest
    {
        return Err(Binding("original learning comparison"));
    }
    let bundle = runner.qualification_bundle(receipt, request.context)?;
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
    // This re-verifies the original keys, controller separation, scope,
    // revocation, expiry and exact signed payload. IDs or seals alone cannot
    // convert unknown or failed authentication into a NoUpdate decision.
    let decision = revalidate_product_qualification_v1(
        product,
        bundle,
        receipt.plan().product_plan().metric_roles.clone(),
        request.evidence,
        timing,
        request.verifier,
        request.now,
    )?;
    let disposition = match decision.decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
            LearningEvaluationDispositionV1::Qualified
        }
        IndependentEvaluationDispositionV1::Ineligible => LearningEvaluationDispositionV1::NoUpdate,
        IndependentEvaluationDispositionV1::InsufficientEvidence => {
            return Err(CellLearningEvaluationErrorV1::InsufficientEvidence);
        }
    };
    let prepared = LearningIterationReceiptV1 {
        operation_id: snapshot.request.operation_id.clone(),
        predecessor: snapshot.head_digest,
        actor_id: snapshot.owners.evaluator.clone(),
        evidence_digest: product.evidence_digest,
        observed_unix_seconds: request.evidence.evaluator_bundle.issued_at,
        observation: LearningIterationObservationV1::Evaluation {
            candidate_bundle: candidate_digest,
            evaluation_profile: snapshot.request.evaluation_profile,
            disposition,
        },
    };
    // Validate the historical observation without mutating the caller's
    // coordinator, claiming a new stage or restamping its original result.
    coordinator.record(prepared.clone(), prepared.observed_unix_seconds)?;
    Ok(prepared)
}
