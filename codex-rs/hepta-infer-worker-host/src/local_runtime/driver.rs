use std::future::Future;
use std::pin::Pin;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use super::LocalRuntimeError;
use super::TrustedDeadline;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;

pub type DriverFuture<'a, T> = Pin<
    Box<dyn Future<Output = Result<T, LocalRuntimeError>> + Send + 'a>,
>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadedModel {
    pub opaque_id: StableId,
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub device_id: StableId,
    pub worker_generation: Generation,
    /// Driver-reported memory is diagnostic only. Resource admission uses the
    /// independently observed value returned by `TrustedDeviceAuthority`.
    pub driver_reported_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeviceVerification {
    pub opaque_id: StableId,
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub device_id: StableId,
    pub worker_generation: Generation,
    pub observed_memory_bytes: u64,
    pub attestation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedMemoryObservation {
    pub device_id: StableId,
    pub worker_generation: Generation,
    pub observed_total_bytes: u64,
    pub witness_digest: Digest32,
}

pub trait TrustedDeviceAuthority: Send + Sync {
    fn verify_loaded_model(
        &self,
        loaded: &DriverLoadedModel,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<DeviceVerification, LocalRuntimeError>;

    fn observe_total_memory(
        &self,
        device_id: &StableId,
        generation: Generation,
    ) -> Result<TrustedMemoryObservation, LocalRuntimeError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttestedModelHandle {
    opaque_id: StableId,
    model_id: StableId,
    model_digest: Digest32,
    device_id: StableId,
    worker_generation: Generation,
    observed_memory_bytes: u64,
    attestation_digest: Digest32,
}

impl AttestedModelHandle {
    pub(crate) fn from_verification(
        value: DeviceVerification,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalRuntimeError> {
        if value.model_id != manifest.claims().model_id
            || value.model_digest != manifest.claims().model_digest
            || value.device_id != manifest.claims().device_id
            || value.device_id != grant.claims().device_id
            || value.worker_generation != grant.claims().worker_generation
            || value.observed_memory_bytes == 0
            || value.observed_memory_bytes > grant.claims().maximum_aggregate_memory_bytes
            || value.attestation_digest.is_zero()
        {
            return Err(LocalRuntimeError::Device(
                "loaded-model attestation does not match the verified tuple".to_string(),
            ));
        }
        Ok(Self {
            opaque_id: value.opaque_id,
            model_id: value.model_id,
            model_digest: value.model_digest,
            device_id: value.device_id,
            worker_generation: value.worker_generation,
            observed_memory_bytes: value.observed_memory_bytes,
            attestation_digest: value.attestation_digest,
        })
    }

    pub fn opaque_id(&self) -> &StableId {
        &self.opaque_id
    }

    pub fn model_id(&self) -> &StableId {
        &self.model_id
    }

    pub fn model_digest(&self) -> Digest32 {
        self.model_digest
    }

    pub fn device_id(&self) -> &StableId {
        &self.device_id
    }

    pub fn worker_generation(&self) -> Generation {
        self.worker_generation
    }

    pub fn observed_memory_bytes(&self) -> u64 {
        self.observed_memory_bytes
    }

    pub fn attestation_digest(&self) -> Digest32 {
        self.attestation_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverTerminalStatus {
    Completed,
    Failed,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TokenUsage {
    Unknown,
    Observed {
        consumed_tokens: u32,
        usage_units: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub terminal_status: Option<DriverTerminalStatus>,
    pub output_digest: Option<Digest32>,
    pub usage: TokenUsage,
    pub observed_memory_bytes: u64,
    pub observation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
    NotFound,
    Running,
    Ambiguous { reason: String },
    Terminal(DriverRunObservation),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnloadObservation {
    pub terminal_observed: bool,
    pub released_memory_bytes: u64,
    pub observation_digest: Digest32,
}

/// Physical local-model driver boundary.
///
/// Implementations may report raw handles, but those handles are unusable until
/// the independently configured `TrustedDeviceAuthority` attests the exact
/// model/device/generation tuple. Every method is asynchronous and receives a
/// live cancellation/deadline boundary where applicable.
pub trait LocalModelDriver: Send + Sync {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadedModel>;

    fn run<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        cancellation: &'a CancellationToken,
        deadline: &'a TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunObservation>;

    fn inspect<'a>(
        &'a self,
        operation_id: &'a StableId,
    ) -> DriverFuture<'a, DriverReconciliation>;

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, UnloadObservation>;

    /// Best-effort cleanup for a raw load that failed independent attestation.
    /// Failure remains visible to the caller and must not be treated as release.
    fn discard_unattested<'a>(
        &'a self,
        loaded: DriverLoadedModel,
    ) -> DriverFuture<'a, UnloadObservation>;
}
