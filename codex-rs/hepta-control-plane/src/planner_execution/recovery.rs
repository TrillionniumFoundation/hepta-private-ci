fn decode_grant_request_body(bytes: &[u8]) -> Result<GrantRequestV1, PlannerExecutionError> {
    let prefix = b"hepta.control.grant-request-body.v1";
    if bytes.len() > 4096 || !bytes.starts_with(prefix) {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    let mut rest = &bytes[prefix.len()..];
    let operation_id = decode_request_id(&mut rest)?;
    let candidate_id = decode_request_id(&mut rest)?;
    let request = GrantRequestV1 {
        operation_id,
        candidate_id,
        plan_digest: decode_request_digest(&mut rest)?,
        final_payload_digest: decode_request_digest(&mut rest)?,
        objective_digest: decode_request_digest(&mut rest)?,
        snapshot_digest: decode_request_digest(&mut rest)?,
        revocation_frontier_digest: decode_request_digest(&mut rest)?,
        expires_at_micros: decode_request_u64(&mut rest)?,
    };
    if !rest.is_empty() || canonical_grant_request_body(&request) != bytes {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    Ok(request)
}

fn take_request_bytes<'a>(
    bytes: &mut &'a [u8],
    len: usize,
) -> Result<&'a [u8], PlannerExecutionError> {
    if len > bytes.len() {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    let (value, rest) = bytes.split_at(len);
    *bytes = rest;
    Ok(value)
}

fn decode_request_u64(bytes: &mut &[u8]) -> Result<u64, PlannerExecutionError> {
    let value = take_request_bytes(bytes, 8)?
        .try_into()
        .map_err(|_| PlannerExecutionError::ReconciliationBindingMismatch)?;
    Ok(u64::from_be_bytes(value))
}

fn decode_request_id(
    bytes: &mut &[u8],
) -> Result<codex_hepta_types::StableId, PlannerExecutionError> {
    let len = usize::try_from(decode_request_u64(bytes)?)
        .map_err(|_| PlannerExecutionError::ReconciliationBindingMismatch)?;
    if len > 1024 {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    let value = std::str::from_utf8(take_request_bytes(bytes, len)?)
        .map_err(|_| PlannerExecutionError::ReconciliationBindingMismatch)?;
    codex_hepta_types::StableId::new(value)
        .map_err(|_| PlannerExecutionError::ReconciliationBindingMismatch)
}

fn decode_request_digest(bytes: &mut &[u8]) -> Result<Digest32, PlannerExecutionError> {
    let value: [u8; 32] = take_request_bytes(bytes, 32)?
        .try_into()
        .map_err(|_| PlannerExecutionError::ReconciliationBindingMismatch)?;
    let digest = Digest32::from_array(value);
    if digest.is_zero() {
        return Err(PlannerExecutionError::ReconciliationBindingMismatch);
    }
    Ok(digest)
}

fn validate_pending(
    store: &PlannerStoreV1,
    pending: &PlannerIndeterminateV1,
) -> Result<(), PlannerExecutionError> {
    let invalid = PlannerExecutionError::ReconciliationBindingMismatch;
    let request_body = store.body(pending.request_digest)?.ok_or(invalid.clone())?;
    if request_body.kind() != PlannerBodyKindV1::AuthorityRequest {
        return Err(invalid);
    }
    let request = decode_grant_request_body(request_body.bytes())?;
    if grant_request_digest(&request) != pending.request_digest
        || request.final_payload_digest != pending.final_payload_digest
        || request.expires_at_micros != pending.expires_at_micros
    {
        return Err(invalid);
    }
    let parent = if let Some(grant_digest) = pending.grant_digest {
        if pending.stage != IndeterminateStageV1::Effect {
            return Err(invalid);
        }
        let grant = store.body(grant_digest)?.ok_or(invalid.clone())?;
        if grant.kind() != PlannerBodyKindV1::AuthorityGrant
            || grant.parent_digest() != Some(pending.request_digest)
        {
            return Err(invalid);
        }
        grant_digest
    } else {
        if pending.stage != IndeterminateStageV1::Authority {
            return Err(invalid);
        }
        pending.request_digest
    };
    if pending.observation_digest != parent {
        let observed = store.body(pending.observation_digest)?.ok_or(invalid.clone())?;
        if observed.kind() != PlannerBodyKindV1::TerminalReceipt
            || observed.parent_digest() != Some(parent)
        {
            return Err(invalid);
        }
    }
    Ok(())
}
