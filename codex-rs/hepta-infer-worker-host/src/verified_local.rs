//! Sealed authority, deadline, driver and resource types for future local inference.
//!
//! This module is deliberately feature-gated and has no product caller. It closes
//! the type-level boundary that the legacy injected driver lacks without claiming
//! that local weights, devices, crash recovery or deployment have been qualified.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use ed25519_dalek::Signature;
use ed25519_dalek::Verifier;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use crate::model_worker::ModelManifest;

const GRANT_SCHEMA: &str = "hepta.local-inference-resource-grant.v1";
const MAX_IDENTITY_BYTES: usize = 256;
const MAX_INPUT_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedResourceGrantV1 {
    pub schema: String,
    pub issuer: String,
    pub signer_id: String,
    pub grant_id: String,
    pub nonce: String,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub worker_subject: String,
    pub worker_generation: u64,
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub device_uuid: String,
    pub device_lease_id: String,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_transient_memory_bytes: u64,
    pub maximum_concurrency: u32,
    pub maximum_tokens_per_request: u32,
    pub maximum_total_tokens: u64,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub semantic_digest: String,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RevocationSnapshot {
    pub authority_epoch: u64,
    pub revision: u64,
    pub revoked_grant_ids: BTreeSet<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReplayClaim {
    Fresh,
    SameSemanticGrant,
}

pub trait GrantReplayGuard: Send + Sync {
    /// Claim `(issuer, epoch, nonce)` durably. Reusing it with different
    /// semantics must return an error rather than replacing the old claim.
    fn claim(
        &self,
        issuer: &str,
        authority_epoch: u64,
        nonce: &str,
        semantic_digest: &str,
    ) -> Result<ReplayClaim, VerificationError>;
}

pub trait TrustedClock: Send + Sync {
    fn unix_time_ms(&self) -> Result<u64, VerificationError>;
    fn monotonic_now(&self) -> Instant;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VerificationError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidSignature,
    WrongSchema,
    WrongIssuer,
    WrongSubject,
    WrongGeneration,
    WrongAuthorityEpoch,
    StaleRevocationHead,
    Revoked,
    NotYetValid,
    Expired,
    InvalidLimit,
    SemanticDigestMismatch,
    ReplayConflict,
    ModelBindingMismatch,
    InputBindingMismatch,
    DeadlineExpired,
    ArithmeticOverflow,
    ResourceCapacity,
    GenerationFenced,
    Driver(String),
}

#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    value: SignedResourceGrantV1,
}

impl VerifiedResourceGrant {
    pub fn grant_id(&self) -> &str {
        &self.value.grant_id
    }

    pub fn worker_subject(&self) -> &str {
        &self.value.worker_subject
    }

    pub fn worker_generation(&self) -> u64 {
        self.value.worker_generation
    }

    pub fn maximum_aggregate_memory_bytes(&self) -> u64 {
        self.value.maximum_aggregate_memory_bytes
    }

    pub fn maximum_transient_memory_bytes(&self) -> u64 {
        self.value.maximum_transient_memory_bytes
    }

    pub fn maximum_concurrency(&self) -> u32 {
        self.value.maximum_concurrency
    }

    pub fn expires_at_unix_ms(&self) -> u64 {
        self.value.expires_at_unix_ms
    }
}

pub struct ResourceGrantVerifier<G: GrantReplayGuard, C: TrustedClock> {
    expected_issuer: String,
    expected_signer_id: String,
    expected_subject: String,
    expected_generation: u64,
    verifying_key: VerifyingKey,
    revocations: RevocationSnapshot,
    replay_guard: G,
    clock: C,
}

impl<G: GrantReplayGuard, C: TrustedClock> ResourceGrantVerifier<G, C> {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        expected_issuer: String,
        expected_signer_id: String,
        expected_subject: String,
        expected_generation: u64,
        verifying_key: [u8; 32],
        revocations: RevocationSnapshot,
        replay_guard: G,
        clock: C,
    ) -> Result<Self, VerificationError> {
        validate_identity(&expected_issuer, "issuer")?;
        validate_identity(&expected_signer_id, "signer")?;
        validate_identity(&expected_subject, "subject")?;
        if expected_generation == 0 || revocations.authority_epoch == 0 {
            return Err(VerificationError::InvalidLimit);
        }
        let verifying_key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| VerificationError::InvalidSignature)?;
        Ok(Self {
            expected_issuer,
            expected_signer_id,
            expected_subject,
            expected_generation,
            verifying_key,
            revocations,
            replay_guard,
            clock,
        })
    }

    pub fn verify(
        &self,
        candidate: SignedResourceGrantV1,
    ) -> Result<VerifiedResourceGrant, VerificationError> {
        validate_grant_shape(&candidate)?;
        if candidate.schema != GRANT_SCHEMA {
            return Err(VerificationError::WrongSchema);
        }
        if candidate.issuer != self.expected_issuer
            || candidate.signer_id != self.expected_signer_id
        {
            return Err(VerificationError::WrongIssuer);
        }
        if candidate.worker_subject != self.expected_subject {
            return Err(VerificationError::WrongSubject);
        }
        if candidate.worker_generation != self.expected_generation {
            return Err(VerificationError::WrongGeneration);
        }
        if candidate.authority_epoch != self.revocations.authority_epoch {
            return Err(VerificationError::WrongAuthorityEpoch);
        }
        if candidate.revocation_revision > self.revocations.revision {
            return Err(VerificationError::StaleRevocationHead);
        }
        if self.revocations.revoked_grant_ids.contains(&candidate.grant_id) {
            return Err(VerificationError::Revoked);
        }
        let now = self.clock.unix_time_ms()?;
        if now < candidate.not_before_unix_ms {
            return Err(VerificationError::NotYetValid);
        }
        if now >= candidate.expires_at_unix_ms {
            return Err(VerificationError::Expired);
        }
        let semantics = grant_semantic_bytes(&candidate)?;
        let expected_digest = hex_digest(&semantics);
        if candidate.semantic_digest != expected_digest {
            return Err(VerificationError::SemanticDigestMismatch);
        }
        let signature_bytes: [u8; 64] = candidate
            .signature
            .as_slice()
            .try_into()
            .map_err(|_| VerificationError::InvalidSignature)?;
        let signature = Signature::from_bytes(&signature_bytes);
        self.verifying_key
            .verify(&semantics, &signature)
            .map_err(|_| VerificationError::InvalidSignature)?;
        match self.replay_guard.claim(
            &candidate.issuer,
            candidate.authority_epoch,
            &candidate.nonce,
            &candidate.semantic_digest,
        )? {
            ReplayClaim::Fresh | ReplayClaim::SameSemanticGrant => {}
        }
        Ok(VerifiedResourceGrant { value: candidate })
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedModelManifest {
    value: ModelManifest,
}

impl VerifiedModelManifest {
    pub fn bind(
        manifest: ModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, VerificationError> {
        let expected = &grant.value;
        if manifest.model_id != expected.model_id
            || manifest.model_digest != expected.model_digest
            || manifest.weights_digest != expected.weights_digest
            || manifest.tokenizer_digest != expected.tokenizer_digest
            || manifest.preprocessor_digest != expected.preprocessor_digest
            || manifest.quantization_digest != expected.quantization_digest
            || manifest.runtime_digest != expected.runtime_digest
            || manifest.device_digest != expected.device_digest
            || manifest.maximum_tokens > expected.maximum_tokens_per_request
        {
            return Err(VerificationError::ModelBindingMismatch);
        }
        Ok(Self { value: manifest })
    }

    pub fn value(&self) -> &ModelManifest {
        &self.value
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedInput {
    bytes: Arc<[u8]>,
    digest: String,
}

impl VerifiedInput {
    pub fn bind(bytes: Vec<u8>, expected_digest: &str) -> Result<Self, VerificationError> {
        if bytes.is_empty() || bytes.len() > MAX_INPUT_BYTES {
            return Err(VerificationError::InputBindingMismatch);
        }
        validate_digest(expected_digest, "input")?;
        let digest = hex_digest(&bytes);
        if digest != expected_digest {
            return Err(VerificationError::InputBindingMismatch);
        }
        Ok(Self {
            bytes: Arc::from(bytes),
            digest,
        })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }
}

#[derive(Clone, Debug)]
pub struct TrustedDeadline {
    absolute_unix_ms: u64,
    monotonic: Instant,
}

impl TrustedDeadline {
    pub fn bind<C: TrustedClock>(
        clock: &C,
        grant: &VerifiedResourceGrant,
        requested_unix_ms: u64,
    ) -> Result<Self, VerificationError> {
        let now_unix_ms = clock.unix_time_ms()?;
        let absolute_unix_ms = requested_unix_ms.min(grant.value.expires_at_unix_ms);
        let remaining = absolute_unix_ms
            .checked_sub(now_unix_ms)
            .filter(|remaining| *remaining != 0)
            .ok_or(VerificationError::DeadlineExpired)?;
        let monotonic = clock
            .monotonic_now()
            .checked_add(Duration::from_millis(remaining))
            .ok_or(VerificationError::ArithmeticOverflow)?;
        Ok(Self {
            absolute_unix_ms,
            monotonic,
        })
    }

    pub fn absolute_unix_ms(&self) -> u64 {
        self.absolute_unix_ms
    }

    pub fn monotonic(&self) -> Instant {
        self.monotonic
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
    Present,
    Released,
    Running,
    Terminal,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub output_digest: Option<String>,
    pub observed_tokens: Option<u64>,
    pub resident_memory_bytes: u64,
    pub transient_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnloadObservation {
    pub released: bool,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug)]
pub struct OperationId(String);

impl OperationId {
    pub fn parse(value: String) -> Result<Self, VerificationError> {
        validate_identity(&value, "operation")?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HandleLifecycle {
    Ready,
    RepairRequired,
}

#[derive(Debug)]
pub struct AttestedModelHandle {
    opaque_id: String,
    manifest_digest: String,
    device_uuid: String,
    device_lease_id: String,
    lifecycle: HandleLifecycle,
    lease: Option<ResourceLease>,
}

impl AttestedModelHandle {
    pub fn opaque_id(&self) -> &str {
        &self.opaque_id
    }

    pub fn lifecycle(&self) -> HandleLifecycle {
        self.lifecycle
    }

    pub fn mark_repair_required(&mut self) {
        self.lifecycle = HandleLifecycle::RepairRequired;
    }

    pub fn manifest_digest(&self) -> &str {
        &self.manifest_digest
    }

    pub fn device_uuid(&self) -> &str {
        &self.device_uuid
    }

    pub fn device_lease_id(&self) -> &str {
        &self.device_lease_id
    }

    /// Consume the handle only after a trusted terminal unload observation.
    pub fn release_after_observed_unload(
        mut self,
        observation: &UnloadObservation,
    ) -> Result<(), VerificationError> {
        if !observation.terminal_observed || !observation.released {
            self.lifecycle = HandleLifecycle::RepairRequired;
            return Err(VerificationError::Driver(
                "unload was not terminally observed".to_string(),
            ));
        }
        self.lease.take();
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct ResourceManager {
    state: Arc<Mutex<ResourceState>>,
}

#[derive(Debug)]
struct ResourceState {
    generation: u64,
    maximum_resident_bytes: u64,
    maximum_transient_bytes: u64,
    maximum_in_flight: u32,
    resident_bytes: u64,
    reserved_resident_bytes: u64,
    transient_bytes: u64,
    in_flight: u32,
    fenced: bool,
}

impl ResourceManager {
    pub fn new(grant: &VerifiedResourceGrant) -> Result<Self, VerificationError> {
        Ok(Self {
            state: Arc::new(Mutex::new(ResourceState {
                generation: grant.value.worker_generation,
                maximum_resident_bytes: grant.value.maximum_aggregate_memory_bytes,
                maximum_transient_bytes: grant.value.maximum_transient_memory_bytes,
                maximum_in_flight: grant.value.maximum_concurrency,
                resident_bytes: 0,
                reserved_resident_bytes: 0,
                transient_bytes: 0,
                in_flight: 0,
                fenced: false,
            })),
        })
    }

    pub fn reserve_load(
        &self,
        generation: u64,
        maximum_resident_bytes: u64,
    ) -> Result<LoadReservation, VerificationError> {
        if maximum_resident_bytes == 0 {
            return Err(VerificationError::InvalidLimit);
        }
        let mut state = self.state.lock().map_err(|_| {
            VerificationError::Driver("resource manager lock poisoned".to_string())
        })?;
        validate_resource_generation(&state, generation)?;
        let total = state
            .resident_bytes
            .checked_add(state.reserved_resident_bytes)
            .and_then(|value| value.checked_add(maximum_resident_bytes))
            .ok_or(VerificationError::ArithmeticOverflow)?;
        if total > state.maximum_resident_bytes {
            return Err(VerificationError::ResourceCapacity);
        }
        state.reserved_resident_bytes = state
            .reserved_resident_bytes
            .checked_add(maximum_resident_bytes)
            .ok_or(VerificationError::ArithmeticOverflow)?;
        Ok(LoadReservation {
            state: Arc::clone(&self.state),
            generation,
            maximum_resident_bytes,
            committed: false,
        })
    }

    pub fn reserve_run(
        &self,
        generation: u64,
        transient_bytes: u64,
    ) -> Result<RunReservation, VerificationError> {
        let mut state = self.state.lock().map_err(|_| {
            VerificationError::Driver("resource manager lock poisoned".to_string())
        })?;
        validate_resource_generation(&state, generation)?;
        let next_in_flight = state
            .in_flight
            .checked_add(1)
            .ok_or(VerificationError::ArithmeticOverflow)?;
        let next_transient = state
            .transient_bytes
            .checked_add(transient_bytes)
            .ok_or(VerificationError::ArithmeticOverflow)?;
        if next_in_flight > state.maximum_in_flight
            || next_transient > state.maximum_transient_bytes
        {
            return Err(VerificationError::ResourceCapacity);
        }
        state.in_flight = next_in_flight;
        state.transient_bytes = next_transient;
        Ok(RunReservation {
            state: Arc::clone(&self.state),
            generation,
            transient_bytes,
            released: false,
        })
    }

    pub fn fence_generation(&self, generation: u64) -> Result<(), VerificationError> {
        let mut state = self.state.lock().map_err(|_| {
            VerificationError::Driver("resource manager lock poisoned".to_string())
        })?;
        if state.generation != generation {
            return Err(VerificationError::WrongGeneration);
        }
        state.fenced = true;
        Ok(())
    }
}

#[derive(Debug)]
pub struct LoadReservation {
    state: Arc<Mutex<ResourceState>>,
    generation: u64,
    maximum_resident_bytes: u64,
    committed: bool,
}

impl LoadReservation {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn commit(
        mut self,
        opaque_id: String,
        manifest_digest: String,
        device_uuid: String,
        device_lease_id: String,
        observed_resident_bytes: u64,
    ) -> Result<AttestedModelHandle, VerificationError> {
        validate_identity(&opaque_id, "handle")?;
        validate_digest(&manifest_digest, "manifest")?;
        validate_identity(&device_uuid, "device uuid")?;
        validate_identity(&device_lease_id, "device lease")?;
        if observed_resident_bytes == 0
            || observed_resident_bytes > self.maximum_resident_bytes
        {
            return Err(VerificationError::ResourceCapacity);
        }
        let mut state = self.state.lock().map_err(|_| {
            VerificationError::Driver("resource manager lock poisoned".to_string())
        })?;
        validate_resource_generation(&state, self.generation)?;
        state.reserved_resident_bytes = state
            .reserved_resident_bytes
            .checked_sub(self.maximum_resident_bytes)
            .ok_or(VerificationError::ArithmeticOverflow)?;
        state.resident_bytes = state
            .resident_bytes
            .checked_add(observed_resident_bytes)
            .ok_or(VerificationError::ArithmeticOverflow)?;
        self.committed = true;
        Ok(AttestedModelHandle {
            opaque_id,
            manifest_digest,
            device_uuid,
            device_lease_id,
            lifecycle: HandleLifecycle::Ready,
            lease: Some(ResourceLease {
                state: Arc::clone(&self.state),
                generation: self.generation,
                resident_bytes: observed_resident_bytes,
            }),
        })
    }
}

impl Drop for LoadReservation {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        if let Ok(mut state) = self.state.lock() {
            if state.generation == self.generation {
                state.reserved_resident_bytes = state
                    .reserved_resident_bytes
                    .checked_sub(self.maximum_resident_bytes)
                    .unwrap_or(0);
                if state.reserved_resident_bytes == 0 && self.maximum_resident_bytes != 0 {
                    // A poisoned accounting transition fences new work instead
                    // of silently manufacturing capacity.
                    state.fenced |= self.maximum_resident_bytes > state.maximum_resident_bytes;
                }
            }
        }
    }
}

#[derive(Debug)]
struct ResourceLease {
    state: Arc<Mutex<ResourceState>>,
    generation: u64,
    resident_bytes: u64,
}

impl Drop for ResourceLease {
    fn drop(&mut self) {
        if let Ok(mut state) = self.state.lock() {
            if state.generation == self.generation {
                match state.resident_bytes.checked_sub(self.resident_bytes) {
                    Some(value) => state.resident_bytes = value,
                    None => state.fenced = true,
                }
            }
        }
    }
}

#[derive(Debug)]
pub struct RunReservation {
    state: Arc<Mutex<ResourceState>>,
    generation: u64,
    transient_bytes: u64,
    released: bool,
}

impl RunReservation {
    pub fn release(mut self) {
        self.release_inner();
    }

    fn release_inner(&mut self) {
        if self.released {
            return;
        }
        if let Ok(mut state) = self.state.lock() {
            if state.generation == self.generation {
                match (
                    state.in_flight.checked_sub(1),
                    state.transient_bytes.checked_sub(self.transient_bytes),
                ) {
                    (Some(in_flight), Some(transient)) => {
                        state.in_flight = in_flight;
                        state.transient_bytes = transient;
                    }
                    _ => state.fenced = true,
                }
            }
        }
        self.released = true;
    }
}

impl Drop for RunReservation {
    fn drop(&mut self) {
        self.release_inner();
    }
}

pub type DriverFuture<'a, T> = Pin<
    Box<dyn Future<Output = Result<T, VerificationError>> + Send + 'a>,
>;

mod sealed {
    pub trait Sealed {}
}

/// Production implementations are crate-owned so callers cannot substitute an
/// arbitrary fake driver and still obtain an attested handle type.
pub trait LocalModelDriver: sealed::Sealed + Send + Sync {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
        reservation: LoadReservation,
    ) -> DriverFuture<'a, AttestedModelHandle>;

    fn run<'a>(
        &'a self,
        operation_id: &'a OperationId,
        handle: &'a AttestedModelHandle,
        input: VerifiedInput,
        cancellation: CancellationToken,
        deadline: TrustedDeadline,
        reservation: RunReservation,
    ) -> DriverFuture<'a, ExecutionObservation>;

    fn inspect<'a>(
        &'a self,
        operation_id: &'a OperationId,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, DriverReconciliation>;

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, UnloadObservation>;
}

pub(crate) use sealed::Sealed as LocalModelDriverSealed;

fn validate_resource_generation(
    state: &ResourceState,
    generation: u64,
) -> Result<(), VerificationError> {
    if state.generation != generation {
        return Err(VerificationError::WrongGeneration);
    }
    if state.fenced {
        return Err(VerificationError::GenerationFenced);
    }
    Ok(())
}

fn validate_grant_shape(value: &SignedResourceGrantV1) -> Result<(), VerificationError> {
    for (identity, field) in [
        (&value.issuer, "issuer"),
        (&value.signer_id, "signer"),
        (&value.grant_id, "grant"),
        (&value.nonce, "nonce"),
        (&value.worker_subject, "subject"),
        (&value.model_id, "model"),
        (&value.device_uuid, "device uuid"),
        (&value.device_lease_id, "device lease"),
    ] {
        validate_identity(identity, field)?;
    }
    for (digest, field) in [
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.device_digest, "device"),
        (&value.semantic_digest, "semantic"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.authority_epoch == 0
        || value.worker_generation == 0
        || value.maximum_aggregate_memory_bytes == 0
        || value.maximum_transient_memory_bytes == 0
        || value.maximum_concurrency == 0
        || value.maximum_tokens_per_request == 0
        || value.maximum_total_tokens == 0
        || value.not_before_unix_ms >= value.expires_at_unix_ms
    {
        return Err(VerificationError::InvalidLimit);
    }
    Ok(())
}

fn grant_semantic_bytes(value: &SignedResourceGrantV1) -> Result<Vec<u8>, VerificationError> {
    #[derive(Serialize)]
    struct SemanticGrant<'a> {
        schema: &'a str,
        issuer: &'a str,
        signer_id: &'a str,
        grant_id: &'a str,
        nonce: &'a str,
        authority_epoch: u64,
        revocation_revision: u64,
        worker_subject: &'a str,
        worker_generation: u64,
        model_id: &'a str,
        model_digest: &'a str,
        weights_digest: &'a str,
        tokenizer_digest: &'a str,
        preprocessor_digest: &'a str,
        quantization_digest: &'a str,
        runtime_digest: &'a str,
        device_digest: &'a str,
        device_uuid: &'a str,
        device_lease_id: &'a str,
        maximum_aggregate_memory_bytes: u64,
        maximum_transient_memory_bytes: u64,
        maximum_concurrency: u32,
        maximum_tokens_per_request: u32,
        maximum_total_tokens: u64,
        not_before_unix_ms: u64,
        expires_at_unix_ms: u64,
    }
    serde_json::to_vec(&SemanticGrant {
        schema: &value.schema,
        issuer: &value.issuer,
        signer_id: &value.signer_id,
        grant_id: &value.grant_id,
        nonce: &value.nonce,
        authority_epoch: value.authority_epoch,
        revocation_revision: value.revocation_revision,
        worker_subject: &value.worker_subject,
        worker_generation: value.worker_generation,
        model_id: &value.model_id,
        model_digest: &value.model_digest,
        weights_digest: &value.weights_digest,
        tokenizer_digest: &value.tokenizer_digest,
        preprocessor_digest: &value.preprocessor_digest,
        quantization_digest: &value.quantization_digest,
        runtime_digest: &value.runtime_digest,
        device_digest: &value.device_digest,
        device_uuid: &value.device_uuid,
        device_lease_id: &value.device_lease_id,
        maximum_aggregate_memory_bytes: value.maximum_aggregate_memory_bytes,
        maximum_transient_memory_bytes: value.maximum_transient_memory_bytes,
        maximum_concurrency: value.maximum_concurrency,
        maximum_tokens_per_request: value.maximum_tokens_per_request,
        maximum_total_tokens: value.maximum_total_tokens,
        not_before_unix_ms: value.not_before_unix_ms,
        expires_at_unix_ms: value.expires_at_unix_ms,
    })
    .map_err(|error| VerificationError::Driver(error.to_string()))
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), VerificationError> {
    if value.is_empty()
        || value.len() > MAX_IDENTITY_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(VerificationError::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), VerificationError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(VerificationError::InvalidDigest(field));
    }
    Ok(())
}

fn hex_digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
