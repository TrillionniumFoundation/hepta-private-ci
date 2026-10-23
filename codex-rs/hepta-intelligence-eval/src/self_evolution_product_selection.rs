//! The original product qualification spine at the selection boundary.
use super::*;

/// The same independent evaluator binds actual candidate and predecessor bytes
/// to its sealed product qualification; a candidate ID alone is insufficient.
pub fn product_candidate_binding_payload_v1(
    request: &SelfEvolutionSelectionRequestV1,
    qualification: &ProductQualificationReceiptV1,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    qualification
        .validate_integrity()
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    if qualification.candidate_id != request.candidate_id {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let mut bytes = b"hepta.intelligence-eval.product-candidate-binding.v1\0".to_vec();
    for id in [
        &request.selection_id,
        &request.predecessor_id,
        &request.candidate_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(&request.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    for digest in [
        request.predecessor_artifact_digest,
        request.candidate_artifact_digest,
        qualification.evidence_digest,
        qualification.publication_digest,
        qualification.temporal_execution_digest,
        qualification.dataset_digest,
        qualification.objective_digest,
        qualification.decision.trust_digest,
        qualification.decision.authentication_digest,
    ] {
        require_digest(digest)?;
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

/// Prepare selection only from a genuinely sealed, durably published product
/// qualification plus the original fully bound signed documents and ledger.
/// The original comparator is used for exact verification, never as a substitute
/// for runner-derived metrics or the runner's durable evidence sink.
#[allow(clippy::too_many_arguments)]
pub fn prepare_self_evolution_product_selection_v1(
    qualification: &ProductQualificationReceiptV1,
    candidate_binding_evidence: &SignedLearningEvidenceV1,
    policy: &SelfEvolutionSelectionPolicyV1,
    request: SelfEvolutionSelectionRequestV1,
    evaluation_bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evaluation_evidence: &SignedEvaluationEvidenceV1,
    longitudinal_time: &LongitudinalTimeEvidenceV1,
    dataset_receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<PreparedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    qualification
        .validate_integrity()
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    if qualification.claim_scope != crate::EvaluationClaimScopeV1::SystemLongitudinal
        || qualification.candidate_id != request.candidate_id
        || qualification.generator != evaluation_bundle.generator
        || qualification.evaluator != evaluation_bundle.evaluator
        || qualification.objective_digest != evaluation_bundle.objective_digest
        || qualification.dataset_digest != evaluation_bundle.dataset_digest
        || qualification.snapshot_ids != evaluation_bundle.snapshot_ids
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let payload = product_candidate_binding_payload_v1(&request, qualification)?;
    let candidate_binding = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        candidate_binding_evidence,
        &payload,
        now,
    )?;
    if candidate_binding.principal() != &qualification.evaluator {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let mut prepared = prepare_self_evolution_selection_v1(
        policy,
        request,
        evaluation_bundle,
        metric_roles,
        evaluation_evidence,
        longitudinal_time,
        dataset_receipt,
        ledger_snapshot,
        verifier,
        now,
    )?;
    if prepared.receipt.evaluation_evidence_digest
        != qualification.decision.decision.evidence_digest
        || prepared.receipt.evaluation_authentication_digest
            != qualification.decision.authentication_digest
        || prepared.receipt.evaluation_trust_digest != qualification.decision.trust_digest
        || qualification.decision.decision.candidate_id != prepared.receipt.candidate_id
        || qualification.decision.decision.baseline_id != prepared.receipt.predecessor_id
        || qualification.decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let mut binding_digest = candidate_binding_evidence.signing_bytes();
    binding_digest.extend_from_slice(&candidate_binding_evidence.signature);
    prepared.receipt.product_qualification_binding = Some(ProductSelfEvolutionSelectionBindingV1 {
        qualification_evidence_digest: qualification.evidence_digest,
        qualification_publication_digest: qualification.publication_digest,
        temporal_execution_digest: qualification.temporal_execution_digest,
        candidate_binding_evidence_digest: Digest32::of_bytes(&binding_digest),
    });
    prepared.product_qualification = Some(Box::new(qualification.clone()));
    prepared.candidate_binding = Some(candidate_binding);
    Ok(prepared)
}

pub(super) fn validate_product_binding(
    receipt: &SelfEvolutionSelectionReceiptV1,
    qualification: &ProductQualificationReceiptV1,
) -> Result<(), SelfEvolutionSelectionError> {
    qualification
        .validate_integrity()
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    let binding = receipt
        .product_qualification_binding
        .as_ref()
        .ok_or(SelfEvolutionSelectionError::CanonicalQualificationRequired)?;
    if binding.qualification_evidence_digest != qualification.evidence_digest
        || binding.qualification_publication_digest != qualification.publication_digest
        || binding.temporal_execution_digest != qualification.temporal_execution_digest
        || binding.candidate_binding_evidence_digest.is_zero()
        || qualification.candidate_id != receipt.candidate_id
        || qualification.dataset_digest != receipt.dataset_digest
        || qualification.objective_digest != receipt.objective_digest
        || qualification.decision.trust_digest != receipt.evaluation_trust_digest
        || qualification.decision.authentication_digest != receipt.evaluation_authentication_digest
        || qualification.decision.decision.evidence_digest != receipt.evaluation_evidence_digest
        || qualification.decision.decision.baseline_id != receipt.predecessor_id
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    Ok(())
}
