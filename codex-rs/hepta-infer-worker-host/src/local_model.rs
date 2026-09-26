//! Experimental local-model execution with sealed authority, aggregate resource
//! accounting and durable no-replay semantics.
//!
//! This module is available only with `experimental-local-model`. Verified
//! grants, manifests, deadlines and handles have private construction paths.
//! The profile remains non-production until target hardware and independent
//! acceptance are recorded.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::Assignment as ControlAssignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::InferenceRequest as ControlRequest;
use codex_hepta_infer_core::durable_control::RequestRecord;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation as ControlReservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use sha2::Digest;
use sha2::Sha256;
use tokio::sync::Mutex as AsyncMutex;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

const MAX_INPUT_BYTES: usize = 32 * 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;
const MAX_ID_BYTES: usize = 128;
const RESOURCE_GRANT_DOMAIN: &[u8] = b"hepta.local-model-resource-grant.v1";
const MODEL_MANIFEST_DOMAIN: &[u8] = b"hepta.local-model-manifest.v1";
const LOCAL_REQUEST_DOMAIN: &[u8] = b"hepta.local-model-request.v1";

pub type DriverFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, LocalModelError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalModelError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGrant,
    InvalidManifest,
    InvalidInput,
    InvalidDeadline,
    InvalidSignature,
    GrantExpired,
    GrantNotYetValid,
    GrantRevoked,
    AuthorityEpochMismatch,
    RevocationRollback,
    WorkerBindingMismatch,
    ModelBindingMismatch,
    DeviceBindingMismatch,
    ResourceCapacity,
    ResourceFenced,
    ResourceState,
    ModelAlreadyLoaded,
    ModelNotLoaded,
    Driver(String),
    Observer(String),
    Control(String),
    UsageExceeded,
    ObservationMismatch,
    ArithmeticOverflow,
    LockPoisoned,
}

impl fmt::Display for LocalModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LocalModelError {}

impl From<ControlError> for LocalModelError {
    fn from(value: ControlError) -> Self {
        Self::Control(value.to_string())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceGrantClaimsV1 {
    pub issuer_id: String,
    pub grant_id: String,
    pub nonce: String,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: String,
    pub issued_at_ms: u64,
    pub not_before_ms: u64,
    pub expires_at_ms: u64,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_lease_id: String,
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_transient_memory_bytes: u64,
    pub maximum_concurrent_requests: usize,
    pub maximum_tokens_per_request: u32,
    pub maximum_usage_units: u64,
    pub semantic_digest: String,
}

impl ResourceGrantClaimsV1 {
    #[must_use]
    pub fn with_computed_semantic_digest(mut self) -> Self {
        self.semantic_digest = digest(&self.semantic_bytes());
        self
    }

    #[must_use]
    pub fn computed_semantic_digest(&self) -> String {
        digest(&self.semantic_bytes())
    }

    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESOURCE_GRANT_DOMAIN);
        bytes.extend_from_slice(&self.semantic_bytes());
        push_string(&mut bytes, &self.semantic_digest);
        bytes
    }

    fn semantic_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        for value in [
            &self.issuer_id,
            &self.grant_id,
            &self.nonce,
            &self.revocation_head_digest,
            &self.worker_id,
            &self.model_id,
            &self.model_digest,
            &self.weights_digest,
            &self.tokenizer_digest,
            &self.preprocessor_digest,
            &self.quantization_digest,
            &self.runtime_digest,
            &self.device_id,
            &self.device_lease_id,
        ] {
            push_string(&mut bytes, value);
        }
        for value in [
            self.authority_epoch,
            self.revocation_revision,
            self.issued_at_ms,
            self.not_before_ms,
            self.expires_at_ms,
            self.worker_generation,
            self.maximum_aggregate_memory_bytes,
            self.maximum_transient_memory_bytes,
            u64::try_from(self.maximum_concurrent_requests).unwrap_or(u64::MAX),
            u64::from(self.maximum_tokens_per_request),
            self.maximum_usage_units,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedResourceGrantV1 {
    pub claims: ResourceGrantClaimsV1,
    pub signature: [u8; 64],
}

#[derive(Clone, Debug)]
pub struct ResourceGrantVerifier {
    issuer_id: String,
    verifying_key: VerifyingKey,
    state: Arc<Mutex<AuthorityState>>,
}

#[derive(Debug)]
struct AuthorityState {
    authority_epoch: u64,
    revocation_revision: u64,
    revocation_head_digest: String,
    revoked_grant_ids: BTreeSet<String>,
}

impl ResourceGrantVerifier {
    pub fn new(
        issuer_id: String,
        verifying_key: [u8; 32],
        authority_epoch: u64,
        revocation_revision: u64,
        revocation_head_digest: String,
        revoked_grant_ids: BTreeSet<String>,
    ) -> Result<Self, LocalModelError> {
        validate_identity(&issuer_id, "issuer")?;
        validate_digest(&revocation_head_digest, "revocation head")?;
        if authority_epoch == 0 {
            return Err(LocalModelError::InvalidGrant);
        }
        let verifying_key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| LocalModelError::InvalidSignature)?;
        if verifying_key.is_weak() {
            return Err(LocalModelError::InvalidSignature);
        }
        Ok(Self {
            issuer_id,
            verifying_key,
            state: Arc::new(Mutex::new(AuthorityState {
                authority_epoch,
                revocation_revision,
                revocation_head_digest,
                revoked_grant_ids,
            })),
        })
    }

    pub fn update_revocations(
        &self,
        authority_epoch: u64,
        revision: u64,
        head_digest: String,
        revoked_grant_ids: BTreeSet<String>,
    ) -> Result<(), LocalModelError> {
        validate_digest(&head_digest, "revocation head")?;
        let mut state = self.state.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        if authority_epoch != state.authority_epoch || revision < state.revocation_revision {
            return Err(LocalModelError::RevocationRollback);
        }
        if revision == state.revocation_revision
            && (head_digest != state.revocation_head_digest
                || revoked_grant_ids != state.revoked_grant_ids)
        {
            return Err(LocalModelError::RevocationRollback);
        }
        state.revocation_revision = revision;
        state.revocation_head_digest = head_digest;
        state.revoked_grant_ids = revoked_grant_ids;
        Ok(())
    }

    pub fn verify(
        &self,
        now_ms: u64,
        worker_id: &str,
        worker_generation: u64,
        signed: &SignedResourceGrantV1,
    ) -> Result<VerifiedResourceGrant, LocalModelError> {
        validate_grant_claims(&signed.claims)?;
        if signed.claims.issuer_id != self.issuer_id {
            return Err(LocalModelError::InvalidSignature);
        }
        {
            let state = self.state.lock().map_err(|_| LocalModelError::LockPoisoned)?;
            if signed.claims.authority_epoch != state.authority_epoch {
                return Err(LocalModelError::AuthorityEpochMismatch);
            }
            if signed.claims.revocation_revision != state.revocation_revision
                || signed.claims.revocation_head_digest != state.revocation_head_digest
            {
                return Err(LocalModelError::RevocationRollback);
            }
            if state.revoked_grant_ids.contains(&signed.claims.grant_id) {
                return Err(LocalModelError::GrantRevoked);
            }
        }
        if signed.claims.worker_id != worker_id
            || signed.claims.worker_generation != worker_generation
        {
            return Err(LocalModelError::WorkerBindingMismatch);
        }
        if now_ms < signed.claims.not_before_ms {
            return Err(LocalModelError::GrantNotYetValid);
        }
        if now_ms >= signed.claims.expires_at_ms {
            return Err(LocalModelError::GrantExpired);
        }
        if signed.claims.computed_semantic_digest() != signed.claims.semantic_digest {
            return Err(LocalModelError::InvalidGrant);
        }
        self.verifying_key
            .verify_strict(
                &signed.claims.signing_bytes(),
                &Signature::from_bytes(&signed.signature),
            )
            .map_err(|_| LocalModelError::InvalidSignature)?;
        let mut witness = signed.claims.signing_bytes();
        witness.extend_from_slice(&signed.signature);
        Ok(VerifiedResourceGrant {
            claims: signed.claims.clone(),
            witness_digest: digest(&witness),
            authority_state: Arc::clone(&self.state),
        })
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    claims: ResourceGrantClaimsV1,
    witness_digest: String,
    authority_state: Arc<Mutex<AuthorityState>>,
}

impl VerifiedResourceGrant {
    #[must_use]
    pub fn claims(&self) -> &ResourceGrantClaimsV1 {
        &self.claims
    }

    #[must_use]
    pub fn witness_digest(&self) -> &str {
        &self.witness_digest
    }

    fn validate_current(&self, now_ms: u64) -> Result<(), LocalModelError> {
        if now_ms < self.claims.not_before_ms {
            return Err(LocalModelError::GrantNotYetValid);
        }
        if now_ms >= self.claims.expires_at_ms {
            return Err(LocalModelError::GrantExpired);
        }
        let state = self
            .authority_state
            .lock()
            .map_err(|_| LocalModelError::LockPoisoned)?;
        if state.authority_epoch != self.claims.authority_epoch
            || state.revocation_revision < self.claims.revocation_revision
        {
            return Err(LocalModelError::RevocationRollback);
        }
        if state.revoked_grant_ids.contains(&self.claims.grant_id) {
            return Err(LocalModelError::GrantRevoked);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifestV1 {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_lease_id: String,
    pub declared_weight_bytes: u64,
    pub maximum_tokens: u32,
    pub semantic_digest: String,
}

impl ModelManifestV1 {
    #[must_use]
    pub fn with_computed_semantic_digest(mut self) -> Self {
        self.semantic_digest = digest(&self.semantic_bytes());
        self
    }

    #[must_use]
    pub fn computed_semantic_digest(&self) -> String {
        digest(&self.semantic_bytes())
    }

    fn semantic_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MODEL_MANIFEST_DOMAIN);
        for value in [
            &self.model_id,
            &self.model_digest,
            &self.weights_digest,
            &self.tokenizer_digest,
            &self.preprocessor_digest,
            &self.quantization_digest,
            &self.runtime_digest,
            &self.device_id,
            &self.device_lease_id,
        ] {
            push_string(&mut bytes, value);
        }
        bytes.extend_from_slice(&self.declared_weight_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_tokens.to_be_bytes());
        bytes
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedModelManifest {
    manifest: ModelManifestV1,
}

impl VerifiedModelManifest {
    pub fn verify(
        manifest: ModelManifestV1,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalModelError> {
        validate_manifest(&manifest)?;
        let claims = grant.claims();
        if manifest.model_id != claims.model_id
            || manifest.model_digest != claims.model_digest
            || manifest.weights_digest != claims.weights_digest
            || manifest.tokenizer_digest != claims.tokenizer_digest
            || manifest.preprocessor_digest != claims.preprocessor_digest
            || manifest.quantization_digest != claims.quantization_digest
            || manifest.runtime_digest != claims.runtime_digest
        {
            return Err(LocalModelError::ModelBindingMismatch);
        }
        if manifest.device_id != claims.device_id
            || manifest.device_lease_id != claims.device_lease_id
        {
            return Err(LocalModelError::DeviceBindingMismatch);
        }
        if manifest.maximum_tokens > claims.maximum_tokens_per_request
            || manifest.declared_weight_bytes > claims.maximum_aggregate_memory_bytes
        {
            return Err(LocalModelError::ResourceCapacity);
        }
        if manifest.computed_semantic_digest() != manifest.semantic_digest {
            return Err(LocalModelError::InvalidManifest);
        }
        Ok(Self { manifest })
    }

    #[must_use]
    pub fn manifest(&self) -> &ModelManifestV1 {
        &self.manifest
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedInput {
    bytes: Arc<[u8]>,
    digest: String,
}

impl VerifiedInput {
    pub fn verify(
        bytes: Vec<u8>,
        expected_digest: &str,
        maximum_bytes: usize,
    ) -> Result<Self, LocalModelError> {
        if bytes.is_empty()
            || bytes.len() > maximum_bytes.min(MAX_INPUT_BYTES)
            || digest(&bytes) != expected_digest
        {
            return Err(LocalModelError::InvalidInput);
        }
        validate_digest(expected_digest, "input")?;
        Ok(Self {
            bytes: Arc::from(bytes),
            digest: expected_digest.to_string(),
        })
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn digest(&self) -> &str {
        &self.digest
    }
}

pub trait TrustedClock: Send + Sync {
    fn now_ms(&self) -> Result<u64, LocalModelError>;
}

#[derive(Debug, Default)]
pub struct SystemTrustedClock;

impl TrustedClock for SystemTrustedClock {
    fn now_ms(&self) -> Result<u64, LocalModelError> {
        let value = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| LocalModelError::InvalidDeadline)?
            .as_millis();
        u64::try_from(value).map_err(|_| LocalModelError::InvalidDeadline)
    }
}

#[derive(Clone, Debug)]
pub struct TrustedDeadline {
    deadline_ms: u64,
    instant: Instant,
}

impl TrustedDeadline {
    pub fn verify(
        clock: &dyn TrustedClock,
        deadline_ms: u64,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalModelError> {
        let now_ms = clock.now_ms()?;
        grant.validate_current(now_ms)?;
        if deadline_ms <= now_ms || deadline_ms > grant.claims().expires_at_ms {
            return Err(LocalModelError::InvalidDeadline);
        }
        Ok(Self {
            deadline_ms,
            instant: Instant::now() + Duration::from_millis(deadline_ms - now_ms),
        })
    }

    #[must_use]
    pub fn instant(&self) -> Instant {
        self.instant
    }

    #[must_use]
    pub fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadedModel {
    pub handle_id: String,
    pub model_digest: String,
    pub device_id: String,
    pub device_lease_id: String,
    pub observed_loaded_bytes: u64,
}

#[derive(Clone, Debug)]
pub struct AttestedModelHandle {
    handle_id: String,
    manifest: VerifiedModelManifest,
    worker_generation: u64,
    device_id: String,
    device_lease_id: String,
    resident_bytes: u64,
    attestation_digest: String,
}

impl AttestedModelHandle {
    #[must_use]
    pub fn handle_id(&self) -> &str {
        &self.handle_id
    }

    #[must_use]
    pub fn manifest(&self) -> &VerifiedModelManifest {
        &self.manifest
    }

    #[must_use]
    pub fn worker_generation(&self) -> u64 {
        self.worker_generation
    }

    #[must_use]
    pub fn device_id(&self) -> &str {
        &self.device_id
    }

    #[must_use]
    pub fn device_lease_id(&self) -> &str {
        &self.device_lease_id
    }

    #[must_use]
    pub fn resident_bytes(&self) -> u64 {
        self.resident_bytes
    }

    #[must_use]
    pub fn attestation_digest(&self) -> &str {
        &self.attestation_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverTerminalStatus {
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverExecutionObservation {
    pub operation_id: String,
    pub handle_id: String,
    pub model_digest: String,
    pub input_digest: String,
    pub terminal_observed: bool,
    pub terminal_status: Option<DriverTerminalStatus>,
    pub output_digest: Option<String>,
    pub consumed_tokens: Option<u32>,
    pub usage_units: Option<u64>,
    pub observed_transient_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverReconciliation {
    NotFound,
    InFlight,
    Terminal(DriverExecutionObservation),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverUnloadObservation {
    pub terminal_observed: bool,
    pub released: bool,
}

pub trait LocalModelDriver: Send + Sync {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadedModel>;

    fn run<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        maximum_tokens: u32,
        cancellation: &'a CancellationToken,
        deadline: Instant,
    ) -> DriverFuture<'a, DriverExecutionObservation>;

    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
    ) -> DriverFuture<'a, DriverReconciliation>;

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, DriverUnloadObservation>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedResourceObservation {
    pub handle_id: String,
    pub worker_generation: u64,
    pub device_id: String,
    pub device_lease_id: String,
    pub resident_bytes: u64,
    pub generation_fenced: bool,
    pub evidence_digest: String,
}

pub trait TrustedResourceObserver: Send + Sync {
    fn attest_loaded(
        &self,
        manifest: &VerifiedModelManifest,
        loaded: &DriverLoadedModel,
        worker_generation: u64,
    ) -> Result<TrustedResourceObservation, LocalModelError>;

    fn observe_handle(
        &self,
        handle: &AttestedModelHandle,
    ) -> Result<TrustedResourceObservation, LocalModelError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelResourceState {
    Loading,
    Ready,
    Draining,
    Zombie,
    RepairRequired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub worker_generation: u64,
    pub fenced: bool,
    pub loaded_bytes: u64,
    pub reserved_load_bytes: u64,
    pub reserved_transient_bytes: u64,
    pub active_requests: usize,
    pub models: BTreeMap<String, ModelResourceState>,
}

#[derive(Clone, Debug)]
pub struct ResourceManager {
    inner: Arc<Mutex<ResourceState>>,
}

#[derive(Debug)]
struct ResourceState {
    worker_generation: u64,
    fenced: bool,
    maximum_aggregate_memory_bytes: u64,
    maximum_transient_memory_bytes: u64,
    maximum_concurrent_requests: usize,
    loaded_bytes: u64,
    reserved_load_bytes: u64,
    reserved_transient_bytes: u64,
    active_requests: usize,
    models: BTreeMap<String, ModelResourceRecord>,
}

#[derive(Clone, Debug)]
struct ModelResourceRecord {
    state: ModelResourceState,
    resident_bytes: u64,
}

impl ResourceManager {
    pub fn new(grant: &VerifiedResourceGrant) -> Self {
        let claims = grant.claims();
        Self {
            inner: Arc::new(Mutex::new(ResourceState {
                worker_generation: claims.worker_generation,
                fenced: false,
                maximum_aggregate_memory_bytes: claims.maximum_aggregate_memory_bytes,
                maximum_transient_memory_bytes: claims.maximum_transient_memory_bytes,
                maximum_concurrent_requests: claims.maximum_concurrent_requests,
                loaded_bytes: 0,
                reserved_load_bytes: 0,
                reserved_transient_bytes: 0,
                active_requests: 0,
                models: BTreeMap::new(),
            })),
        }
    }

    pub fn snapshot(&self) -> Result<ResourceSnapshot, LocalModelError> {
        let state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        Ok(ResourceSnapshot {
            worker_generation: state.worker_generation,
            fenced: state.fenced,
            loaded_bytes: state.loaded_bytes,
            reserved_load_bytes: state.reserved_load_bytes,
            reserved_transient_bytes: state.reserved_transient_bytes,
            active_requests: state.active_requests,
            models: state
                .models
                .iter()
                .map(|(id, record)| (id.clone(), record.state))
                .collect(),
        })
    }

    pub fn fence_generation(&self) -> Result<(), LocalModelError> {
        self.inner
            .lock()
            .map_err(|_| LocalModelError::LockPoisoned)?
            .fenced = true;
        Ok(())
    }

    fn reserve_load(
        &self,
        model_id: &str,
        declared_bytes: u64,
    ) -> Result<LoadReservation, LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        require_live(&state)?;
        if state.models.contains_key(model_id) {
            return Err(LocalModelError::ModelAlreadyLoaded);
        }
        let total = aggregate_bytes(&state)?
            .checked_add(declared_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        if total > state.maximum_aggregate_memory_bytes {
            return Err(LocalModelError::ResourceCapacity);
        }
        state.reserved_load_bytes = state
            .reserved_load_bytes
            .checked_add(declared_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.models.insert(
            model_id.to_string(),
            ModelResourceRecord {
                state: ModelResourceState::Loading,
                resident_bytes: 0,
            },
        );
        drop(state);
        Ok(LoadReservation {
            manager: self.clone(),
            model_id: model_id.to_string(),
            declared_bytes,
            active: true,
        })
    }

    fn begin_run(&self, transient_bytes: u64) -> Result<RunReservation, LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        require_live(&state)?;
        if transient_bytes > state.maximum_transient_memory_bytes
            || state.active_requests >= state.maximum_concurrent_requests
        {
            return Err(LocalModelError::ResourceCapacity);
        }
        let total = aggregate_bytes(&state)?
            .checked_add(transient_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        if total > state.maximum_aggregate_memory_bytes {
            return Err(LocalModelError::ResourceCapacity);
        }
        state.reserved_transient_bytes = state
            .reserved_transient_bytes
            .checked_add(transient_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.active_requests = state
            .active_requests
            .checked_add(1)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        drop(state);
        Ok(RunReservation {
            manager: self.clone(),
            transient_bytes,
        })
    }

    fn begin_unload(&self, model_id: &str) -> Result<(), LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        require_live(&state)?;
        let record = state
            .models
            .get_mut(model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if record.state != ModelResourceState::Ready {
            return Err(LocalModelError::ResourceState);
        }
        record.state = ModelResourceState::Draining;
        Ok(())
    }

    fn mark_model(
        &self,
        model_id: &str,
        next: ModelResourceState,
    ) -> Result<(), LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        let record = state
            .models
            .get_mut(model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        record.state = next;
        Ok(())
    }

    fn complete_unload(&self, model_id: &str) -> Result<(), LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        let resident_bytes = state
            .models
            .get(model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?
            .resident_bytes;
        let next_loaded = state
            .loaded_bytes
            .checked_sub(resident_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.models.remove(model_id);
        state.loaded_bytes = next_loaded;
        Ok(())
    }

    fn reconcile_resident(
        &self,
        model_id: &str,
        resident_bytes: u64,
    ) -> Result<(), LocalModelError> {
        let mut state = self.inner.lock().map_err(|_| LocalModelError::LockPoisoned)?;
        let previous = state
            .models
            .get(model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?
            .resident_bytes;
        let next_loaded = state
            .loaded_bytes
            .checked_sub(previous)
            .and_then(|value| value.checked_add(resident_bytes))
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        let total = next_loaded
            .checked_add(state.reserved_load_bytes)
            .and_then(|value| value.checked_add(state.reserved_transient_bytes))
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.loaded_bytes = next_loaded;
        if let Some(record) = state.models.get_mut(model_id) {
            record.resident_bytes = resident_bytes;
        }
        if total > state.maximum_aggregate_memory_bytes {
            state.fenced = true;
            if let Some(record) = state.models.get_mut(model_id) {
                record.state = ModelResourceState::RepairRequired;
            }
            return Err(LocalModelError::ResourceCapacity);
        }
        Ok(())
    }
}

struct LoadReservation {
    manager: ResourceManager,
    model_id: String,
    declared_bytes: u64,
    active: bool,
}

impl LoadReservation {
    fn commit(mut self, resident_bytes: u64) -> Result<(), LocalModelError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalModelError::LockPoisoned)?;
        let remaining_reserved = state
            .reserved_load_bytes
            .checked_sub(self.declared_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        let next_loaded = state
            .loaded_bytes
            .checked_add(resident_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        let total = next_loaded
            .checked_add(remaining_reserved)
            .and_then(|value| value.checked_add(state.reserved_transient_bytes))
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.reserved_load_bytes = remaining_reserved;
        state.loaded_bytes = next_loaded;
        let record = state
            .models
            .get_mut(&self.model_id)
            .ok_or(LocalModelError::ResourceState)?;
        record.resident_bytes = resident_bytes;
        if total > state.maximum_aggregate_memory_bytes {
            record.state = ModelResourceState::RepairRequired;
            state.fenced = true;
            self.active = false;
            return Err(LocalModelError::ResourceCapacity);
        }
        record.state = ModelResourceState::Ready;
        self.active = false;
        Ok(())
    }

    fn quarantine(mut self, resident_bytes: u64) -> Result<(), LocalModelError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalModelError::LockPoisoned)?;
        state.reserved_load_bytes = state
            .reserved_load_bytes
            .checked_sub(self.declared_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.loaded_bytes = state
            .loaded_bytes
            .checked_add(resident_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        if let Some(record) = state.models.get_mut(&self.model_id) {
            record.state = ModelResourceState::RepairRequired;
            record.resident_bytes = resident_bytes;
        }
        state.fenced = true;
        self.active = false;
        Ok(())
    }
}

impl Drop for LoadReservation {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            if let Some(next) = state.reserved_load_bytes.checked_sub(self.declared_bytes) {
                state.reserved_load_bytes = next;
                state.models.remove(&self.model_id);
            } else {
                state.fenced = true;
            }
        }
    }
}

struct RunReservation {
    manager: ResourceManager,
    transient_bytes: u64,
}

impl Drop for RunReservation {
    fn drop(&mut self) {
        if let Ok(mut state) = self.manager.inner.lock() {
            match (
                state.reserved_transient_bytes.checked_sub(self.transient_bytes),
                state.active_requests.checked_sub(1),
            ) {
                (Some(memory), Some(active)) => {
                    state.reserved_transient_bytes = memory;
                    state.active_requests = active;
                }
                _ => state.fenced = true,
            }
        }
    }
}

fn aggregate_bytes(state: &ResourceState) -> Result<u64, LocalModelError> {
    state
        .loaded_bytes
        .checked_add(state.reserved_load_bytes)
        .and_then(|value| value.checked_add(state.reserved_transient_bytes))
        .ok_or(LocalModelError::ArithmeticOverflow)
}

fn require_live(state: &ResourceState) -> Result<(), LocalModelError> {
    if state.fenced {
        Err(LocalModelError::ResourceFenced)
    } else {
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalRunRequest {
    pub request_id: String,
    pub input_digest: String,
    pub maximum_tokens: u32,
    pub maximum_usage_units: u64,
    pub maximum_transient_memory_bytes: u64,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalExecutionState {
    Completed,
    Failed,
    Cancelled,
    UsagePending,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalExecutionResult {
    pub request_id: String,
    pub state: LocalExecutionState,
    pub terminal_observed: bool,
    pub output_digest: Option<String>,
    pub consumed_tokens: Option<u32>,
    pub usage_units: Option<u64>,
    pub observation_digest: Option<String>,
    pub replayed_from_journal: bool,
    pub stop_reason: Option<String>,
}

pub struct LocalModelWorker {
    worker_id: String,
    generation: u64,
    grant: VerifiedResourceGrant,
    driver: Arc<dyn LocalModelDriver>,
    observer: Arc<dyn TrustedResourceObserver>,
    clock: Arc<dyn TrustedClock>,
    resources: ResourceManager,
    models: AsyncMutex<BTreeMap<String, AttestedModelHandle>>,
    control: AsyncMutex<DurableInferenceControl>,
}

impl LocalModelWorker {
    pub fn new(
        worker_id: String,
        generation: u64,
        grant: VerifiedResourceGrant,
        driver: Arc<dyn LocalModelDriver>,
        observer: Arc<dyn TrustedResourceObserver>,
        clock: Arc<dyn TrustedClock>,
        control: DurableInferenceControl,
    ) -> Result<Self, LocalModelError> {
        validate_identity(&worker_id, "worker")?;
        if generation == 0
            || grant.claims().worker_id != worker_id
            || grant.claims().worker_generation != generation
        {
            return Err(LocalModelError::WorkerBindingMismatch);
        }
        let resources = ResourceManager::new(&grant);
        Ok(Self {
            worker_id,
            generation,
            grant,
            driver,
            observer,
            clock,
            resources,
            models: AsyncMutex::new(BTreeMap::new()),
            control: AsyncMutex::new(control),
        })
    }

    #[must_use]
    pub fn resources(&self) -> &ResourceManager {
        &self.resources
    }

    fn validate_grant_now(&self) -> Result<u64, LocalModelError> {
        let now_ms = self.clock.now_ms()?;
        self.grant.validate_current(now_ms)?;
        Ok(now_ms)
    }

    pub async fn load_model(
        &self,
        manifest: ModelManifestV1,
    ) -> Result<AttestedModelHandle, LocalModelError> {
        self.validate_grant_now()?;
        let manifest = VerifiedModelManifest::verify(manifest, &self.grant)?;
        let model_id = manifest.manifest().model_id.clone();
        if self.models.lock().await.contains_key(&model_id) {
            return Err(LocalModelError::ModelAlreadyLoaded);
        }
        let reservation = self
            .resources
            .reserve_load(&model_id, manifest.manifest().declared_weight_bytes)?;
        let loaded = match self.driver.load(&manifest, &self.grant).await {
            Ok(value) => value,
            Err(error) => {
                reservation.quarantine(manifest.manifest().declared_weight_bytes)?;
                return Err(error);
            }
        };
        let trusted = match self
            .observer
            .attest_loaded(&manifest, &loaded, self.generation)
        {
            Ok(value) => value,
            Err(error) => {
                reservation.quarantine(loaded.observed_loaded_bytes)?;
                return Err(error);
            }
        };
        if let Err(error) =
            validate_loaded_observation(&manifest, &loaded, &trusted, self.generation)
        {
            reservation.quarantine(loaded.observed_loaded_bytes)?;
            return Err(error);
        }
        if trusted.generation_fenced {
            reservation.quarantine(trusted.resident_bytes)?;
            return Err(LocalModelError::ResourceFenced);
        }
        let handle = AttestedModelHandle {
            handle_id: loaded.handle_id,
            manifest,
            worker_generation: self.generation,
            device_id: trusted.device_id,
            device_lease_id: trusted.device_lease_id,
            resident_bytes: trusted.resident_bytes,
            attestation_digest: trusted.evidence_digest,
        };
        reservation.commit(handle.resident_bytes)?;
        self.models
            .lock()
            .await
            .insert(model_id, handle.clone());
        Ok(handle)
    }

    pub async fn unload_model(&self, model_id: &str) -> Result<(), LocalModelError> {
        self.validate_grant_now()?;
        validate_identity(model_id, "model")?;
        let handle = self
            .models
            .lock()
            .await
            .get(model_id)
            .cloned()
            .ok_or(LocalModelError::ModelNotLoaded)?;
        self.resources.begin_unload(model_id)?;
        let observed = match self.driver.unload(&handle).await {
            Ok(value) => value,
            Err(error) => {
                self.resources
                    .mark_model(model_id, ModelResourceState::Zombie)?;
                return Err(error);
            }
        };
        if !observed.terminal_observed || !observed.released {
            self.resources
                .mark_model(model_id, ModelResourceState::Zombie)?;
            return Err(LocalModelError::ResourceState);
        }
        let trusted = self.observer.observe_handle(&handle)?;
        validate_resource_observation(&handle, &trusted)?;
        if trusted.generation_fenced || trusted.resident_bytes != 0 {
            self.resources
                .mark_model(model_id, ModelResourceState::RepairRequired)?;
            self.resources.fence_generation()?;
            return Err(LocalModelError::ResourceFenced);
        }
        self.resources.complete_unload(model_id)?;
        self.models.lock().await.remove(model_id);
        Ok(())
    }

    pub async fn run(
        &self,
        model_id: &str,
        request: LocalRunRequest,
        input: VerifiedInput,
        cancellation: &CancellationToken,
    ) -> Result<LocalExecutionResult, LocalModelError> {
        self.validate_grant_now()?;
        validate_run_request(&request, &self.grant, &input)?;
        validate_identity(model_id, "model")?;
        let handle = self
            .models
            .lock()
            .await
            .get(model_id)
            .cloned()
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if handle.manifest().manifest().model_id != model_id {
            return Err(LocalModelError::ModelBindingMismatch);
        }
        let deadline = TrustedDeadline::verify(self.clock.as_ref(), request.deadline_ms, &self.grant)?;
        let payload_digest = local_payload_digest(&request, &input, &handle);
        let assignment_digest = local_assignment_digest(
            &self.grant,
            &handle,
            &request.request_id,
            &payload_digest,
        );
        let prepared = self
            .prepare_durable_run(
                &request,
                &handle,
                &payload_digest,
                &assignment_digest,
                cancellation.is_cancelled(),
            )
            .await?;
        match prepared {
            PreparedRun::Terminal(record) => Ok(result_from_record(&record)),
            PreparedRun::InspectOnly => {
                let inspected = self.driver.inspect(&request.request_id).await?;
                self.finish_reconciliation(&request, &handle, inspected).await
            }
            PreparedRun::Dispatch => {
                let _reservation = self
                    .resources
                    .begin_run(request.maximum_transient_memory_bytes)?;
                match self
                    .driver
                    .run(
                        &request.request_id,
                        &handle,
                        &input,
                        request.maximum_tokens,
                        cancellation,
                        deadline.instant(),
                    )
                    .await
                {
                    Ok(observed) => {
                        self.finish_observation(&request, &handle, observed, false)
                            .await
                    }
                    Err(error) => Ok(LocalExecutionResult {
                        request_id: request.request_id,
                        state: LocalExecutionState::Quarantined,
                        terminal_observed: false,
                        output_digest: None,
                        consumed_tokens: None,
                        usage_units: None,
                        observation_digest: None,
                        replayed_from_journal: false,
                        stop_reason: Some(bounded_reason(&format!(
                            "driver returned after durable assignment: {error}"
                        ))),
                    }),
                }
            }
        }
    }

    async fn prepare_durable_run(
        &self,
        request: &LocalRunRequest,
        handle: &AttestedModelHandle,
        payload_digest: &str,
        assignment_digest: &str,
        cancelled: bool,
    ) -> Result<PreparedRun, LocalModelError> {
        let now_ms = self.validate_grant_now()?;
        let semantic_digest = local_semantic_digest(request, &self.grant, handle);
        let control_request = ControlRequest {
            request_id: request.request_id.clone(),
            principal_id: self.worker_id.clone(),
            model_digest: handle.manifest().manifest().model_digest.clone(),
            payload_digest: payload_digest.to_string(),
            maximum_tokens: request.maximum_tokens,
            deadline_ms: request.deadline_ms,
            semantic_digest,
        };
        let reservation = ControlReservation {
            reservation_id: format!(
                "local-reservation:{}",
                &digest(request.request_id.as_bytes())[..32]
            ),
            quota_units: request.maximum_usage_units,
            maximum_tokens: request.maximum_tokens,
            authority_epoch: self.grant.claims().authority_epoch,
            valid_until_ms: request.deadline_ms.min(self.grant.claims().expires_at_ms),
        };
        let assignment = ControlAssignment {
            worker_id: self.worker_id.clone(),
            worker_generation: self.generation,
            assignment_digest: assignment_digest.to_string(),
        };
        let mut control = self.control.lock().await;
        control.submit(now_ms, control_request)?;
        let mut record = control
            .get(&request.request_id)
            .cloned()
            .ok_or_else(|| LocalModelError::Control("submitted record disappeared".to_string()))?;
        if is_terminal(record.state) {
            return Ok(PreparedRun::Terminal(record));
        }
        if cancelled && matches!(record.state, RequestState::Pending | RequestState::Reserved) {
            control.cancel(&request.request_id, record.revision)?;
            record = control
                .get(&request.request_id)
                .cloned()
                .ok_or_else(|| LocalModelError::Control("cancelled record disappeared".to_string()))?;
            return Ok(PreparedRun::Terminal(record));
        }
        if record.state == RequestState::Pending {
            control.reserve(now_ms, &request.request_id, record.revision, reservation.clone())?;
            record = control
                .get(&request.request_id)
                .cloned()
                .ok_or_else(|| LocalModelError::Control("reserved record disappeared".to_string()))?;
        }
        if record.state == RequestState::Reserved {
            if record.reservation.as_ref() != Some(&reservation) {
                return Err(LocalModelError::Control(
                    "reservation identity conflict".to_string(),
                ));
            }
            control.assign(&request.request_id, record.revision, assignment.clone())?;
            return Ok(PreparedRun::Dispatch);
        }
        if matches!(record.state, RequestState::Assigned | RequestState::Cancelling) {
            if record.assignment.as_ref() != Some(&assignment) {
                return Err(LocalModelError::Control(
                    "assignment identity conflict".to_string(),
                ));
            }
            if cancelled && record.state == RequestState::Assigned {
                control.cancel(&request.request_id, record.revision)?;
            }
            return Ok(PreparedRun::InspectOnly);
        }
        Err(LocalModelError::Control(
            "unsupported durable request state".to_string(),
        ))
    }

    async fn finish_reconciliation(
        &self,
        request: &LocalRunRequest,
        handle: &AttestedModelHandle,
        reconciliation: DriverReconciliation,
    ) -> Result<LocalExecutionResult, LocalModelError> {
        match reconciliation {
            DriverReconciliation::Terminal(observation) => {
                self.finish_observation(request, handle, observation, true)
                    .await
            }
            DriverReconciliation::NotFound | DriverReconciliation::InFlight => {
                Ok(LocalExecutionResult {
                    request_id: request.request_id.clone(),
                    state: LocalExecutionState::Quarantined,
                    terminal_observed: false,
                    output_digest: None,
                    consumed_tokens: None,
                    usage_units: None,
                    observation_digest: None,
                    replayed_from_journal: true,
                    stop_reason: Some(
                        "durable assignment reopened without exact terminal evidence; no replay"
                            .to_string(),
                    ),
                })
            }
        }
    }

    async fn finish_observation(
        &self,
        request: &LocalRunRequest,
        handle: &AttestedModelHandle,
        observation: DriverExecutionObservation,
        reconciled: bool,
    ) -> Result<LocalExecutionResult, LocalModelError> {
        validate_execution_observation(request, handle, &observation)?;
        let trusted = self.observer.observe_handle(handle)?;
        validate_resource_observation(handle, &trusted)?;
        if trusted.generation_fenced {
            self.resources.fence_generation()?;
            return Err(LocalModelError::ResourceFenced);
        }
        self.resources.reconcile_resident(
            &handle.manifest().manifest().model_id,
            trusted.resident_bytes,
        )?;
        if !observation.terminal_observed {
            return Ok(LocalExecutionResult {
                request_id: request.request_id.clone(),
                state: LocalExecutionState::Quarantined,
                terminal_observed: false,
                output_digest: None,
                consumed_tokens: observation.consumed_tokens,
                usage_units: observation.usage_units,
                observation_digest: None,
                replayed_from_journal: reconciled,
                stop_reason: Some("driver terminality is unknown; no replay".to_string()),
            });
        }
        let (Some(consumed_tokens), Some(usage_units)) =
            (observation.consumed_tokens, observation.usage_units)
        else {
            return Ok(LocalExecutionResult {
                request_id: request.request_id.clone(),
                state: LocalExecutionState::UsagePending,
                terminal_observed: true,
                output_digest: observation.output_digest,
                consumed_tokens: observation.consumed_tokens,
                usage_units: observation.usage_units,
                observation_digest: None,
                replayed_from_journal: reconciled,
                stop_reason: Some(
                    "terminal result observed but trusted usage is missing; zero was not inferred"
                        .to_string(),
                ),
            });
        };
        if consumed_tokens > request.maximum_tokens || usage_units > request.maximum_usage_units {
            return Err(LocalModelError::UsageExceeded);
        }
        let terminal_status = match observation
            .terminal_status
            .ok_or(LocalModelError::ObservationMismatch)?
        {
            DriverTerminalStatus::Succeeded => RequestState::Completed,
            DriverTerminalStatus::Failed => RequestState::Failed,
            DriverTerminalStatus::Cancelled => RequestState::Cancelled,
        };
        if terminal_status == RequestState::Completed && observation.output_digest.is_none() {
            return Err(LocalModelError::ObservationMismatch);
        }
        let observation_digest = local_observation_digest(&observation);
        let mut control = self.control.lock().await;
        let record = control
            .get(&request.request_id)
            .cloned()
            .ok_or_else(|| LocalModelError::Control("assigned record disappeared".to_string()))?;
        if is_terminal(record.state) {
            return Ok(result_from_record(&record));
        }
        let reservation_id = record
            .reservation
            .as_ref()
            .ok_or_else(|| LocalModelError::Control("reservation missing".to_string()))?
            .reservation_id
            .clone();
        control.settle(
            &request.request_id,
            record.revision,
            observation_digest.clone(),
            TerminalObservation {
                request_id: request.request_id.clone(),
                reservation_id,
                worker_id: self.worker_id.clone(),
                worker_generation: self.generation,
                model_digest: handle.manifest().manifest().model_digest.clone(),
                payload_digest: record.request.payload_digest,
                terminal_observed: true,
                terminal_status: Some(terminal_status),
                output_digest: observation.output_digest.clone(),
                consumed_tokens,
                usage_units,
            },
        )?;
        Ok(LocalExecutionResult {
            request_id: request.request_id.clone(),
            state: match terminal_status {
                RequestState::Completed => LocalExecutionState::Completed,
                RequestState::Failed => LocalExecutionState::Failed,
                RequestState::Cancelled => LocalExecutionState::Cancelled,
                _ => return Err(LocalModelError::ObservationMismatch),
            },
            terminal_observed: true,
            output_digest: observation.output_digest,
            consumed_tokens: Some(consumed_tokens),
            usage_units: Some(usage_units),
            observation_digest: Some(observation_digest),
            replayed_from_journal: reconciled,
            stop_reason: None,
        })
    }
}

#[derive(Clone, Debug)]
enum PreparedRun {
    Dispatch,
    InspectOnly,
    Terminal(RequestRecord),
}

fn result_from_record(record: &RequestRecord) -> LocalExecutionResult {
    let state = match record.state {
        RequestState::Completed => LocalExecutionState::Completed,
        RequestState::Failed => LocalExecutionState::Failed,
        RequestState::Cancelled => LocalExecutionState::Cancelled,
        _ => LocalExecutionState::Quarantined,
    };
    LocalExecutionResult {
        request_id: record.request.request_id.clone(),
        state,
        terminal_observed: matches!(
            record.state,
            RequestState::Completed | RequestState::Failed | RequestState::Cancelled
        ),
        output_digest: None,
        consumed_tokens: record
            .terminal_observation_digest
            .as_ref()
            .map(|_| record.consumed_tokens),
        usage_units: record
            .terminal_observation_digest
            .as_ref()
            .map(|_| record.usage_units),
        observation_digest: record.terminal_observation_digest.clone(),
        replayed_from_journal: true,
        stop_reason: Some(
            "durable terminal receipt replayed; output bytes are not stored in the control journal"
                .to_string(),
        ),
    }
}

fn is_terminal(state: RequestState) -> bool {
    matches!(
        state,
        RequestState::Completed
            | RequestState::Failed
            | RequestState::Cancelled
            | RequestState::Indeterminate
    )
}

fn validate_grant_claims(value: &ResourceGrantClaimsV1) -> Result<(), LocalModelError> {
    for (identity, field) in [
        (&value.issuer_id, "issuer"),
        (&value.grant_id, "grant"),
        (&value.nonce, "nonce"),
        (&value.worker_id, "worker"),
        (&value.model_id, "model"),
        (&value.device_id, "device"),
        (&value.device_lease_id, "device lease"),
    ] {
        validate_identity(identity, field)?;
    }
    for (digest_value, field) in [
        (&value.revocation_head_digest, "revocation head"),
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.semantic_digest, "semantic"),
    ] {
        validate_digest(digest_value, field)?;
    }
    if value.authority_epoch == 0
        || value.worker_generation == 0
        || value.issued_at_ms > value.not_before_ms
        || value.not_before_ms >= value.expires_at_ms
        || value.maximum_aggregate_memory_bytes == 0
        || value.maximum_transient_memory_bytes == 0
        || value.maximum_concurrent_requests == 0
        || value.maximum_tokens_per_request == 0
        || value.maximum_tokens_per_request > MAX_TOKENS
        || value.maximum_usage_units == 0
    {
        return Err(LocalModelError::InvalidGrant);
    }
    Ok(())
}

fn validate_manifest(value: &ModelManifestV1) -> Result<(), LocalModelError> {
    validate_identity(&value.model_id, "model")?;
    validate_identity(&value.device_id, "device")?;
    validate_identity(&value.device_lease_id, "device lease")?;
    for (digest_value, field) in [
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.semantic_digest, "semantic"),
    ] {
        validate_digest(digest_value, field)?;
    }
    if value.declared_weight_bytes == 0
        || value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
    {
        return Err(LocalModelError::InvalidManifest);
    }
    Ok(())
}

fn validate_run_request(
    request: &LocalRunRequest,
    grant: &VerifiedResourceGrant,
    input: &VerifiedInput,
) -> Result<(), LocalModelError> {
    validate_identity(&request.request_id, "request")?;
    validate_digest(&request.input_digest, "input")?;
    if request.input_digest != input.digest()
        || request.maximum_tokens == 0
        || request.maximum_tokens > grant.claims().maximum_tokens_per_request
        || request.maximum_usage_units == 0
        || request.maximum_usage_units > grant.claims().maximum_usage_units
        || request.maximum_transient_memory_bytes == 0
        || request.maximum_transient_memory_bytes
            > grant.claims().maximum_transient_memory_bytes
    {
        return Err(LocalModelError::InvalidInput);
    }
    Ok(())
}

fn validate_loaded_observation(
    manifest: &VerifiedModelManifest,
    loaded: &DriverLoadedModel,
    trusted: &TrustedResourceObservation,
    generation: u64,
) -> Result<(), LocalModelError> {
    validate_identity(&loaded.handle_id, "model handle")?;
    validate_digest(&trusted.evidence_digest, "resource evidence")?;
    if loaded.model_digest != manifest.manifest().model_digest
        || loaded.device_id != manifest.manifest().device_id
        || loaded.device_lease_id != manifest.manifest().device_lease_id
        || trusted.handle_id != loaded.handle_id
        || trusted.worker_generation != generation
        || trusted.device_id != loaded.device_id
        || trusted.device_lease_id != loaded.device_lease_id
        || trusted.resident_bytes != loaded.observed_loaded_bytes
        || trusted.resident_bytes == 0
    {
        return Err(LocalModelError::ObservationMismatch);
    }
    Ok(())
}

fn validate_resource_observation(
    handle: &AttestedModelHandle,
    observed: &TrustedResourceObservation,
) -> Result<(), LocalModelError> {
    validate_digest(&observed.evidence_digest, "resource evidence")?;
    if observed.handle_id != handle.handle_id
        || observed.worker_generation != handle.worker_generation
        || observed.device_id != handle.device_id
        || observed.device_lease_id != handle.device_lease_id
    {
        return Err(LocalModelError::ObservationMismatch);
    }
    Ok(())
}

fn validate_execution_observation(
    request: &LocalRunRequest,
    handle: &AttestedModelHandle,
    observed: &DriverExecutionObservation,
) -> Result<(), LocalModelError> {
    if observed.operation_id != request.request_id
        || observed.handle_id != handle.handle_id
        || observed.model_digest != handle.manifest().manifest().model_digest
        || observed.input_digest != request.input_digest
    {
        return Err(LocalModelError::ObservationMismatch);
    }
    if observed.observed_transient_bytes > request.maximum_transient_memory_bytes {
        return Err(LocalModelError::ResourceCapacity);
    }
    if observed.terminal_observed != observed.terminal_status.is_some()
        || (!observed.terminal_observed && observed.output_digest.is_some())
    {
        return Err(LocalModelError::ObservationMismatch);
    }
    if let Some(tokens) = observed.consumed_tokens {
        if tokens > request.maximum_tokens {
            return Err(LocalModelError::UsageExceeded);
        }
    }
    if let Some(units) = observed.usage_units {
        if units > request.maximum_usage_units {
            return Err(LocalModelError::UsageExceeded);
        }
    }
    if let Some(output) = &observed.output_digest {
        validate_digest(output, "output")?;
    }
    Ok(())
}

fn local_payload_digest(
    request: &LocalRunRequest,
    input: &VerifiedInput,
    handle: &AttestedModelHandle,
) -> String {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(LOCAL_REQUEST_DOMAIN);
    for value in [
        request.request_id.as_str(),
        input.digest(),
        handle.manifest().manifest().model_digest.as_str(),
        handle.attestation_digest(),
    ] {
        push_string(&mut bytes, value);
    }
    bytes.extend_from_slice(&request.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_usage_units.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_transient_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    digest(&bytes)
}

fn local_semantic_digest(
    request: &LocalRunRequest,
    grant: &VerifiedResourceGrant,
    handle: &AttestedModelHandle,
) -> String {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(LOCAL_REQUEST_DOMAIN);
    for value in [
        request.request_id.as_str(),
        grant.witness_digest(),
        handle.attestation_digest(),
        handle.manifest().manifest().semantic_digest.as_str(),
    ] {
        push_string(&mut bytes, value);
    }
    bytes.extend_from_slice(&request.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_usage_units.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_transient_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    digest(&bytes)
}

fn local_assignment_digest(
    grant: &VerifiedResourceGrant,
    handle: &AttestedModelHandle,
    operation_id: &str,
    payload_digest: &str,
) -> String {
    let mut bytes = Vec::new();
    for value in [
        grant.witness_digest(),
        handle.attestation_digest(),
        handle.handle_id(),
        operation_id,
        payload_digest,
    ] {
        push_string(&mut bytes, value);
    }
    digest(&bytes)
}

fn local_observation_digest(observed: &DriverExecutionObservation) -> String {
    let mut bytes = Vec::new();
    for value in [
        observed.operation_id.as_str(),
        observed.handle_id.as_str(),
        observed.model_digest.as_str(),
        observed.input_digest.as_str(),
    ] {
        push_string(&mut bytes, value);
    }
    bytes.push(u8::from(observed.terminal_observed));
    bytes.push(match observed.terminal_status {
        None => 0,
        Some(DriverTerminalStatus::Succeeded) => 1,
        Some(DriverTerminalStatus::Failed) => 2,
        Some(DriverTerminalStatus::Cancelled) => 3,
    });
    match &observed.output_digest {
        Some(value) => {
            bytes.push(1);
            push_string(&mut bytes, value);
        }
        None => bytes.push(0),
    }
    match observed.consumed_tokens {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
    match observed.usage_units {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&observed.observed_transient_bytes.to_be_bytes());
    digest(&bytes)
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), LocalModelError> {
    if value.is_empty()
        || value.len() > MAX_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(LocalModelError::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), LocalModelError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(LocalModelError::InvalidDigest(field));
    }
    Ok(())
}

fn bounded_reason(value: &str) -> String {
    value.chars().take(1024).collect()
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "local_model_tests.rs"]
mod tests;
