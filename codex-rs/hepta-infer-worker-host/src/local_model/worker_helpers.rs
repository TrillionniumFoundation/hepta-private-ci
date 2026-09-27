fn attest_driver_handle(
    manifest: &VerifiedModelManifest,
    grant: &VerifiedResourceGrant,
    evidence: DriverLoadEvidence,
) -> Result<AttestedModelHandle, Error> {
    validate_identity(&evidence.handle_id, "model handle")?;
    if evidence.model_digest != manifest.manifest.model_digest
        || evidence.weights_digest != manifest.manifest.weights_digest
        || evidence.runtime_digest != manifest.manifest.runtime_digest
        || evidence.device_id != manifest.manifest.device_id
        || evidence.device_digest != manifest.manifest.device_digest
        || evidence.observed_weight_bytes == 0
        || evidence.observed_weight_bytes > manifest.manifest.declared_weight_bytes
        || evidence.observed_weight_bytes > grant.claims.maximum_model_memory_bytes
    {
        return Err(Error::InvalidManifest("driver load evidence"));
    }
    Ok(AttestedModelHandle {
        handle_id: evidence.handle_id,
        model_id: manifest.manifest.model_id.clone(),
        model_digest: evidence.model_digest,
        weights_digest: evidence.weights_digest,
        runtime_digest: evidence.runtime_digest,
        device_id: evidence.device_id,
        device_digest: evidence.device_digest,
        observed_weight_bytes: evidence.observed_weight_bytes,
    })
}

fn attest_host_load(
    provisional: &AttestedModelHandle,
    manifest: &VerifiedModelManifest,
    grant: &VerifiedResourceGrant,
    generation: u64,
    host: &HostResourceObservation,
) -> Result<AttestedModelHandle, Error> {
    validate_identity(&host.handle_id, "observed handle")?;
    if !host.present
        || host.handle_id != provisional.handle_id
        || host.worker_generation != generation
        || host.device_id != provisional.device_id
        || host.device_digest != provisional.device_digest
        || host.model_memory_bytes == 0
        || host.model_memory_bytes != provisional.observed_weight_bytes
        || host.model_memory_bytes > manifest.manifest.declared_weight_bytes
        || host.model_memory_bytes > grant.claims.maximum_model_memory_bytes
        || host.kv_memory_bytes != 0
        || host.transient_memory_bytes != 0
    {
        return Err(Error::InvalidManifest("trusted host load observation"));
    }
    let mut handle = provisional.clone();
    handle.observed_weight_bytes = host.model_memory_bytes;
    Ok(handle)
}

fn validate_run_evidence(
    evidence: &DriverRunEvidence,
    host: &HostResourceObservation,
    loaded: &LoadedModel,
    grant: &VerifiedResourceGrant,
    generation: u64,
) -> Result<(), Error> {
    if !evidence.terminal_observed
        || evidence.status.is_none()
        || evidence.consumed_tokens.is_none()
        || !host.present
        || host.handle_id != loaded.handle.handle_id
        || host.worker_generation != generation
        || host.device_id != loaded.handle.device_id
        || host.device_digest != loaded.handle.device_digest
        || host.model_memory_bytes != loaded.handle.observed_weight_bytes
        || evidence.observed_model_bytes != host.model_memory_bytes
        || evidence.observed_kv_memory_bytes != host.kv_memory_bytes
        || evidence.transient_memory_bytes != host.transient_memory_bytes
        || evidence.observed_kv_memory_bytes
            > loaded.manifest.manifest.maximum_kv_memory_bytes
        || evidence.observed_kv_memory_bytes > grant.claims.maximum_kv_memory_bytes
        || evidence.transient_memory_bytes
            > loaded.manifest.manifest.maximum_transient_memory_bytes
        || evidence.transient_memory_bytes > grant.claims.maximum_transient_memory_bytes
        || evidence.consumed_tokens.unwrap_or(MAX_TOKENS) > grant.claims.maximum_tokens
    {
        return Err(Error::ResourceCapacity);
    }
    if let Some(output) = &evidence.output_digest {
        validate_digest(output, "output")?;
    }
    if evidence.status == Some(DriverTerminalStatus::Succeeded)
        && evidence.output_digest.is_none()
    {
        return Err(Error::Control("successful output missing".to_string()));
    }
    Ok(())
}

fn durable_record(
    control: &DurableInferenceControl,
    operation_id: &OperationId,
) -> Result<RequestRecord, Error> {
    control
        .get(operation_id.as_str())
        .cloned()
        .ok_or_else(|| Error::Control("durable request missing".to_string()))
}

fn request_memory(loaded: &LoadedModel) -> Result<u64, Error> {
    loaded
        .manifest
        .manifest
        .maximum_kv_memory_bytes
        .checked_add(loaded.manifest.manifest.maximum_transient_memory_bytes)
        .ok_or(Error::ArithmeticOverflow)
}

fn terminal_state(state: RequestState) -> bool {
    matches!(
        state,
        RequestState::Completed
            | RequestState::Failed
            | RequestState::Cancelled
            | RequestState::Indeterminate
    )
}

fn terminal_receipt(record: &RequestRecord) -> Result<LocalRunReceipt, Error> {
    let (status, output, terminal) = match record.state {
        RequestState::Completed => (
            LocalRunStatus::Succeeded,
            record.terminal_observation_digest.clone(),
            true,
        ),
        RequestState::Failed => (LocalRunStatus::Failed, None, true),
        RequestState::Cancelled => (LocalRunStatus::Cancelled, None, true),
        RequestState::Indeterminate => (LocalRunStatus::Indeterminate, None, false),
        _ => {
            return Err(Error::Control("request is not terminal".to_string()));
        }
    };
    Ok(LocalRunReceipt {
        operation_id: record.request.request_id.clone(),
        status,
        output_digest: output,
        consumed_tokens: terminal.then_some(record.consumed_tokens),
        terminal_observed: terminal,
        replayed_provider: false,
        stop_reason: (!terminal)
            .then(|| "legacy indeterminate record remains quarantined".to_string()),
    })
}

fn indeterminate_receipt(
    operation_id: &OperationId,
    reason: &str,
) -> LocalRunReceipt {
    LocalRunReceipt {
        operation_id: operation_id.as_str().to_string(),
        status: LocalRunStatus::Indeterminate,
        output_digest: None,
        consumed_tokens: None,
        terminal_observed: false,
        replayed_provider: false,
        stop_reason: Some(reason.chars().take(1_024).collect()),
    }
}

fn request_semantic_digest(
    operation_id: &OperationId,
    handle: &AttestedModelHandle,
    input: &VerifiedInput,
    maximum_tokens: u32,
    deadline_ms: u64,
    grant: &VerifiedResourceGrant,
) -> String {
    digest(
        format!(
            "hepta.local-request.v1|{}|{}|{}|{}|{}|{}|{}",
            operation_id.as_str(),
            handle.handle_id,
            handle.model_digest,
            input.digest(),
            maximum_tokens,
            deadline_ms,
            grant.witness_digest
        )
        .as_bytes(),
    )
}

fn assignment_digest(
    operation_id: &OperationId,
    handle: &AttestedModelHandle,
    grant: &VerifiedResourceGrant,
) -> String {
    digest(
        format!(
            "hepta.local-assignment.v1|{}|{}|{}|{}|{}",
            operation_id.as_str(),
            handle.handle_id,
            handle.device_id,
            handle.device_digest,
            grant.witness_digest
        )
        .as_bytes(),
    )
}
