//! Exact predecessor binding and pure current-time signature checks.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::revalidate_product_qualification_v1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;

use super::*;

pub(super) fn validate_config(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    key: &SigningKey,
) -> Result<(ProductEvaluationExecutionKeyV1, LearningIterationSnapshotV1), Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
    config.scope.validate_snapshot(&config.decision)?;
    if config.decision.receipts.len() != 5
        || coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.signer.principal.principal_id != config.decision.owners.selector
        || config.decision.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.decision.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        || !matches!(
            &training_receipt(config)?.observation,
            LearningIterationObservationV1::Training { .. }
        )
        || !matches!(
            &evaluation_receipt(config)?.observation,
            LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::Qualified,
                ..
            }
        )
        || !matches!(
            &config.decision.receipts[4].observation,
            LearningIterationObservationV1::Proposal {
                disposition: LearningProposalDispositionV1::UpdateCandidates,
                ..
            }
        )
    {
        return Err(OwnerError::Binding("original positive Model Selector capability").into());
    }
    let candidate = coordinator
        .candidate()
        .ok_or(OwnerError::Binding("original trained Model candidate"))?
        .digest()
        .map_err(LearningIterationError::from)?;
    if candidate
        == config
            .decision
            .request
            .selected_bundle
            .digest()
            .map_err(LearningIterationError::from)?
    {
        return Err(
            OwnerError::Binding("positive Model selection requires a changed candidate").into(),
        );
    }
    let product = config.qualification.product();
    product.validate_integrity()?;
    config
        .evaluation
        .require_original_signed_execution(&product.evaluator)?;
    if config.qualification.comparison() != config.evaluation.plan().record()
        || product.temporal_execution_digest != config.evaluation.temporal().execution_digest
        || product.evidence_digest != evaluation_receipt(config)?.evidence_digest
        || product.generator.principal_id != config.decision.owners.trainer
        || product.evaluator.principal_id != config.decision.owners.evaluator
        || product.objective_digest != config.verifier.objective_digest()
        || product.decision.trust_digest != config.verifier.trust_digest()
        || config.execution_evidence.key().plan_id
            != config.evaluation.plan().product_plan().frozen_plan.plan_id
    {
        return Err(OwnerError::Binding("original Model evaluation material").into());
    }
    let evidence = (
        config.training_evidence.clone(),
        config.evaluation_evidence.clone(),
    );
    let current = now()?;
    authenticate_roles(config, &evidence, current)?;
    let execution = OriginalProductEvaluationExecutionEvidenceV1::revalidate(
        &config.execution_evidence,
        &config.verifier,
        current,
    )?;
    if execution.principal() != &product.evaluator {
        return Err(OwnerError::Binding("original execution Evaluator").into());
    }
    let mut training = LearningIterationCoordinatorV1::new(
        config.decision.request.clone(),
        config.decision.owners.clone(),
    )?;
    for receipt in config.decision.receipts.iter().take(3) {
        training.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    let mut signatures = Vec::new();
    for original in [
        &config.training_evidence,
        &config.evaluation_evidence,
        &config.product_evidence.generator_plan,
        &config.product_evidence.evaluator_bundle,
        config.execution_evidence.attestation(),
    ] {
        let bytes = original.signing_bytes();
        signatures.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
        signatures.extend_from_slice(&bytes);
        signatures.extend_from_slice(&original.signature);
    }
    Ok((
        ProductEvaluationExecutionKeyV1 {
            plan_id: config.decision.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-circuit-model-selection-receipt.v1\0",
                config.decision.head_digest.as_array(),
                config.scope.binding().as_array(),
                config.verifier.trust_digest().as_array(),
                config.signer.principal.principal_id.as_str().as_bytes(),
                &config.signer.verifying_key,
                config.execution_evidence.key().binding_digest.as_array(),
                config.execution_evidence.record_digest().as_array(),
                product.evidence_digest.as_array(),
                product.publication_digest.as_array(),
                &signatures,
                &config.maximum_signature_lifetime_seconds.to_be_bytes(),
            ]),
        },
        training.snapshot().clone(),
    ))
}

pub(super) fn training_receipt(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    config
        .decision
        .receipts
        .get(2)
        .ok_or_else(|| OwnerError::Binding("original Model Training receipt").into())
}
pub(super) fn evaluation_receipt(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    config
        .decision
        .receipts
        .get(3)
        .ok_or_else(|| OwnerError::Binding("original Model Evaluation receipt").into())
}

pub(super) fn authenticate_roles(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    evidence: &(SignedLearningEvidenceV1, SignedLearningEvidenceV1),
    current: u64,
) -> Result<(VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1), Error> {
    if evidence.0 != config.training_evidence || evidence.1 != config.evaluation_evidence {
        return Err(OwnerError::Binding("changed original Model predecessor signatures").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Selector,
        &config.signer,
        current,
    )?;
    let training = config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.0,
        &learning_iteration_receipt_signing_bytes_v1(training_receipt(config)?)?,
        current,
    )?;
    let evaluation = config.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence.1,
        &learning_iteration_receipt_signing_bytes_v1(evaluation_receipt(config)?)?,
        current,
    )?;
    if training.principal().principal_id != config.decision.owners.trainer
        || evaluation.principal().principal_id != config.decision.owners.evaluator
        || training.principal() != &config.qualification.product().generator
        || evaluation.principal() != &config.qualification.product().evaluator
    {
        return Err(OwnerError::Binding("original Model predecessor actors").into());
    }
    verify_signed_actor_separation(&training, &evaluation, current)?;
    for original in [&training, &evaluation] {
        verify_independent_roles(original.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if original.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
    }
    Ok((training, evaluation))
}

pub(super) fn authenticate(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    prepared: &Prepared,
    timing: ProductTimingEvidenceV1<'_>,
    evidence: &(SignedLearningEvidenceV1, SignedLearningEvidenceV1),
    current: u64,
) -> Result<(VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1), Error> {
    let (training, evaluation) = authenticate_roles(config, evidence, current)?;
    let original = OriginalProductEvaluationExecutionEvidenceV1::revalidate(
        &config.execution_evidence,
        &config.verifier,
        current,
    )?;
    if original.principal() != evaluation.principal()
        || original.controller_id() != evaluation.controller_id()
        || prepared.bundle.generator != *training.principal()
        || prepared.bundle.evaluator != *evaluation.principal()
    {
        return Err(OwnerError::Binding("original Model execution and product actors").into());
    }
    let decision = revalidate_product_qualification_v1(
        config.qualification.product(),
        prepared.bundle.clone(),
        config.evaluation.plan().product_plan().metric_roles.clone(),
        &config.product_evidence,
        timing,
        &config.verifier,
        current,
    )?;
    if decision.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(OwnerError::Binding("original Model qualification is not eligible").into());
    }
    Ok((training, evaluation))
}

pub(super) fn receipt(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let LearningIterationObservationV1::Selection {
        candidate_bundle,
        selection_digest,
    } = observation
    else {
        return Err(OwnerError::Binding("actual original Model selection observation").into());
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
    let candidate = coordinator
        .candidate()
        .ok_or(OwnerError::Binding("original positive Model candidate"))?
        .digest()
        .map_err(LearningIterationError::from)?;
    if *candidate_bundle != candidate || selection_digest.is_zero() {
        return Err(OwnerError::Binding("actual positive Model publication").into());
    }
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.decision.request.operation_id.clone(),
        predecessor: config.decision.head_digest,
        actor_id: config.decision.owners.selector.clone(),
        evidence_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-model-selection-evidence.v1\0",
            config.decision.head_digest.as_array(),
            candidate_bundle.as_array(),
            selection_digest.as_array(),
            config.execution_evidence.record_digest().as_array(),
            config.qualification.product().evidence_digest.as_array(),
        ]),
        observed_unix_seconds,
        observation: observation.clone(),
    };
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

pub(super) fn sign_original(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, OwnerError> {
    sign_original_until(config, key, payload, identity, issued_at, signature_expiry(config, issued_at)?)
}

/// A new remote attestation may only shorten the original owner's window.
/// Existing completed signatures are read verbatim and are never re-signed.
pub(super) fn sign_original_until(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
    expires_at: u64,
) -> Result<SignedLearningEvidenceV1, OwnerError> {
    if expires_at <= issued_at || expires_at > signature_expiry(config, issued_at)? {
        return Err(OwnerError::Binding("original Model Selector capped window"));
    }
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Selector,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: config.signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    Ok(signed)
}

pub(super) fn signature_expiry(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    issued_at: u64,
) -> Result<u64, OwnerError> {
    Ok(issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(OwnerError::Binding(
            "Model Selector signature deadline overflow",
        ))?
        .min(config.signer.principal.expires_at)
        .min(config.training_evidence.expires_at)
        .min(config.evaluation_evidence.expires_at)
        .min(config.product_evidence.generator_plan.expires_at)
        .min(config.product_evidence.evaluator_bundle.expires_at)
        .min(config.execution_evidence.attestation().expires_at))
}

pub(super) fn new_work_time(
    config: &OriginalCircuitModelSelectionReceiptConfigV1,
    started_at: u64,
    current: u64,
) -> Result<(), OwnerError> {
    if current < started_at || current >= config.decision.request.envelope.expiry_unix_seconds {
        return Err(OwnerError::Binding(
            "new Model Selection outside original deadline",
        ));
    }
    Ok(())
}

pub(super) fn evidence_id(identity: Digest32) -> Result<StableId, OwnerError> {
    StableId::new(format!("original-circuit-model-selection:{identity}"))
        .map_err(|_| OwnerError::Binding("original Model Selection evidence id"))
}

pub(super) fn now() -> Result<u64, OwnerError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| OwnerError::Binding("original Model Selector clock"))
}
