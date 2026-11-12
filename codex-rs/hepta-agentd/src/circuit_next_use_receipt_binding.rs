//! Private original Observer binding, role checks and receipt encoding.
//! The unchanged legacy profile remains closed to evaluated-retention S.

use super::*;

pub(super) fn validate_config(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    key: &SigningKey,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
    config.scope.validate_snapshot(&config.selection)?;
    // This exact five-cut retention profile needs current original B as well
    // as T/S. The legacy configuration cannot carry that readback capability.
    if config.selection.receipts.len() == 5
        && coordinator.candidate().is_some()
        && matches!(
            config
                .selection
                .receipts
                .get(3)
                .map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            })
        )
        && matches!(
            config
                .selection
                .receipts
                .last()
                .map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Selection { .. })
        )
    {
        return Err(
            OwnerError::Binding("evaluated retention requires original T/B/S readbacks").into(),
        );
    }
    if coordinator.next_stage() != Some(LearningIterationStageV1::NextUse)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.signer.principal.principal_id != config.selection.owners.next_use_observer
        || config.selection.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.selection.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(OwnerError::Binding("original C Observer capability").into());
    }
    let current = now()?;
    authenticate_predecessors(
        config,
        &[
            config.training_evidence.clone(),
            config.selection_evidence.clone(),
        ],
        current,
    )?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.selection.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-next-use-receipt.v1\0",
            config.selection.head_digest.as_array(),
            config.scope.binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.training_evidence.signing_bytes(),
            &config.training_evidence.signature,
            &config.selection_evidence.signing_bytes(),
            &config.selection_evidence.signature,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    })
}

pub(super) fn prior(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    stage: LearningIterationStageV1,
) -> Result<&LearningIterationReceiptV1, Error> {
    config
        .selection
        .receipts
        .iter()
        .find(|receipt| receipt.observation.stage() == stage)
        .ok_or_else(|| OwnerError::Binding("original predecessor receipt").into())
}

pub(super) fn authenticate_predecessors(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    evidence: &[SignedLearningEvidenceV1; 2],
    current: u64,
) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
    if evidence[0] != config.training_evidence || evidence[1] != config.selection_evidence {
        return Err(OwnerError::Binding("changed original predecessor signatures").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        current,
    )?;
    let verify = |index, stage, role| -> Result<VerifiedLearningEvidenceV1, Error> {
        let original = prior(config, stage)?;
        let verified = config.verifier.verify(
            role,
            &evidence[index],
            &learning_iteration_receipt_signing_bytes_v1(original)?,
            current,
        )?;
        if verified.principal().principal_id != original.actor_id {
            return Err(OwnerError::Binding("original predecessor actor").into());
        }
        verify_independent_roles(verified.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if verified.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
        Ok(verified)
    };
    Ok([
        verify(
            0,
            LearningIterationStageV1::Training,
            LearningEvidenceRoleV1::Generator,
        )?,
        verify(
            1,
            LearningIterationStageV1::Selection,
            LearningEvidenceRoleV1::Selector,
        )?,
    ])
}

pub(super) fn receipt(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    receipt_with_domain(
        config,
        observation,
        observed_unix_seconds,
        b"hepta.agentd.original-circuit-next-use-evidence.v1\0",
    )
}

pub(super) fn receipt_with_domain(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
    domain: &[u8],
) -> Result<LearningIterationReceiptV1, Error> {
    let committed = match observation {
        LearningIterationObservationV1::NextUse {
            committed_step_receipt,
            ..
        }
        | LearningIterationObservationV1::RetainedModelNextUse {
            committed_step_receipt,
            ..
        } => committed_step_receipt,
        _ => return Err(OwnerError::Binding("actual original C completion").into()),
    };
    if committed.is_zero() {
        return Err(OwnerError::Binding("empty original C completion").into());
    }
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.selection.request.operation_id.clone(),
        predecessor: config.selection.head_digest,
        actor_id: config.selection.owners.next_use_observer.clone(),
        evidence_digest: Digest32::of_parts(&[
            domain,
            config.selection.head_digest.as_array(),
            committed.as_array(),
        ]),
        observed_unix_seconds,
        observation: observation.clone(),
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

pub(super) fn sign_original(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, OwnerError> {
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(OwnerError::Binding("signature deadline overflow"))?
        .min(config.signer.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
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

pub(super) fn require_new_attestation(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    started_at: u64,
    current: u64,
) -> Result<(), OwnerError> {
    if current < started_at || current >= config.selection.request.envelope.expiry_unix_seconds {
        return Err(OwnerError::Binding(
            "new C attestation outside original deadline",
        ));
    }
    Ok(())
}

pub(super) fn evidence_id(identity: Digest32) -> Result<StableId, OwnerError> {
    StableId::new(format!("original-circuit-next-use:{identity}"))
        .map_err(|_| OwnerError::Binding("original C evidence id"))
}

pub(super) fn now() -> Result<u64, OwnerError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| OwnerError::Binding("original Observer clock"))
}
