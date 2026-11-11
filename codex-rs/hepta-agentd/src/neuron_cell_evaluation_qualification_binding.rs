//! Fixed original custody, complete signature binding and pure revalidation.
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::product_evaluation_execution_key_v1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

pub(super) fn validate_config(
    config: &OriginalCellEvaluationQualificationConfigV1,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.training.clone())?;
    config.scope.validate_snapshot(&config.training)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || config.training.receipts.len() != 3
        || config.qualification_namespace.is_zero()
        || config.qualification_namespace == config.execution_namespace
        || config.training.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.training.request.envelope.objective_digest != config.verifier.objective_digest()
        || config.plan.product_plan().frozen_plan.claim_scope != EvaluationClaimScopeV1::Qualification
    {
        return Err(Error::Binding("original Qualification profile"));
    }
    let candidate = coordinator.candidate().ok_or(Error::Binding("original trained candidate"))?;
    let baseline = &config.training.request.selected_bundle;
    let candidate_digest = candidate.digest().map_err(LearningIterationError::from)?;
    let baseline_digest = baseline.digest().map_err(LearningIterationError::from)?;
    let original_training = training_receipt(config)?;
    let training_digest = Digest32::of_bytes(
        &learning_iteration_receipt_signing_bytes_v1(original_training)?,
    );
    let record = config.plan.record();
    let frozen = &config.plan.product_plan().frozen_plan;
    if record.learning_evaluation_profile != Some(config.training.request.evaluation_profile.into_array())
        || candidate.training_lineage.as_ref().map(|lineage| lineage.evaluation_profile)
            != Some(config.training.request.evaluation_profile)
        || record.candidate.manifest.bundle_digest != candidate_digest.into_array()
        || record.fixed_expert.manifest.bundle_digest != baseline_digest.into_array()
        || record.comparison.candidate.training_receipt_digest != training_digest.into_array()
        || record.comparison.candidate.participant_id != candidate.artifact_id
        || record.comparison.fixed_expert.participant_id != baseline.artifact_id
        || frozen.candidate_id != candidate.artifact_id
        || frozen.baseline_id != baseline.artifact_id
        || frozen.objective_digest != config.verifier.objective_digest()
        || config.context.generator.principal_id != config.training.owners.trainer
        || config.context.evaluator.principal_id != config.training.owners.evaluator
        || config.product_evidence.evaluator_bundle.issued_at < original_training.observed_unix_seconds
    {
        return Err(Error::Binding("original Qualification comparison"));
    }
    let execution = product_evaluation_execution_key_v1(
        config.plan.product_plan(), config.execution_namespace, &config.context.evaluator,
    )?;
    if &execution != config.execution_evidence.key() {
        return Err(Error::Binding("original Qualification execution identity"));
    }
    authenticate_fixed(config, now()?)?;
    let record = serde_json::to_vec(config.plan.record())
        .map_err(|_| Error::Binding("original Qualification comparison encoding"))?;
    let mut bytes = b"hepta.agentd.original-evaluation-qualification.v1\0".to_vec();
    for digest in [
        config.training.head_digest, config.scope.binding(),
        config.execution_namespace, config.qualification_namespace,
        execution.binding_digest, config.execution_evidence.record_digest(),
        config.verifier.trust_digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_bytes(&mut bytes, &record)?;
    push_principal(&mut bytes, &config.context.generator)?;
    push_principal(&mut bytes, &config.context.evaluator)?;
    bytes.extend_from_slice(&(config.context.retention_receipt_digests.len() as u64).to_be_bytes());
    for digest in &config.context.retention_receipt_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(config.context.unlearning_receipt_digest.as_array());
    for original in [
        &config.training_evidence,
        &config.product_evidence.generator_plan,
        &config.product_evidence.evaluator_bundle,
        config.execution_evidence.attestation(),
    ] {
        push_bytes(&mut bytes, &original.signing_bytes())?;
        bytes.extend_from_slice(&original.signature);
    }
    if bytes.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
        return Err(Error::Binding("original Qualification binding exceeds bound"));
    }
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.training.request.operation_id.clone(),
        binding_digest: Digest32::of_bytes(&bytes),
    })
}

pub(super) fn training_receipt(
    config: &OriginalCellEvaluationQualificationConfigV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    config.training.receipts.last().ok_or(Error::Binding("original Training cut"))
}

fn authenticate_fixed(
    config: &OriginalCellEvaluationQualificationConfigV1,
    current: u64,
) -> Result<(VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1), Error> {
    let training = config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &config.training_evidence,
        &learning_iteration_receipt_signing_bytes_v1(training_receipt(config)?)?,
        current,
    )?;
    let generator = config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &config.product_evidence.generator_plan,
        config.plan.product_plan().frozen_plan.plan_digest.as_array(),
        current,
    )?;
    let execution = OriginalProductEvaluationExecutionEvidenceV1::revalidate(
        &config.execution_evidence, &config.verifier, current,
    )?;
    if training.principal() != &config.context.generator
        || generator.principal() != training.principal()
        || generator.controller_id() != training.controller_id()
        || execution.principal() != &config.context.evaluator
    {
        return Err(Error::Binding("original Qualification role custody"));
    }
    verify_signed_actor_separation(&training, &execution, current)?;
    Ok((training, execution))
}

pub(super) fn authenticate(
    config: &OriginalCellEvaluationQualificationConfigV1,
    prepared: &Prepared,
    current: u64,
) -> Result<(), Error> {
    let (training, execution) = authenticate_fixed(config, current)?;
    let payload = evaluation_signing_payload_v2(
        &prepared.bundle, &config.plan.product_plan().metric_roles,
    ).map_err(ProductEvaluationError::from)?;
    let evaluator = config.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &config.product_evidence.evaluator_bundle,
        &payload,
        current,
    )?;
    if prepared.evaluation.plan() != &config.plan
        || prepared.bundle.generator != config.context.generator
        || prepared.bundle.evaluator != config.context.evaluator
        || evaluator.principal() != execution.principal()
        || evaluator.controller_id() != execution.controller_id()
    {
        return Err(Error::Binding("original Qualification Product and execution custody"));
    }
    verify_signed_actor_separation(&training, &evaluator, current)?;
    Ok(())
}

/// Canonical full public decision bytes; no seal is decoded or constructed here.
/// Time is deliberately absent: revalidation never restamps the original data.
pub(super) fn decision_bytes(
    key: &ProductEvaluationExecutionKeyV1,
    execution_digest: Digest32,
    decision: &SignedEvaluationDecisionV1,
) -> Result<Vec<u8>, Error> {
    if execution_digest.is_zero() || decision.decision.authority != AuthorityPosture::DENY_ALL
        || decision.decision.evidence_digest.is_zero()
        || decision.trust_digest.is_zero() || decision.authentication_digest.is_zero()
    {
        return Err(Error::Binding("original Qualification decision"));
    }
    let mut bytes = b"hepta.agentd.original-qualification-record.v1\0".to_vec();
    push_id(&mut bytes, &key.plan_id)?;
    for digest in [
        key.binding_digest, execution_digest, decision.decision.evidence_digest,
        decision.trust_digest, decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for id in [
        &decision.decision.evaluation_id, &decision.decision.candidate_id,
        &decision.decision.baseline_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.push(match decision.decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(decision.decision.failed_metrics.len() as u64).to_be_bytes());
    for id in &decision.decision.failed_metrics {
        push_id(&mut bytes, id)?;
    }
    bytes.push(0); // exactly DENY_ALL, checked above
    if bytes.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
        return Err(Error::Binding("original Qualification record exceeds bound"));
    }
    Ok(bytes)
}

pub(super) fn publication_digest(
    key: &ProductEvaluationExecutionKeyV1,
    bytes: &[u8],
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.agentd.original-qualification-publication.v1\0",
        key.binding_digest.as_array(), bytes,
    ])
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), Error> {
    push_bytes(bytes, id.as_str().as_bytes())
}
fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), Error> {
    if bytes.len().checked_add(8).and_then(|size| size.checked_add(value.len()))
        .is_none_or(|size| size > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1)
    {
        return Err(Error::Binding("original Qualification encoding exceeds bound"));
    }
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}
fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) -> Result<(), Error> {
    push_id(bytes, &principal.principal_id)?;
    for digest in [
        principal.credential_chain_digest, principal.signing_key_digest, principal.scope_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [principal.authority_epoch, principal.authenticated_at, principal.expires_at] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

pub(super) fn clock_time(started_at: u64, current: u64) -> Result<(), Error> {
    if current < started_at {
        return Err(Error::Binding("original Qualification clock moved backwards"));
    }
    Ok(())
}
pub(super) fn new_work_time(
    config: &OriginalCellEvaluationQualificationConfigV1,
    started_at: u64,
    current: u64,
) -> Result<(), Error> {
    clock_time(started_at, current)?;
    if current >= config.training.request.envelope.expiry_unix_seconds {
        return Err(Error::Binding("new Qualification outside original deadline"));
    }
    Ok(())
}
pub(super) fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original Qualification system clock"))
}
