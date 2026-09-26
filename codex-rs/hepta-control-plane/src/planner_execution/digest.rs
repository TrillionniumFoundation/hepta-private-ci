fn validate_authority_observation(
    observation: &SignedAuthorityObservationV1,
    request_digest: Digest32,
) -> Result<(), PlannerExecutionError> {
    require_signed_body(
        observation.observation_digest,
        observation.issuer_identity_digest,
        observation.signature_digest,
        &observation.canonical_body,
        b"hepta.control.authority-observation.v1",
        "authority observation",
    )?;
    if observation.request_digest != request_digest {
        return Err(PlannerExecutionError::AuthorityBindingMismatch);
    }
    let expected = authority_observation_digest(observation);
    if expected != observation.observation_digest {
        return Err(PlannerExecutionError::EvidenceDigestMismatch(
            "authority observation",
        ));
    }
    Ok(())
}

fn validate_grant(
    grant: &VerifiedExecutionGrantV1,
    request: &GrantRequestV1,
    request_digest: Digest32,
    now_micros: u64,
) -> Result<(), PlannerExecutionError> {
    require_signed_body(
        grant.grant_digest,
        grant.issuer_identity_digest,
        grant.signature_digest,
        &grant.canonical_body,
        b"hepta.control.authority-grant.v1",
        "authority grant",
    )?;
    if grant.request_digest != request_digest
        || grant.final_payload_digest != request.final_payload_digest
        || grant.authority_epoch == 0
        || grant.expires_at_micros > request.expires_at_micros
    {
        return Err(PlannerExecutionError::GrantBindingMismatch);
    }
    if now_micros >= grant.expires_at_micros {
        return Err(PlannerExecutionError::GrantExpired);
    }
    if authority_grant_digest(grant) != grant.grant_digest {
        return Err(PlannerExecutionError::EvidenceDigestMismatch(
            "authority grant",
        ));
    }
    Ok(())
}

fn validate_terminal(
    terminal: &SignedTerminalObservationV1,
    request: &GrantRequestV1,
    grant: &VerifiedExecutionGrantV1,
    request_digest: Digest32,
) -> Result<(), PlannerExecutionError> {
    require_signed_body(
        terminal.terminal_digest,
        terminal.executor_identity_digest,
        terminal.signature_digest,
        &terminal.canonical_body,
        b"hepta.control.terminal-observation.v1",
        "terminal observation",
    )?;
    if terminal.request_digest != request_digest
        || terminal.grant_digest != grant.grant_digest
        || terminal.final_payload_digest != request.final_payload_digest
    {
        return Err(PlannerExecutionError::TerminalBindingMismatch);
    }
    if terminal_observation_digest(terminal) != terminal.terminal_digest {
        return Err(PlannerExecutionError::EvidenceDigestMismatch(
            "terminal observation",
        ));
    }
    Ok(())
}

fn validate_reconciliation(
    receipt: &SignedReconciliationReceiptV1,
    pending: &PlannerIndeterminateV1,
) -> Result<(), PlannerExecutionError> {
    require_signed_body(
        receipt.reconciliation_digest,
        receipt.reconciler_identity_digest,
        receipt.signature_digest,
        &receipt.canonical_body,
        b"hepta.control.reconciliation-receipt.v1",
        "reconciliation receipt",
    )?;
    if receipt.request_digest != pending.request_digest
        || receipt.observed_digest != pending.observation_digest
    {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    if reconciliation_digest(receipt) != receipt.reconciliation_digest {
        return Err(PlannerExecutionError::EvidenceDigestMismatch(
            "reconciliation receipt",
        ));
    }
    Ok(())
}

fn require_signed_body(
    semantic_digest: Digest32,
    issuer: Digest32,
    signature: Digest32,
    body: &[u8],
    domain: &[u8],
    name: &'static str,
) -> Result<(), PlannerExecutionError> {
    if semantic_digest.is_zero() || issuer.is_zero() || signature.is_zero() || body.is_empty() {
        return Err(PlannerExecutionError::EmptyEvidence(name));
    }
    if evidence_digest(domain, body).is_zero() {
        return Err(PlannerExecutionError::EvidenceDigestMismatch(name));
    }
    Ok(())
}

pub fn grant_request_digest(request: &GrantRequestV1) -> Digest32 {
    evidence_digest(
        b"hepta.control.authority-request.v1",
        &canonical_grant_request_body(request),
    )
}

fn canonical_grant_request_body(request: &GrantRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.grant-request-body.v1".to_vec();
    push_bytes(&mut bytes, request.operation_id.as_str().as_bytes());
    push_bytes(&mut bytes, request.candidate_id.as_str().as_bytes());
    push_digest(&mut bytes, request.plan_digest);
    push_digest(&mut bytes, request.final_payload_digest);
    push_digest(&mut bytes, request.objective_digest);
    push_digest(&mut bytes, request.snapshot_digest);
    push_digest(&mut bytes, request.revocation_frontier_digest);
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    bytes
}

pub fn authority_observation_digest(observation: &SignedAuthorityObservationV1) -> Digest32 {
    let mut bytes = b"hepta.control.authority-observation-binding.v1".to_vec();
    push_digest(&mut bytes, observation.request_digest);
    bytes.push(observation.disposition.tag());
    push_digest(&mut bytes, observation.issuer_identity_digest);
    push_digest(&mut bytes, observation.signature_digest);
    push_digest(
        &mut bytes,
        evidence_digest(
            b"hepta.control.authority-observation.v1",
            &observation.canonical_body,
        ),
    );
    Digest32::of_bytes(&bytes)
}

pub fn authority_grant_digest(grant: &VerifiedExecutionGrantV1) -> Digest32 {
    let mut bytes = b"hepta.control.authority-grant-binding.v1".to_vec();
    push_digest(&mut bytes, grant.request_digest);
    push_digest(&mut bytes, grant.final_payload_digest);
    push_digest(&mut bytes, grant.issuer_identity_digest);
    push_digest(&mut bytes, grant.signature_digest);
    bytes.extend_from_slice(&grant.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&grant.expires_at_micros.to_be_bytes());
    push_digest(
        &mut bytes,
        evidence_digest(
            b"hepta.control.authority-grant.v1",
            &grant.canonical_body,
        ),
    );
    Digest32::of_bytes(&bytes)
}

pub fn terminal_observation_digest(terminal: &SignedTerminalObservationV1) -> Digest32 {
    let mut bytes = b"hepta.control.terminal-observation-binding.v1".to_vec();
    push_digest(&mut bytes, terminal.request_digest);
    push_digest(&mut bytes, terminal.grant_digest);
    push_digest(&mut bytes, terminal.final_payload_digest);
    bytes.push(terminal.disposition.tag());
    push_digest(&mut bytes, terminal.executor_identity_digest);
    push_digest(&mut bytes, terminal.signature_digest);
    push_digest(
        &mut bytes,
        evidence_digest(
            b"hepta.control.terminal-observation.v1",
            &terminal.canonical_body,
        ),
    );
    Digest32::of_bytes(&bytes)
}

pub fn reconciliation_digest(receipt: &SignedReconciliationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control.reconciliation-receipt-binding.v1".to_vec();
    push_digest(&mut bytes, receipt.request_digest);
    push_digest(&mut bytes, receipt.observed_digest);
    bytes.push(receipt.disposition.tag());
    push_digest(&mut bytes, receipt.reconciler_identity_digest);
    push_digest(&mut bytes, receipt.signature_digest);
    push_digest(
        &mut bytes,
        evidence_digest(
            b"hepta.control.reconciliation-receipt.v1",
            &receipt.canonical_body,
        ),
    );
    Digest32::of_bytes(&bytes)
}

fn evidence_digest(domain: &[u8], body: &[u8]) -> Digest32 {
    let mut bytes = domain.to_vec();
    push_bytes(&mut bytes, body);
    Digest32::of_bytes(&bytes)
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
