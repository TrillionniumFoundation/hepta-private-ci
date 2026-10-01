//! Bounded manifest, grant and request validation for the local model driver.

use super::Error;
use super::MAX_TOKENS;
use super::ModelManifest;
use super::ResourceGrant;
use super::WorkerRequest;

pub(super) fn validate_manifest(value: &ModelManifest) -> Result<(), Error> {
    validate_identity(&value.model_id, "model")?;
    for (digest, field) in [
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.device_digest, "device"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.maximum_tokens == 0 || value.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidManifest);
    }
    Ok(())
}

pub(super) fn validate_grant(now_ms: u64, value: &ResourceGrant) -> Result<(), Error> {
    validate_identity(&value.grant_id, "grant")?;
    validate_digest(&value.semantic_digest, "grant semantic")?;
    if value.revoked {
        return Err(Error::GrantRevoked);
    }
    if value.authority_epoch == 0
        || value.generation == 0
        || value.maximum_models == 0
        || value.maximum_active_requests == 0
        || value.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidGrant);
    }
    if now_ms >= value.expires_at_ms {
        return Err(Error::GrantExpired);
    }
    Ok(())
}

pub(super) fn validate_request(now_ms: u64, value: &WorkerRequest) -> Result<(), Error> {
    validate_identity(&value.request_id, "request")?;
    validate_identity(&value.reservation_id, "reservation")?;
    validate_digest(&value.model_digest, "model")?;
    validate_digest(&value.payload_digest, "payload")?;
    validate_digest(&value.lease_payload_digest, "lease payload")?;
    validate_digest(&value.reservation_model_digest, "reservation model")?;
    if value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.reservation_maximum_tokens == 0
        || value.reservation_maximum_tokens > MAX_TOKENS
    {
        return Err(Error::TokenLimit);
    }
    if now_ms >= value.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

pub(super) fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

pub(super) fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
}
