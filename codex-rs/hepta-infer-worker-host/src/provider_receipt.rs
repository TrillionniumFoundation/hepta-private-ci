//! Independently signed provider terminal/usage receipts for recovery.
//!
//! A verified receipt may refine provider terminality or usage for one exact
//! durable dispatch. It cannot create or upgrade `NativeOwnerAuthority` and it
//! never authorizes a new `turn/start`.

use std::error::Error as StdError;
use std::fmt;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_infer_core::durable_control::native::{
    NativeBoundaryStatus, NativeOwnerAuthority, NativeRunOutput, NativeRunRecord,
    NativeRunStatus,
};
use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const RECEIPT_SCHEMA_VERSION: u32 = 1;
const MAX_IDENTITY_BYTES: usize = 256;
const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
const MAX_REASON_BYTES: usize = 4096;
const MAX_RECEIPT_VALIDITY_MS: u64 = 24 * 60 * 60 * 1000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderTerminalReceiptClaims {
    pub schema_version: u32,
    pub issuer: String,
    pub authority_epoch: u64,
    pub receipt_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub model: String,
    pub thread_id: String,
    pub turn_id: String,
    pub model_provider: String,
    pub codex_request_digest: String,
    pub codex_payload_digest: String,
    pub codex_source_admission_digest: String,
    pub terminal_correlation_digest: String,
    pub status: NativeRunStatus,
    pub output: String,
    pub output_sha256: String,
    pub observed_output_tokens: Option<u64>,
    pub stop_reason: Option<String>,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedProviderTerminalReceipt {
    pub claims: ProviderTerminalReceiptClaims,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct ProviderReceiptVerifier {
    issuer: String,
    authority_epoch: u64,
    verifying_key: VerifyingKey,
    maximum_validity_ms: u64,
}

impl ProviderReceiptVerifier {
    pub fn new(
        issuer: String,
        authority_epoch: u64,
        verifying_key: [u8; 32],
        maximum_validity_ms: u64,
    ) -> Result<Self, ProviderReceiptError> {
        validate_identity(&issuer, "issuer")?;
        if authority_epoch == 0
            || maximum_validity_ms == 0
            || maximum_validity_ms > MAX_RECEIPT_VALIDITY_MS
        {
            return Err(ProviderReceiptError::Invalid("verifier bounds"));
        }
        Ok(Self {
            issuer,
            authority_epoch,
            verifying_key: VerifyingKey::from_bytes(&verifying_key)
                .map_err(|_| ProviderReceiptError::Signature)?,
            maximum_validity_ms,
        })
    }

    pub fn verify(
        &self,
        signed: &SignedProviderTerminalReceipt,
    ) -> Result<VerifiedProviderTerminalReceipt, ProviderReceiptError> {
        self.verify_at(signed, wall_clock_ms()?)
    }

    pub fn verify_at(
        &self,
        signed: &SignedProviderTerminalReceipt,
        now_ms: u64,
    ) -> Result<VerifiedProviderTerminalReceipt, ProviderReceiptError> {
        validate_claims(&signed.claims)?;
        let validity_ms = signed
            .claims
            .expires_at_ms
            .checked_sub(signed.claims.issued_at_ms)
            .ok_or(ProviderReceiptError::Invalid("receipt validity"))?;
        if signed.claims.issuer != self.issuer
            || signed.claims.authority_epoch != self.authority_epoch
            || signed.claims.issued_at_ms > now_ms
            || now_ms >= signed.claims.expires_at_ms
            || validity_ms > self.maximum_validity_ms
            || provider_receipt_semantic_digest(&signed.claims)?
                != signed.claims.semantic_digest
        {
            return Err(ProviderReceiptError::Invalid("authority or time binding"));
        }
        let signing_bytes = provider_receipt_signing_bytes(&signed.claims)?;
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| ProviderReceiptError::Signature)?;
        self.verifying_key
            .verify_strict(&signing_bytes, &signature)
            .map_err(|_| ProviderReceiptError::Signature)?;
        let mut witness = signing_bytes;
        witness.extend_from_slice(&signed.signature);
        Ok(VerifiedProviderTerminalReceipt {
            claims: signed.claims.clone(),
            witness_sha256: sha256(&witness),
        })
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedProviderTerminalReceipt {
    claims: ProviderTerminalReceiptClaims,
    witness_sha256: String,
}

impl VerifiedProviderTerminalReceipt {
    pub fn receipt_id(&self) -> &str {
        &self.claims.receipt_id
    }

    pub fn witness_sha256(&self) -> &str {
        &self.witness_sha256
    }

    pub(crate) fn resolve(
        &self,
        record: &NativeRunRecord,
    ) -> Result<ProviderReceiptResolution, ProviderReceiptError> {
        let dispatch = record
            .dispatch
            .as_ref()
            .ok_or(ProviderReceiptError::Mismatch("missing durable dispatch"))?;
        let exact_dispatch = record.request.request_id == self.claims.request_id
            && record.request.principal_id == self.claims.principal_id
            && record.request.worker_generation == self.claims.worker_generation
            && record.request.model == self.claims.model
            && dispatch.thread_id == self.claims.thread_id
            && dispatch.model_provider == self.claims.model_provider
            && dispatch.codex_request_digest.as_deref()
                == Some(self.claims.codex_request_digest.as_str())
            && dispatch.codex_payload_digest.as_deref()
                == Some(self.claims.codex_payload_digest.as_str())
            && dispatch.codex_source_admission_digest.as_deref()
                == Some(self.claims.codex_source_admission_digest.as_str())
            && record
                .turn_id
                .as_ref()
                .is_none_or(|turn| turn == &self.claims.turn_id);
        if !exact_dispatch
            || record.pre_dispatch_stop.is_some()
            || record.dispatch_rejection.is_some()
        {
            return Err(ProviderReceiptError::Mismatch("durable dispatch binding"));
        }
        let owner_authority = record
            .observation
            .as_ref()
            .map(|output| output.owner_authority.clone())
            .unwrap_or(NativeOwnerAuthority::Unverified);
        let boundary_status = match self.claims.status {
            NativeRunStatus::Completed => NativeBoundaryStatus::Succeeded,
            NativeRunStatus::Failed => NativeBoundaryStatus::Failed,
            NativeRunStatus::Interrupted => NativeBoundaryStatus::Interrupted,
            NativeRunStatus::Indeterminate => {
                return Err(ProviderReceiptError::Invalid("nonterminal receipt"));
            }
        };
        let output = NativeRunOutput {
            thread_id: self.claims.thread_id.clone(),
            turn_id: self.claims.turn_id.clone(),
            model: self.claims.model.clone(),
            model_provider: self.claims.model_provider.clone(),
            status: self.claims.status,
            boundary_status,
            output: self.claims.output.clone(),
            observed_output_tokens: self.claims.observed_output_tokens,
            terminal_observed: true,
            stop_reason: self.claims.stop_reason.clone(),
            owner_authority,
            codex_terminal_correlation_digest: Some(
                self.claims.terminal_correlation_digest.clone(),
            ),
        };
        Ok(ProviderReceiptResolution {
            output,
            receipt_id: self.claims.receipt_id.clone(),
            receipt_witness_sha256: self.witness_sha256.clone(),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderReceiptResolution {
    pub output: NativeRunOutput,
    pub receipt_id: String,
    /// The caller must retain the signed receipt and this witness in its
    /// evidence archive; the native journal durably retains normalized terminal
    /// and usage facts but does not pretend to be the provider receipt archive.
    pub receipt_witness_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderReceiptError {
    Invalid(&'static str),
    Mismatch(&'static str),
    Signature,
    Time,
    Serialization,
}

impl fmt::Display for ProviderReceiptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderReceiptError {}

pub fn provider_receipt_semantic_digest(
    claims: &ProviderTerminalReceiptClaims,
) -> Result<String, ProviderReceiptError> {
    let mut canonical = claims.clone();
    canonical.semantic_digest.clear();
    serde_json::to_vec(&(
        "hepta.provider-terminal-receipt.semantic.v1",
        canonical,
    ))
    .map(|bytes| sha256(&bytes))
    .map_err(|_| ProviderReceiptError::Serialization)
}

pub fn provider_receipt_signing_bytes(
    claims: &ProviderTerminalReceiptClaims,
) -> Result<Vec<u8>, ProviderReceiptError> {
    serde_json::to_vec(&(
        "hepta.provider-terminal-receipt.signed.v1",
        claims,
    ))
    .map_err(|_| ProviderReceiptError::Serialization)
}

fn validate_claims(
    claims: &ProviderTerminalReceiptClaims,
) -> Result<(), ProviderReceiptError> {
    for (value, field) in [
        (&claims.issuer, "issuer"),
        (&claims.receipt_id, "receipt"),
        (&claims.request_id, "request"),
        (&claims.principal_id, "principal"),
        (&claims.thread_id, "thread"),
        (&claims.turn_id, "turn"),
        (&claims.model_provider, "provider"),
    ] {
        validate_identity(value, field)?;
    }
    if claims.model.is_empty()
        || claims.model.len() > MAX_IDENTITY_BYTES
        || claims.model.bytes().any(|byte| byte.is_ascii_control())
        || claims.schema_version != RECEIPT_SCHEMA_VERSION
        || claims.authority_epoch == 0
        || claims.worker_generation == 0
        || claims.issued_at_ms == 0
        || claims.expires_at_ms <= claims.issued_at_ms
        || claims.output.len() > MAX_OUTPUT_BYTES
        || claims
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.len() > MAX_REASON_BYTES)
        || claims.status == NativeRunStatus::Indeterminate
    {
        return Err(ProviderReceiptError::Invalid("claims"));
    }
    for (value, field) in [
        (&claims.codex_request_digest, "codex request"),
        (&claims.codex_payload_digest, "codex payload"),
        (&claims.codex_source_admission_digest, "source admission"),
        (&claims.terminal_correlation_digest, "terminal correlation"),
        (&claims.output_sha256, "output"),
        (&claims.semantic_digest, "semantic"),
    ] {
        validate_digest(value, field)?;
    }
    if sha256(claims.output.as_bytes()) != claims.output_sha256 {
        return Err(ProviderReceiptError::Invalid("output digest"));
    }
    Ok(())
}

fn validate_identity(
    value: &str,
    field: &'static str,
) -> Result<(), ProviderReceiptError> {
    if value.is_empty()
        || value.len() > MAX_IDENTITY_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(ProviderReceiptError::Invalid(field));
    }
    Ok(())
}

fn validate_digest(
    value: &str,
    field: &'static str,
) -> Result<(), ProviderReceiptError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ProviderReceiptError::Invalid(field));
    }
    Ok(())
}

fn wall_clock_ms() -> Result<u64, ProviderReceiptError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .ok_or(ProviderReceiptError::Time)
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
