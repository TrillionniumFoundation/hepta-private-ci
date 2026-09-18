//! Product-facing composition for one isolated local-model execution.
//!
//! The caller supplies the existing inference request/lease/reservation facts,
//! a kernel-signed resource grant, an exact model manifest and immutable local
//! artifact paths. The composition validates the pre-existing inference
//! contract before it constructs the physical local runtime driver.

#![forbid(unsafe_code)]

use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AuthorityLease;
use crate::InferenceRequest;
use crate::Reservation;
use crate::TerminalStatus;
use crate::execute;
use crate::local_process::LocalModelArtifacts;
use crate::local_process::LocalProcessDriver;
use crate::model_worker::ExecutionStatus;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;
use crate::model_worker::verify_resource_grant;

pub type ProductResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Versioned wire envelope emitted by the trusted product caller. Identity and
/// digest strings are parsed into the same bounded core types used by the
/// pre-existing inference boundary; unknown fields fail closed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalExecutionEnvelopeV1 {
    pub schema_version: u32,
    pub request_id: String,
    pub reservation_id: String,
    pub model_digest: String,
    pub prompt_digest: String,
    pub prompt: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub lease_id: String,
    pub lease_request_id: String,
    pub lease_model_digest: String,
    /// Canonical request digest consumed by the existing AuthorityLease.
    pub lease_payload_digest: String,
    pub lease_expires_at_ms: u64,
    pub lease_revoked: bool,
    pub reservation_request_id: String,
    pub reservation_model_digest: String,
    pub reservation_maximum_tokens: u32,
    pub reservation_valid_until_ms: u64,
    pub reservation_cancelled: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalProductStatus {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalProductOutput {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_generation: u64,
    pub model_digest: String,
    pub payload_digest: String,
    pub status: LocalProductStatus,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
}

pub struct LocalProductConfig {
    pub worker_id: String,
    pub generation: u64,
    pub runtime_socket: PathBuf,
    pub artifacts: LocalModelArtifacts,
    pub timeout: Duration,
}

/// Execute one local request through all repository-owned boundaries. This does
/// not manufacture authority: request/lease/reservation must already match, and
/// the resource grant must be signed by the configured kernel authority owner.
pub fn execute_local_product(
    now_ms: u64,
    config: LocalProductConfig,
    authority: &FinalUseAuthority,
    signed_resource_grant: &SignedFinalUseGrant,
    resource_grant: ResourceGrant,
    manifest: ModelManifest,
    envelope: LocalExecutionEnvelopeV1,
) -> ProductResult<LocalProductOutput> {
    if envelope.schema_version != 1 {
        return Err("unsupported local execution envelope version".into());
    }
    if envelope.prompt.is_empty() || envelope.prompt.len() > 32 * 1024 {
        return Err("local prompt must contain 1..32768 bytes".into());
    }

    let request = InferenceRequest {
        request_id: StableId::new(envelope.request_id.clone())?,
        reservation_id: StableId::new(envelope.reservation_id.clone())?,
        model_digest: envelope.model_digest.parse::<Digest32>()?,
        prompt_digest: envelope.prompt_digest.parse::<Digest32>()?,
        maximum_tokens: envelope.maximum_tokens,
        deadline_ms: envelope.deadline_ms,
    };
    if Digest32::of_bytes(envelope.prompt.as_bytes()) != request.prompt_digest {
        return Err("prompt bytes do not match prompt_digest".into());
    }
    let lease = AuthorityLease {
        lease_id: StableId::new(envelope.lease_id)?,
        request_id: StableId::new(envelope.lease_request_id)?,
        model_digest: envelope.lease_model_digest.parse::<Digest32>()?,
        payload_digest: envelope.lease_payload_digest.parse::<Digest32>()?,
        expires_at_ms: envelope.lease_expires_at_ms,
        revoked: envelope.lease_revoked,
    };
    let reservation = Reservation {
        reservation_id: StableId::new(envelope.reservation_id)?,
        request_id: StableId::new(envelope.reservation_request_id)?,
        model_digest: envelope.reservation_model_digest.parse::<Digest32>()?,
        maximum_tokens: envelope.reservation_maximum_tokens,
        valid_until_ms: envelope.reservation_valid_until_ms,
        cancelled: envelope.reservation_cancelled,
    };

    // `execute(..., None)` is a pure pre-dispatch validation of the existing
    // request/lease/reservation contract. It must be indeterminate because no
    // physical model observation has happened yet.
    let preflight = execute(now_ms, request.clone(), lease, reservation.clone(), None)?;
    if preflight.status != TerminalStatus::Indeterminate {
        return Err("local preflight unexpectedly produced terminal success".into());
    }
    if manifest.model_digest != request.model_digest.to_string() {
        return Err("local model manifest does not match admitted request".into());
    }

    let verified_resource_grant = verify_resource_grant(
        authority,
        signed_resource_grant,
        now_ms,
        &config.worker_id,
        resource_grant,
    )?;
    let driver = LocalProcessDriver::single_model(
        config.runtime_socket,
        manifest.model_id.clone(),
        config.artifacts,
        config.timeout,
    )?;
    let mut worker = InferenceWorker::new(
        now_ms,
        config.worker_id,
        config.generation,
        verified_resource_grant,
        driver,
    )?;
    worker.load_model(now_ms, manifest.clone())?;

    let worker_request = WorkerRequest {
        request_id: request.request_id.to_string(),
        reservation_id: request.reservation_id.to_string(),
        model_digest: request.model_digest.to_string(),
        payload_digest: request.prompt_digest.to_string(),
        prompt: envelope.prompt,
        maximum_tokens: request.maximum_tokens,
        deadline_ms: request.deadline_ms,
        // The cryptographic AuthorityLease has already been validated above;
        // this local digest prevents payload drift between preflight and driver.
        lease_payload_digest: request.prompt_digest.to_string(),
        reservation_model_digest: reservation.model_digest.to_string(),
        reservation_maximum_tokens: reservation.maximum_tokens,
        cancelled: reservation.cancelled,
    };
    let observed = worker.run(now_ms, &manifest.model_id, worker_request);
    let unloaded = worker.unload_model(now_ms, &manifest.model_id);
    let observed = observed?;
    unloaded?;

    Ok(LocalProductOutput {
        request_id: observed.request_id,
        reservation_id: observed.reservation_id,
        worker_generation: observed.worker_generation,
        model_digest: observed.model_digest,
        payload_digest: observed.payload_digest,
        status: match observed.status {
            ExecutionStatus::Succeeded => LocalProductStatus::Succeeded,
            ExecutionStatus::Failed => LocalProductStatus::Failed,
            ExecutionStatus::Cancelled => LocalProductStatus::Cancelled,
            ExecutionStatus::Indeterminate => LocalProductStatus::Indeterminate,
        },
        output_digest: observed.output_digest,
        consumed_tokens: observed.consumed_tokens,
        observed_memory_bytes: observed.observed_memory_bytes,
        terminal_observed: observed.terminal_observed,
    })
}
