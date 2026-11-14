fn local_observation(
    operation: &OperationId,
    output: &NativeRunOutput,
) -> Result<LocalExecutionObservation, LocalModelError> {
    let status = match output.status {
        NativeRunStatus::Completed => LocalExecutionStatus::Succeeded,
        NativeRunStatus::Failed => LocalExecutionStatus::Failed,
        NativeRunStatus::Interrupted => LocalExecutionStatus::Cancelled,
        NativeRunStatus::Indeterminate => LocalExecutionStatus::Indeterminate,
    };
    Ok(LocalExecutionObservation {
        operation_id: operation.as_str().to_string(),
        status,
        output_digest: if output.output.is_empty() {
            None
        } else {
            Some(output.output.clone())
        },
        observed_usage_tokens: output.observed_output_tokens,
        terminal_observed: output.terminal_observed,
    })
}

#[derive(Debug)]
pub enum LocalModelError {
    InvalidGrant(&'static str),
    GrantBinding,
    GrantExpired,
    GrantRevoked,
    GrantReplay,
    RevocationRollback,
    ManifestBinding,
    InputBinding,
    DeadlineExpired,
    ResourceCapacity,
    ArithmeticOverflow,
    DriverAttestation,
    DriverRejected(String),
    DriverIndeterminate(String),
    ModelNotLoaded,
    InvalidTransition,
    ReconciliationRequired,
    Cancelled,
    StatePoisoned,
    Clock,
    Journal(codex_hepta_infer_core::durable_control::Error),
}

impl fmt::Display for LocalModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LocalModelError {}

fn map_driver_error(error: DriverError) -> LocalModelError {
    match error {
        DriverError::Rejected(reason) => LocalModelError::DriverRejected(reason),
        DriverError::Indeterminate(reason) => LocalModelError::DriverIndeterminate(reason),
    }
}

fn validate_grant_shape(claims: &ResourceGrantClaims) -> Result<(), LocalModelError> {
    if claims.schema_version != GRANT_SCHEMA
        || claims.authority_epoch == 0
        || claims.worker_generation == 0
        || claims.maximum_model_memory_bytes == 0
        || claims.maximum_aggregate_memory_bytes < claims.maximum_model_memory_bytes
        || claims.maximum_models == 0
        || claims.maximum_concurrency == 0
        || claims.maximum_tokens_per_request == 0
        || claims.maximum_tokens_per_request > MAX_TOKENS
        || claims.maximum_total_usage_tokens == 0
        || claims.not_before_unix_ms >= claims.expires_at_unix_ms
        || claims.revocation_revision == 0
    {
        return Err(LocalModelError::InvalidGrant("invalid grant bounds"));
    }
    for (value, label) in [
        (&claims.issuer_id, "issuer"),
        (&claims.grant_id, "grant"),
        (&claims.nonce, "nonce"),
        (&claims.worker_subject, "worker"),
        (&claims.model_id, "model"),
        (&claims.device_id, "device"),
        (&claims.device_lease_id, "device lease"),
    ] {
        validate_identifier(value, label)?;
    }
    for (value, label) in [
        (&claims.model_digest, "model"),
        (&claims.weights_digest, "weights"),
        (&claims.tokenizer_digest, "tokenizer"),
        (&claims.preprocessor_digest, "preprocessor"),
        (&claims.quantization_digest, "quantization"),
        (&claims.runtime_digest, "runtime"),
        (&claims.revocation_head_digest, "revocation head"),
        (&claims.semantic_digest, "semantic"),
    ] {
        validate_digest(value, label)?;
    }
    Ok(())
}

fn validate_revocation_head(head: &ResourceRevocationHead) -> Result<(), LocalModelError> {
    if head.authority_epoch == 0 || head.revision == 0 {
        return Err(LocalModelError::InvalidGrant("invalid revocation head"));
    }
    validate_digest(&head.head_digest, "revocation head")?;
    for grant in &head.revoked_grant_ids {
        validate_identifier(grant, "revoked grant")?;
    }
    Ok(())
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), LocalModelError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(LocalModelError::InvalidGrant(label));
    }
    Ok(())
}

fn validate_digest(value: &str, label: &'static str) -> Result<(), LocalModelError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(LocalModelError::InvalidGrant(label));
    }
    Ok(())
}

fn frame(hasher: &mut Sha256, value: &[u8]) {
    hasher.update(u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    hasher.update(value);
}

fn frame_u32(hasher: &mut Sha256, value: u32) {
    frame(hasher, &value.to_be_bytes());
}

fn frame_u64(hasher: &mut Sha256, value: u64) {
    frame(hasher, &value.to_be_bytes());
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn unix_time_ms() -> Result<u64, LocalModelError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| LocalModelError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| LocalModelError::Clock)
}
