//! Canonical Model data projection shared by the live owner and Root's
//! actual native B borrow. This data neither restores a native qualification
//! nor constructs a proposal writer, signer or publication capability.

use super::*;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
#[cfg(target_os = "linux")]
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
#[cfg(target_os = "linux")]
use serde::Deserialize;
#[cfg(target_os = "linux")]
use serde::Serialize;

#[cfg(target_os = "linux")]
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootQ24ModelProjectionDataV1 {
    pub(crate) scope: String,
    pub(crate) dataset_head: String,
    pub(crate) training_head: String,
    pub(crate) evaluation_head: String,
    pub(crate) candidate: String,
    pub(crate) owner_binding: String,
    pub(crate) material: String,
    pub(crate) proposal_binding: String,
}

#[cfg(target_os = "linux")]
pub(crate) fn project_original_root_model(
    actual: &crate::OriginalRootBEvaluationBorrowV1<'_>,
    scope: &FrozenLearningScopeV2,
    now: u64,
) -> Result<RootQ24ModelProjectionDataV1, Error> {
    let training = actual.training_snapshot();
    scope.validate_snapshot(training)?;
    let original = training
        .receipts
        .last()
        .ok_or(Error::Binding("original Root Training absent"))?;
    if original.observation.stage() != LearningIterationStageV1::Training {
        return Err(Error::Binding("actual Root Training cut required"));
    }
    let mut dataset =
        LearningIterationCoordinatorV1::new(training.request.clone(), training.owners.clone())?;
    for receipt in &training.receipts[..training.receipts.len() - 1] {
        dataset.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    if dataset.next_stage() != Some(LearningIterationStageV1::Training)
        || dataset.snapshot().head_digest != original.predecessor
    {
        return Err(Error::Binding("actual Root Dataset prefix differs"));
    }
    let request = actual.qualification_request();
    let inputs = CellQ24ModelProposalInputsV1 {
        training_cut: training,
        training_attestation: actual.training_attestation(),
        runner: actual.runner(),
        evaluation: actual.execution(),
        qualification: actual.qualification(),
        request: &request,
    };
    let projected = project_original_qualified_model(&inputs, now)?;
    if projected.cut.receipts.last() != Some(actual.receipt()) {
        return Err(Error::Binding("actual Root native B receipt differs"));
    }
    let owner = model_owner_binding(
        dataset.snapshot().head_digest,
        scope.binding(),
        original.evidence_digest,
    );
    Ok(RootQ24ModelProjectionDataV1 {
        scope: scope.binding().to_string(),
        dataset_head: dataset.snapshot().head_digest.to_string(),
        training_head: training.head_digest.to_string(),
        evaluation_head: projected.cut.head_digest.to_string(),
        candidate: projected.candidate.to_string(),
        owner_binding: owner.to_string(),
        material: projected.material.to_string(),
        proposal_binding: projected.key(owner).binding_digest.to_string(),
    })
}

pub(super) fn project_original_qualified_model<S: FinalHoldoutCasStoreV1>(
    inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    now: u64,
) -> Result<Admission, Error> {
    let mut coordinator =
        LearningIterationCoordinatorV1::from_snapshot(inputs.training_cut.clone())?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation) {
        return Err(Error::Binding("exact original Training extension"));
    }
    let cut = coordinator.snapshot();
    let training = cut
        .receipts
        .last()
        .ok_or(Error::Binding("original Training receipt"))?;
    let verified = inputs.request.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        inputs.training_attestation,
        &learning_iteration_receipt_signing_bytes_v1(training)?,
        now,
    )?;
    if verified.principal().principal_id != cut.owners.trainer
        || verified.principal() != &inputs.qualification.product().generator
        || verified.trust_digest() != cut.owners.evidence_trust_digest
        || verified.objective_digest() != cut.request.envelope.objective_digest
    {
        return Err(Error::Binding("original Training signer"));
    }
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("trained candidate"))?;
    let comparison = inputs.evaluation.plan().record();
    for (bundle, manifest) in [
        (candidate, &comparison.candidate.manifest),
        (
            &cut.request.selected_bundle,
            &comparison.fixed_expert.manifest,
        ),
    ] {
        crate::cell_composed_q24::validate_manifest(bundle, manifest)
            .map_err(|_| Error::Binding("complete Q24 generation manifest"))?;
    }
    let candidate = candidate.digest().map_err(LearningIterationError::from)?;
    let timing = match &inputs.request.timing {
        ProductTimingEvidenceV1::Qualification => ProductTimingEvidenceV1::Qualification,
        ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros: *minimum_window_micros,
        },
    };
    let request = CellEvaluationQualificationRequestV1 {
        context: inputs.request.context,
        evidence: inputs.request.evidence,
        timing,
        verifier: inputs.request.verifier,
        now,
    };
    let evaluation = crate::prepare_cell_learning_evaluation_v1(
        inputs.runner,
        cut,
        inputs.evaluation,
        inputs.qualification,
        &request,
    )?;
    if !matches!(
        evaluation.observation,
        LearningIterationObservationV1::Evaluation {
            disposition: LearningEvaluationDispositionV1::Qualified,
            ..
        }
    ) {
        return Err(Error::Binding("NoUpdate has no model proposal"));
    }
    // Complete canonical manifest payloads, both evaluated journals and the
    // original training observation enter this record, not only a model name.
    let material = Digest32::of_parts(&[
        b"hepta.cell.q24.model-proposal-material.v1\0",
        training.evidence_digest.as_array(),
        &serde_json::to_vec(&comparison.candidate.manifest)
            .map_err(|_| Error::Binding("candidate manifest encoding"))?,
        &serde_json::to_vec(&comparison.fixed_expert.manifest)
            .map_err(|_| Error::Binding("fixed manifest encoding"))?,
        comparison.candidate.journal_cut.as_array(),
        comparison.fixed_expert.journal_cut.as_array(),
        inputs
            .evaluation
            .plan()
            .product_plan()
            .frozen_plan
            .plan_digest
            .as_array(),
        inputs.qualification.product().evidence_digest.as_array(),
    ]);
    coordinator.record(evaluation.clone(), evaluation.observed_unix_seconds)?;
    Ok(Admission {
        cut: coordinator.snapshot().clone(),
        candidate,
        material,
    })
}
