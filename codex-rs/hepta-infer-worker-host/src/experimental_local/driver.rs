use super::LocalFuture;
use super::LocalWorkerError;
use super::TrustedDeadline;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;
use super::validate_digest;
use super::validate_identity;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadObservation {
    pub handle_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub runtime_digest: String,
    pub device_uuid: String,
    /// Diagnostic only. Capacity decisions use the trusted observer value.
    pub driver_reported_memory_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverTerminalStatus {
    Succeeded,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub status: DriverTerminalStatus,
    pub output: Vec<u8>,
    /// `None` means unknown. It is never normalized to zero.
    pub observed_tokens: Option<u64>,
    pub usage_units: Option<u64>,
    pub stop_reason: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
    Pending {
        observed_tokens: Option<u64>,
        usage_units: Option<u64>,
    },
    Terminal(DriverRunObservation),
    MissingHistory,
    Ambiguous {
        reason: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverUnloadObservation {
    pub terminal_observed: bool,
    pub released_memory_bytes: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedResourceObservation {
    pub observer_id: String,
    pub handle_id: String,
    pub worker_generation: u64,
    pub device_uuid: String,
    pub device_epoch: u64,
    pub resident_memory_bytes: u64,
    pub transient_memory_bytes: u64,
    pub attestation_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedReleaseObservation {
    pub observer_id: String,
    pub handle_id: String,
    pub worker_generation: u64,
    pub device_uuid: String,
    pub device_epoch: u64,
    pub resident_memory_bytes: u64,
    pub attestation_digest: String,
}

pub trait LocalModelDriver: Send + Sync {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, DriverLoadObservation>;

    /// Clean up a physical load that returned a driver handle but failed before
    /// an `AttestedModelHandle` could be constructed. Implementations must use
    /// only the exact opaque handle/device tuple returned by `load` and must not
    /// start another load as part of cleanup.
    fn cleanup_failed_load<'a>(
        &'a self,
        load: &'a DriverLoadObservation,
    ) -> LocalFuture<'a, DriverUnloadObservation>;

    fn run<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        cancellation: &'a CancellationToken,
        deadline: TrustedDeadline,
    ) -> LocalFuture<'a, DriverRunObservation>;

    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation>;

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverUnloadObservation>;
}

/// Trusted OS/device observation port. A model driver cannot implement this
/// port for its own result in a production composition.
pub trait TrustedResourceObserver: Send + Sync {
    fn observe_model<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedResourceObservation>;

    /// Observe zero residency for a driver handle that could not be promoted to
    /// an `AttestedModelHandle`. This closes the load/attestation failure window
    /// without trusting the model driver to attest its own cleanup.
    fn observe_unattested_release<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedReleaseObservation>;

    fn observe_release<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, TrustedReleaseObservation>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttestedModelHandle {
    handle_id: String,
    model_id: String,
    model_digest: String,
    weights_digest: String,
    runtime_digest: String,
    device_uuid: String,
    device_epoch: u64,
    pub(super) worker_generation: u64,
    resident_memory_bytes: u64,
    manifest_semantic_digest: String,
    grant_witness_digest: String,
    resource_attestation_digest: String,
}

impl AttestedModelHandle {
    pub(super) fn attest(
        load: DriverLoadObservation,
        observed: TrustedResourceObservation,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        validate_identity(&load.handle_id, "local driver handle")?;
        validate_identity(&load.device_uuid, "local driver device")?;
        validate_identity(&observed.observer_id, "local resource observer")?;
        validate_identity(&observed.handle_id, "local observed handle")?;
        validate_identity(&observed.device_uuid, "local observed device")?;
        validate_digest(&load.model_digest, "local driver model digest")?;
        validate_digest(&load.weights_digest, "local driver weights digest")?;
        validate_digest(&load.runtime_digest, "local driver runtime digest")?;
        validate_digest(
            &observed.attestation_digest,
            "local resource attestation digest",
        )?;
        let raw = manifest.as_manifest();
        let claims = grant.claims();
        if load.handle_id != observed.handle_id
            || load.model_digest != raw.model_digest
            || load.weights_digest != raw.weights_digest
            || load.runtime_digest != raw.runtime_digest
            || load.device_uuid != raw.device_uuid
            || observed.device_uuid != raw.device_uuid
            || observed.worker_generation != claims.worker_generation
            || observed.device_epoch != claims.device_epoch
        {
            return Err(LocalWorkerError::InvalidObservation(
                "driver/resource tuple mismatch",
            ));
        }
        let observed_peak_memory = observed
            .resident_memory_bytes
            .checked_add(observed.transient_memory_bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        if observed.resident_memory_bytes == 0
            || observed_peak_memory > claims.maximum_aggregate_memory_bytes
        {
            return Err(LocalWorkerError::CapacityExceeded);
        }
        Ok(Self {
            handle_id: load.handle_id,
            model_id: raw.model_id.clone(),
            model_digest: raw.model_digest.clone(),
            weights_digest: raw.weights_digest.clone(),
            runtime_digest: raw.runtime_digest.clone(),
            device_uuid: raw.device_uuid.clone(),
            device_epoch: observed.device_epoch,
            worker_generation: observed.worker_generation,
            resident_memory_bytes: observed.resident_memory_bytes,
            manifest_semantic_digest: raw.semantic_digest.clone(),
            grant_witness_digest: grant.witness_digest().to_string(),
            resource_attestation_digest: observed.attestation_digest,
        })
    }

    pub fn handle_id(&self) -> &str {
        &self.handle_id
    }

    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    pub fn model_digest(&self) -> &str {
        &self.model_digest
    }

    pub fn device_uuid(&self) -> &str {
        &self.device_uuid
    }

    pub fn device_epoch(&self) -> u64 {
        self.device_epoch
    }

    pub fn worker_generation(&self) -> u64 {
        self.worker_generation
    }

    pub fn resident_memory_bytes(&self) -> u64 {
        self.resident_memory_bytes
    }

    pub fn manifest_semantic_digest(&self) -> &str {
        &self.manifest_semantic_digest
    }

    pub fn resource_attestation_digest(&self) -> &str {
        &self.resource_attestation_digest
    }

    pub(super) fn verify_for(
        &self,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<(), LocalWorkerError> {
        let raw = manifest.as_manifest();
        let claims = grant.claims();
        if self.model_id != raw.model_id
            || self.model_digest != raw.model_digest
            || self.weights_digest != raw.weights_digest
            || self.runtime_digest != raw.runtime_digest
            || self.device_uuid != raw.device_uuid
            || self.device_epoch != claims.device_epoch
            || self.worker_generation != claims.worker_generation
            || self.manifest_semantic_digest != raw.semantic_digest
            || self.grant_witness_digest != grant.witness_digest()
        {
            return Err(LocalWorkerError::InvalidObservation(
                "attested handle no longer matches manifest/grant",
            ));
        }
        Ok(())
    }

    #[cfg(test)]
    pub(super) fn test_fixture(
        handle_id: &str,
        worker_generation: u64,
        device_epoch: u64,
        resident_memory_bytes: u64,
    ) -> Self {
        Self {
            handle_id: handle_id.to_string(),
            model_id: "model.test".to_string(),
            model_digest: "1".repeat(64),
            weights_digest: "2".repeat(64),
            runtime_digest: "3".repeat(64),
            device_uuid: "device.test".to_string(),
            device_epoch,
            worker_generation,
            resident_memory_bytes,
            manifest_semantic_digest: "4".repeat(64),
            grant_witness_digest: "5".repeat(64),
            resource_attestation_digest: "6".repeat(64),
        }
    }
}
