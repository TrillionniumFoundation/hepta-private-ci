//! Qualification-only process-bound adapter for the AuthBus B3 contracts.
//!
//! This module is deliberately a small local harness, not an OpenBao client or
//! a production writer.  It demonstrates the safety boundary required by the
//! B3 stage: a [`SecretRefBackend`] resolves an opaque reference into
//! zeroizing, process-local material; a [`SecretRefProvider`] consumes that
//! material and returns only typed status/opaque references; and status
//! reconciliation is a lookup-only path.  No listener, network client,
//! durable store, provider effect, or authority flag is enabled here.

use std::collections::BTreeMap;
use std::fmt;

use zeroize::Zeroizing;

use crate::AuthBusContractError;
use crate::Sha256Digest;
use crate::authbus::b3::OpaqueSecretRef;
use crate::authbus::b3::RefreshStatusByOperationKeyRequest;
use crate::authbus::b3::RefreshStatusByOperationKeyResponse;
use crate::authbus::b3::RefreshWithSecretRefRequest;
use crate::authbus::b3::RefreshWithSecretRefResponse;
use crate::authbus::b3::RotateSecretRefRequest;
use crate::authbus::b3::RotateSecretRefResponse;
use crate::authbus::b3::SecretProviderStatus;
use crate::authbus::b3::SecretRefCallbackFence;
use crate::authbus::b3::SecretRefEvent;
use crate::authbus::b3::SecretRefOperationRecord;
use crate::authbus::b3::SecretRefOutcome;
use crate::authbus::b3::SecretRefState;

/// This implementation is a local qualification seam only.
pub const AUTHBUS_B3_ADAPTER_QUALIFICATION_ONLY: bool = true;
pub const AUTHBUS_B3_ADAPTER_AUTHORITY: bool = false;
pub const AUTHBUS_B3_ADAPTER_EFFECT_AUTHORITY: bool = false;
pub const AUTHBUS_B3_ADAPTER_PRODUCTION_CALLER: bool = false;
pub const AUTHBUS_B3_ADAPTER_PRODUCTION_WRITER: bool = false;
pub const AUTHBUS_B3_ADAPTER_OPERATOR_ACCEPTANCE: bool = false;
pub const AUTHBUS_B3_ADAPTER_PROMOTION: bool = false;
pub const AUTHBUS_B3_ADAPTER_G5_ALLOWED: bool = false;
pub const AUTHBUS_B3_ADAPTER_EXECUTE_ALLOWED: bool = false;

/// Errors returned by a secret backend.  The variants intentionally carry no
/// provider body, header, or secret bytes; the adapter maps them to a bounded
/// [`SecretProviderStatus`] classification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretBackendError {
    NotFound,
    Unauthorized,
    Timeout,
    Unavailable,
    Sealed,
    InvalidReference,
}

impl fmt::Display for SecretBackendError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Self::NotFound => "secret backend did not find the reference",
            Self::Unauthorized => "secret backend denied the reference",
            Self::Timeout => "secret backend timed out",
            Self::Unavailable => "secret backend is unavailable",
            Self::Sealed => "secret backend is sealed or standby",
            Self::InvalidReference => "secret reference is invalid",
        };
        formatter.write_str(label)
    }
}

/// Errors observed at the provider adapter boundary.  `Unknown` is the only
/// variant that can produce an indeterminate outcome; no variant authorizes a
/// blind retry after a call has crossed the boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderAdapterError {
    InvalidGrant,
    Unauthorized,
    Conflict,
    Timeout,
    Unavailable,
    Sealed,
    StaleFence,
    SchemaInvalid,
    Unknown,
}

impl fmt::Display for ProviderAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Self::InvalidGrant => "provider rejected the grant",
            Self::Unauthorized => "provider denied the request",
            Self::Conflict => "provider reported a conflict",
            Self::Timeout => "provider timed out",
            Self::Unavailable => "provider is unavailable",
            Self::Sealed => "provider backend is sealed",
            Self::StaleFence => "provider rejected a stale fence",
            Self::SchemaInvalid => "provider returned an invalid schema",
            Self::Unknown => "provider outcome is unknown",
        };
        formatter.write_str(label)
    }
}

impl ProviderAdapterError {
    fn status(self) -> SecretProviderStatus {
        match self {
            Self::InvalidGrant => SecretProviderStatus::InvalidGrant,
            Self::Unauthorized => SecretProviderStatus::Unauthorized,
            Self::Conflict => SecretProviderStatus::Conflict,
            Self::Timeout => SecretProviderStatus::Timeout,
            Self::Unavailable => SecretProviderStatus::Unavailable,
            Self::Sealed => SecretProviderStatus::Sealed,
            Self::StaleFence => SecretProviderStatus::StaleFence,
            Self::SchemaInvalid => SecretProviderStatus::SchemaInvalid,
            Self::Unknown => SecretProviderStatus::Unknown,
        }
    }

    fn outcome(self) -> SecretRefOutcome {
        match self {
            Self::InvalidGrant => SecretRefOutcome::Quarantined,
            Self::Unknown => SecretRefOutcome::Indeterminate,
            Self::Unauthorized
            | Self::Conflict
            | Self::Timeout
            | Self::Unavailable
            | Self::Sealed
            | Self::StaleFence
            | Self::SchemaInvalid => SecretRefOutcome::TransientFailure,
        }
    }

    fn event(self) -> SecretRefEvent {
        match self {
            Self::InvalidGrant => SecretRefEvent::InvalidGrant,
            Self::Unknown => SecretRefEvent::ResponseUnknown,
            Self::Unauthorized
            | Self::Conflict
            | Self::Timeout
            | Self::Unavailable
            | Self::Sealed
            | Self::StaleFence
            | Self::SchemaInvalid => SecretRefEvent::TransientFailure,
        }
    }
}

impl SecretBackendError {
    fn provider_error(self) -> ProviderAdapterError {
        match self {
            // A missing reference cannot prove a successful rotation.  Keep
            // it in the bounded unavailable class rather than inventing a
            // terminal invalid-grant result.
            Self::NotFound => ProviderAdapterError::Unavailable,
            Self::Unauthorized => ProviderAdapterError::Unauthorized,
            Self::Timeout => ProviderAdapterError::Timeout,
            Self::Unavailable => ProviderAdapterError::Unavailable,
            Self::Sealed => ProviderAdapterError::Sealed,
            Self::InvalidReference => ProviderAdapterError::SchemaInvalid,
        }
    }
}

/// Process-local secret material.  The underlying bytes are intentionally not
/// serializable or printable and are zeroized when this value is dropped.
/// Providers should use [`Self::with_bytes`] only for the duration of their
/// synchronous call and must not retain or return the borrowed slice.
pub struct ProcessBoundSecret(Zeroizing<Vec<u8>>);

impl ProcessBoundSecret {
    /// Creates process-local material for a qualification backend.  A real
    /// backend would construct this value directly after an in-place read.
    pub fn from_bytes(bytes: impl AsRef<[u8]>) -> Self {
        Self(Zeroizing::new(bytes.as_ref().to_vec()))
    }

    /// Runs a provider operation against the borrowed bytes without exposing a
    /// byte-bearing value in any B3 request/response type.
    pub fn with_bytes<T>(&self, operation: impl FnOnce(&[u8]) -> T) -> T {
        operation(self.0.as_slice())
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl fmt::Debug for ProcessBoundSecret {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProcessBoundSecret")
            .field("len", &self.0.len())
            .finish_non_exhaustive()
    }
}

/// Process-bound backend boundary.  Implementations must not persist or
/// return the resolved bytes outside the returned zeroizing wrapper.
pub trait SecretRefBackend: Send + Sync {
    fn resolve(
        &self,
        secret_ref: &OpaqueSecretRef,
    ) -> Result<ProcessBoundSecret, SecretBackendError>;
}

/// Provider boundary used by the local adapter.  The only raw bytes appear as
/// a borrowed [`ProcessBoundSecret`] during the synchronous call.  Provider
/// results contain opaque references and digests only.
pub trait SecretRefProvider: Send + Sync {
    fn refresh(
        &self,
        request: &RefreshWithSecretRefRequest,
        secret: &ProcessBoundSecret,
    ) -> Result<ProviderRefreshResult, ProviderAdapterError>;

    fn rotate(
        &self,
        request: &RotateSecretRefRequest,
        secret: &ProcessBoundSecret,
    ) -> Result<ProviderRotationResult, ProviderAdapterError>;

    /// Provider-owned lookup by the durable operation key.  This is the
    /// decode-only `StatusByEffectKey` alias from the registry; it is never a
    /// dispatch operation and receives no secret material.
    fn status_by_operation_key(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<ProviderStatusResult, ProviderAdapterError>;

    fn status_by_effect_key(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<ProviderStatusResult, ProviderAdapterError> {
        self.status_by_operation_key(request)
    }
}

/// Provider response for a refresh call.  It deliberately has no raw token or
/// provider response-body field.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRefreshResult {
    pub response_id: String,
    pub provider_status: SecretProviderStatus,
    pub access_secret_ref: Option<OpaqueSecretRef>,
    pub refresh_secret_ref: Option<OpaqueSecretRef>,
    pub secret_revision: Option<u64>,
    pub response_digest: Sha256Digest,
}

/// Provider response for a rotation call.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRotationResult {
    pub response_id: String,
    pub provider_status: SecretProviderStatus,
    pub new_refresh_secret_ref: Option<OpaqueSecretRef>,
    pub secret_revision: Option<u64>,
    pub response_digest: Sha256Digest,
}

/// Provider-owned status lookup result.  The adapter adds the local evidence
/// sentinel and computes the binding digest before exposing the response.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderStatusResult {
    pub response_id: String,
    pub provider_status: SecretProviderStatus,
    pub secret_revision: u64,
    pub response_digest: Sha256Digest,
    pub status_revision: u64,
    pub observed_at: u64,
    pub provider_query_receipt_digest: Sha256Digest,
    pub new_access_secret_ref: Option<OpaqueSecretRef>,
    pub new_refresh_secret_ref: Option<OpaqueSecretRef>,
}

/// A deterministic in-memory backend used by qualification tests.  It is not
/// a substitute for OpenBao and is never wired to a runtime listener.
#[derive(Default)]
pub struct QualificationSecretBackend {
    entries: BTreeMap<String, (OpaqueSecretRef, Zeroizing<Vec<u8>>)>,
    forced_error: Option<SecretBackendError>,
}

impl QualificationSecretBackend {
    pub fn insert(
        &mut self,
        secret_ref: OpaqueSecretRef,
        bytes: impl AsRef<[u8]>,
    ) -> Result<(), SecretBackendError> {
        secret_ref
            .validate()
            .map_err(|_| SecretBackendError::InvalidReference)?;
        let bytes = bytes.as_ref();
        if Sha256Digest::for_bytes(bytes) != secret_ref.secret_digest {
            return Err(SecretBackendError::InvalidReference);
        }
        self.entries.insert(
            secret_ref
                .digest()
                .map_err(|_| SecretBackendError::InvalidReference)?
                .as_str()
                .to_string(),
            (secret_ref, Zeroizing::new(bytes.to_vec())),
        );
        Ok(())
    }

    pub fn set_error(&mut self, error: Option<SecretBackendError>) {
        self.forced_error = error;
    }

    pub fn clear_error(&mut self) {
        self.forced_error = None;
    }
}

impl SecretRefBackend for QualificationSecretBackend {
    fn resolve(
        &self,
        secret_ref: &OpaqueSecretRef,
    ) -> Result<ProcessBoundSecret, SecretBackendError> {
        secret_ref
            .validate()
            .map_err(|_| SecretBackendError::InvalidReference)?;
        if let Some(error) = self.forced_error {
            return Err(error);
        }
        let key = secret_ref
            .digest()
            .map_err(|_| SecretBackendError::InvalidReference)?;
        let Some((stored_ref, bytes)) = self.entries.get(key.as_str()) else {
            return Err(SecretBackendError::NotFound);
        };
        if stored_ref != secret_ref
            || Sha256Digest::for_bytes(bytes.as_slice()) != secret_ref.secret_digest
        {
            return Err(SecretBackendError::InvalidReference);
        }
        Ok(ProcessBoundSecret::from_bytes(bytes.as_slice()))
    }
}

/// Errors returned by the qualification adapter.  A binding or provider
/// error is reported without carrying provider bytes or headers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum B3AdapterError {
    InvalidRequest(String),
    Backend(SecretBackendError),
    Provider(ProviderAdapterError),
    ProviderResponseInvalid(String),
    Conflict,
    SingleflightConflict,
    ReconcileRequired,
    OperationNotFound,
    AlreadyTerminal,
    InvalidState(String),
}

impl fmt::Display for B3AdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(message) => write!(formatter, "invalid B3 request: {message}"),
            Self::Backend(error) => write!(formatter, "secret backend error: {error}"),
            Self::Provider(error) => write!(formatter, "provider adapter error: {error}"),
            Self::ProviderResponseInvalid(message) => {
                write!(formatter, "invalid provider response: {message}")
            }
            Self::Conflict => formatter.write_str("B3 operation conflict"),
            Self::SingleflightConflict => {
                formatter.write_str("B3 token-family singleflight conflict")
            }
            Self::ReconcileRequired => {
                formatter.write_str("B3 operation requires status reconciliation")
            }
            Self::OperationNotFound => formatter.write_str("B3 operation was not found"),
            Self::AlreadyTerminal => formatter.write_str("B3 operation is already terminal"),
            Self::InvalidState(message) => {
                write!(formatter, "invalid B3 operation state: {message}")
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OperationKind {
    Refresh,
    Rotate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum StoredResponse {
    Refresh(RefreshWithSecretRefResponse),
    Rotate(RotateSecretRefResponse),
}

struct OperationEntry {
    request_digest: Sha256Digest,
    claim_key: String,
    kind: OperationKind,
    record: SecretRefOperationRecord,
    response: Option<StoredResponse>,
}

/// Local process-bound adapter.  The map is intentionally in-memory and is
/// only a qualification witness; it is not the AuthBus durable writer.
pub struct ProcessBoundSecretRefAdapter<B, P> {
    backend: B,
    provider: P,
    retry_budget: u32,
    operations: BTreeMap<String, OperationEntry>,
    claims: BTreeMap<String, String>,
}

trait RequestRecordSource {
    fn operation_record(
        &self,
        retry_budget: u32,
    ) -> Result<SecretRefOperationRecord, AuthBusContractError>;
}

impl RequestRecordSource for RefreshWithSecretRefRequest {
    fn operation_record(
        &self,
        retry_budget: u32,
    ) -> Result<SecretRefOperationRecord, AuthBusContractError> {
        SecretRefOperationRecord::from_refresh_request(self, retry_budget)
    }
}

impl RequestRecordSource for RotateSecretRefRequest {
    fn operation_record(
        &self,
        retry_budget: u32,
    ) -> Result<SecretRefOperationRecord, AuthBusContractError> {
        // Rotation has the same identity/fence shape as refresh.  Convert
        // only the contract fields needed by the local operation record; no
        // secret bytes are copied or retained.
        let refresh = RefreshWithSecretRefRequest {
            schema_version: self.schema_version,
            operation_id: self.operation_id.clone(),
            refresh_operation_key: self.refresh_operation_key.clone(),
            command_id: self.command_id.clone(),
            run_id: self.run_id.clone(),
            profile_id: self.profile_id.clone(),
            provider_id: self.provider_id.clone(),
            token_family_id: self.token_family_id.clone(),
            secret_ref: self.secret_ref.clone(),
            expected_secret_revision: self.expected_secret_revision,
            idempotency_key: self.idempotency_key.clone(),
            payload_digest: self.payload_digest.clone(),
            policy_digest: self.policy_digest.clone(),
            scope_digest: self.scope_digest.clone(),
            authority_epoch: self.authority_epoch,
            owner_epoch: self.owner_epoch,
            generation: self.generation,
            fencing_token: self.fencing_token.clone(),
            logical_clock: self.logical_clock,
            causal_parent_event_id: self.causal_parent_event_id.clone(),
            deadline_at: self.deadline_at,
            purpose_digest: self.purpose_digest.clone(),
            audience: self.audience.clone(),
        };
        SecretRefOperationRecord::from_refresh_request(&refresh, retry_budget)
    }
}

impl<B, P> ProcessBoundSecretRefAdapter<B, P>
where
    B: SecretRefBackend,
    P: SecretRefProvider,
{
    pub fn new(backend: B, provider: P) -> Self {
        Self::with_retry_budget(backend, provider, /*retry_budget*/ 1)
    }

    pub fn with_retry_budget(backend: B, provider: P, retry_budget: u32) -> Self {
        Self {
            backend,
            provider,
            retry_budget,
            operations: BTreeMap::new(),
            claims: BTreeMap::new(),
        }
    }

    pub fn backend(&self) -> &B {
        &self.backend
    }

    pub fn backend_mut(&mut self) -> &mut B {
        &mut self.backend
    }

    pub fn provider(&self) -> &P {
        &self.provider
    }

    pub fn provider_mut(&mut self) -> &mut P {
        &mut self.provider
    }

    pub fn operation_state(&self, operation_id: &str) -> Option<SecretRefState> {
        self.operations
            .get(operation_id)
            .map(|entry| entry.record.state)
    }

    pub fn operation_count(&self) -> usize {
        self.operations.len()
    }

    /// Execute one refresh.  A repeated operation key replays a recorded
    /// response and never calls the provider a second time.  Non-terminal
    /// operations must use [`Self::status_by_operation_key`] instead.
    pub fn refresh(
        &mut self,
        request: RefreshWithSecretRefRequest,
    ) -> Result<RefreshWithSecretRefResponse, B3AdapterError> {
        request
            .validate()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        let request_digest = request
            .digest()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        if let Some(replay) = self.begin_or_replay(
            request.operation_id.as_str(),
            request.provider_id.as_str(),
            request.profile_id.as_str(),
            request.token_family_id.as_str(),
            OperationKind::Refresh,
            request_digest,
            &request,
        )? {
            return match replay {
                StoredResponse::Refresh(response) => Ok(response),
                StoredResponse::Rotate(_) => Err(B3AdapterError::Conflict),
            };
        }

        let provider_result = {
            let backend = &self.backend;
            let provider = &self.provider;
            backend
                .resolve(&request.secret_ref)
                .map_err(B3AdapterError::Backend)
                .and_then(|secret| {
                    let result = provider.refresh(&request, &secret);
                    // `secret` is dropped here, before any response is
                    // persisted or returned to the caller.
                    result.map_err(B3AdapterError::Provider)
                })
        };

        match provider_result {
            Ok(result) => self.finish_refresh(&request, result),
            Err(B3AdapterError::Backend(error)) => {
                self.finish_refresh_error(&request, error.provider_error())
            }
            Err(B3AdapterError::Provider(error)) => self.finish_refresh_error(&request, error),
            Err(error) => Err(error),
        }
    }

    /// Execute one refresh-token rotation with the same process-bound and
    /// singleflight rules as [`Self::refresh`].
    pub fn rotate(
        &mut self,
        request: RotateSecretRefRequest,
    ) -> Result<RotateSecretRefResponse, B3AdapterError> {
        request
            .validate()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        let request_digest = request
            .digest()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        if let Some(replay) = self.begin_or_replay(
            request.operation_id.as_str(),
            request.provider_id.as_str(),
            request.profile_id.as_str(),
            request.token_family_id.as_str(),
            OperationKind::Rotate,
            request_digest,
            &request,
        )? {
            return match replay {
                StoredResponse::Rotate(response) => Ok(response),
                StoredResponse::Refresh(_) => Err(B3AdapterError::Conflict),
            };
        }

        let provider_result = {
            let backend = &self.backend;
            let provider = &self.provider;
            backend
                .resolve(&request.secret_ref)
                .map_err(B3AdapterError::Backend)
                .and_then(|secret| {
                    let result = provider.rotate(&request, &secret);
                    result.map_err(B3AdapterError::Provider)
                })
        };

        match provider_result {
            Ok(result) => self.finish_rotate(&request, result),
            Err(B3AdapterError::Backend(error)) => {
                self.finish_rotate_error(&request, error.provider_error())
            }
            Err(B3AdapterError::Provider(error)) => self.finish_rotate_error(&request, error),
            Err(error) => Err(error),
        }
    }

    /// Perform a provider-owned lookup by operation key.  No secret is
    /// resolved and no dispatch method is reachable from this path.
    pub fn status_by_operation_key(
        &mut self,
        request: RefreshStatusByOperationKeyRequest,
    ) -> Result<RefreshStatusByOperationKeyResponse, B3AdapterError> {
        request
            .validate()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        let operation = self
            .operations
            .get(request.operation_id.as_str())
            .ok_or(B3AdapterError::OperationNotFound)?;
        if operation.record.refresh_operation_key != request.refresh_operation_key
            || operation.record.provider_id != request.provider_id
            || operation.record.profile_id != request.profile_id
            || operation.record.token_family_id != request.token_family_id
            || operation.record.expected_secret_revision != request.expected_secret_revision
            || operation.record.authority_epoch != request.authority_epoch
            || operation.record.owner_epoch != request.owner_epoch
            || operation.record.generation != request.generation
            || operation.record.fencing_token != request.fencing_token
        {
            return Err(B3AdapterError::Conflict);
        }
        if operation.record.state.is_terminal() {
            return Err(B3AdapterError::AlreadyTerminal);
        }

        let provider_result = self
            .provider
            .status_by_effect_key(&request)
            .map_err(B3AdapterError::Provider)?;
        let response = self.build_status_response(&request, provider_result)?;
        self.apply_status_transition(&request, response.outcome)?;
        Ok(response)
    }

    /// Registry alias for [`Self::status_by_operation_key`].
    pub fn status_by_effect_key(
        &mut self,
        request: RefreshStatusByOperationKeyRequest,
    ) -> Result<RefreshStatusByOperationKeyResponse, B3AdapterError> {
        self.status_by_operation_key(request)
    }

    #[allow(clippy::too_many_arguments)]
    fn begin_or_replay<R>(
        &mut self,
        operation_id: &str,
        provider_id: &str,
        profile_id: &str,
        token_family_id: &str,
        kind: OperationKind,
        request_digest: Sha256Digest,
        request: &R,
    ) -> Result<Option<StoredResponse>, B3AdapterError>
    where
        R: RequestRecordSource,
    {
        if let Some(existing) = self.operations.get(operation_id) {
            if existing.kind != kind || existing.request_digest != request_digest {
                return Err(B3AdapterError::Conflict);
            }
            return existing
                .response
                .clone()
                .map(Some)
                .ok_or(B3AdapterError::ReconcileRequired);
        }
        let claim_key = format!("{provider_id}:{profile_id}:{token_family_id}");
        if let Some(existing_operation) = self.claims.get(&claim_key)
            && existing_operation != operation_id
        {
            return Err(B3AdapterError::SingleflightConflict);
        }

        let mut record = request
            .operation_record(self.retry_budget)
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        record
            .transition(SecretRefEvent::Claim)
            .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        record
            .transition(SecretRefEvent::Dispatch)
            .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        // Insertion happens before resolve/provider call.  This is the local
        // witness for operation-key-before-call ordering; it is not a durable
        // fsync and therefore cannot be used as production authority.
        self.operations.insert(
            operation_id.to_string(),
            OperationEntry {
                request_digest,
                claim_key: claim_key.clone(),
                kind,
                record,
                response: None,
            },
        );
        self.claims.insert(claim_key, operation_id.to_string());
        Ok(None)
    }

    fn finish_refresh(
        &mut self,
        request: &RefreshWithSecretRefRequest,
        result: ProviderRefreshResult,
    ) -> Result<RefreshWithSecretRefResponse, B3AdapterError> {
        let outcome = outcome_for_status(result.provider_status);
        let response = RefreshWithSecretRefResponse {
            schema_version: request.schema_version,
            response_id: result.response_id,
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome,
            access_secret_ref: (outcome == SecretRefOutcome::Succeeded)
                .then_some(result.access_secret_ref)
                .flatten(),
            refresh_secret_ref: (outcome == SecretRefOutcome::Succeeded)
                .then_some(result.refresh_secret_ref)
                .flatten(),
            secret_revision: result.secret_revision,
            refresh_operation_key: request.refresh_operation_key.clone(),
            provider_status: result.provider_status,
            response_digest: result.response_digest,
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        if let Err(error) = response.validate_against(request) {
            self.mark_response_unknown(request.operation_id.as_str())?;
            return Err(B3AdapterError::ProviderResponseInvalid(error.to_string()));
        }
        self.apply_event(
            request.operation_id.as_str(),
            request,
            event_for_outcome(outcome),
        )?;
        self.store_response(
            request.operation_id.as_str(),
            StoredResponse::Refresh(response.clone()),
        )?;
        Ok(response)
    }

    fn finish_refresh_error(
        &mut self,
        request: &RefreshWithSecretRefRequest,
        error: ProviderAdapterError,
    ) -> Result<RefreshWithSecretRefResponse, B3AdapterError> {
        let outcome = error.outcome();
        let response = RefreshWithSecretRefResponse {
            schema_version: request.schema_version,
            response_id: local_response_id("refresh", request.operation_id.as_str()),
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome,
            access_secret_ref: None,
            refresh_secret_ref: None,
            secret_revision: None,
            refresh_operation_key: request.refresh_operation_key.clone(),
            provider_status: error.status(),
            response_digest: local_response_digest(
                "refresh-error",
                request.operation_id.as_str(),
                error.status(),
            ),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        response.validate_against(request).map_err(|validation| {
            B3AdapterError::ProviderResponseInvalid(validation.to_string())
        })?;
        self.apply_event(request.operation_id.as_str(), request, error.event())?;
        self.store_response(
            request.operation_id.as_str(),
            StoredResponse::Refresh(response.clone()),
        )?;
        Ok(response)
    }

    fn finish_rotate(
        &mut self,
        request: &RotateSecretRefRequest,
        result: ProviderRotationResult,
    ) -> Result<RotateSecretRefResponse, B3AdapterError> {
        let outcome = outcome_for_status(result.provider_status);
        let response = RotateSecretRefResponse {
            schema_version: request.schema_version,
            response_id: result.response_id,
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome,
            new_refresh_secret_ref: (outcome == SecretRefOutcome::Succeeded)
                .then_some(result.new_refresh_secret_ref)
                .flatten(),
            secret_revision: result.secret_revision,
            refresh_operation_key: request.refresh_operation_key.clone(),
            response_digest: result.response_digest,
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        if let Err(error) = response.validate_against(request) {
            self.mark_response_unknown(request.operation_id.as_str())?;
            return Err(B3AdapterError::ProviderResponseInvalid(error.to_string()));
        }
        self.apply_event(
            request.operation_id.as_str(),
            request,
            event_for_outcome(outcome),
        )?;
        self.store_response(
            request.operation_id.as_str(),
            StoredResponse::Rotate(response.clone()),
        )?;
        Ok(response)
    }

    fn finish_rotate_error(
        &mut self,
        request: &RotateSecretRefRequest,
        error: ProviderAdapterError,
    ) -> Result<RotateSecretRefResponse, B3AdapterError> {
        let outcome = error.outcome();
        let response = RotateSecretRefResponse {
            schema_version: request.schema_version,
            response_id: local_response_id("rotate", request.operation_id.as_str()),
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome,
            new_refresh_secret_ref: None,
            secret_revision: None,
            refresh_operation_key: request.refresh_operation_key.clone(),
            response_digest: local_response_digest(
                "rotate-error",
                request.operation_id.as_str(),
                error.status(),
            ),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        response.validate_against(request).map_err(|validation| {
            B3AdapterError::ProviderResponseInvalid(validation.to_string())
        })?;
        self.apply_event(request.operation_id.as_str(), request, error.event())?;
        self.store_response(
            request.operation_id.as_str(),
            StoredResponse::Rotate(response.clone()),
        )?;
        Ok(response)
    }

    fn build_status_response(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
        result: ProviderStatusResult,
    ) -> Result<RefreshStatusByOperationKeyResponse, B3AdapterError> {
        let outcome = outcome_for_status(result.provider_status);
        let mut response = RefreshStatusByOperationKeyResponse {
            schema_version: request.schema_version,
            response_id: result.response_id,
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            refresh_operation_key: request.refresh_operation_key.clone(),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
            outcome,
            secret_revision: result.secret_revision,
            response_digest: result.response_digest,
            provider_status: result.provider_status,
            status_revision: result.status_revision,
            observed_at: result.observed_at,
            binding_digest: local_response_digest(
                "status-binding-placeholder",
                request.operation_id.as_str(),
                result.provider_status,
            ),
            evidence_profile: "local-qualification-provider-status".to_string(),
            provider_query_receipt_digest: result.provider_query_receipt_digest,
            execution_mode: request.expected_execution_mode.clone(),
            mode_attestation_digest: Sha256Digest::for_bytes(b"hepta-authbus-b3-local-status-mode"),
            policy_digest: request.policy_digest.clone(),
            audience: request.audience.clone(),
            key_epoch: 0,
            issuer: "local-mode-registry".to_string(),
            new_access_secret_ref: (outcome == SecretRefOutcome::Succeeded)
                .then_some(result.new_access_secret_ref)
                .flatten(),
            new_refresh_secret_ref: (outcome == SecretRefOutcome::Succeeded)
                .then_some(result.new_refresh_secret_ref)
                .flatten(),
            signature: None,
            key_id: None,
            issued_at: None,
            expires_at: None,
        };
        response.binding_digest = response
            .expected_binding_digest()
            .map_err(|error| B3AdapterError::ProviderResponseInvalid(error.to_string()))?;
        response
            .validate_against(request)
            .map_err(|error| B3AdapterError::ProviderResponseInvalid(error.to_string()))?;
        Ok(response)
    }

    fn apply_status_transition(
        &mut self,
        request: &RefreshStatusByOperationKeyRequest,
        outcome: SecretRefOutcome,
    ) -> Result<(), B3AdapterError> {
        let fence = SecretRefCallbackFence::new(
            request.authority_epoch,
            request.owner_epoch,
            request.generation,
            request.fencing_token.clone(),
        )
        .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        let entry = self
            .operations
            .get_mut(request.operation_id.as_str())
            .ok_or(B3AdapterError::OperationNotFound)?;
        if entry.record.state == SecretRefState::Indeterminate {
            entry
                .record
                .transition(SecretRefEvent::Lookup)
                .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        } else if entry.record.state == SecretRefState::ManualRequired {
            entry
                .record
                .transition_with_fence(SecretRefEvent::ManualEvidenceSubmitted, &fence)
                .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        }
        let event = match outcome {
            SecretRefOutcome::Succeeded => SecretRefEvent::LookupRotated,
            SecretRefOutcome::Quarantined => SecretRefEvent::LookupInvalidGrant,
            SecretRefOutcome::TransientFailure => SecretRefEvent::LookupTransientFailure,
            SecretRefOutcome::Indeterminate => SecretRefEvent::LookupRetryable,
        };
        entry
            .record
            .transition_with_fence(event, &fence)
            .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        if entry.record.state.is_terminal() {
            self.claims.remove(&entry.claim_key);
        }
        Ok(())
    }

    fn apply_event<R: RequestIdentity>(
        &mut self,
        operation_id: &str,
        request: &R,
        event: SecretRefEvent,
    ) -> Result<(), B3AdapterError> {
        let fence = request
            .callback_fence()
            .map_err(|error| B3AdapterError::InvalidRequest(error.to_string()))?;
        let entry = self
            .operations
            .get_mut(operation_id)
            .ok_or(B3AdapterError::OperationNotFound)?;
        if event.requires_current_fence() {
            entry
                .record
                .transition_with_fence(event, &fence)
                .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        } else {
            entry
                .record
                .transition(event)
                .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        }
        if entry.record.state.is_terminal() {
            self.claims.remove(&entry.claim_key);
        }
        Ok(())
    }

    fn mark_response_unknown(&mut self, operation_id: &str) -> Result<(), B3AdapterError> {
        let entry = self
            .operations
            .get_mut(operation_id)
            .ok_or(B3AdapterError::OperationNotFound)?;
        let fence = SecretRefCallbackFence::new(
            entry.record.authority_epoch,
            entry.record.owner_epoch,
            entry.record.generation,
            entry.record.fencing_token.clone(),
        )
        .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        if entry.record.state == SecretRefState::InFlight {
            entry
                .record
                .transition_with_fence(SecretRefEvent::ResponseUnknown, &fence)
                .map_err(|error| B3AdapterError::InvalidState(error.to_string()))?;
        }
        Ok(())
    }

    fn store_response(
        &mut self,
        operation_id: &str,
        response: StoredResponse,
    ) -> Result<(), B3AdapterError> {
        let entry = self
            .operations
            .get_mut(operation_id)
            .ok_or(B3AdapterError::OperationNotFound)?;
        if entry.response.is_some() {
            return Err(B3AdapterError::Conflict);
        }
        entry.response = Some(response);
        Ok(())
    }
}

trait RequestIdentity {
    fn callback_fence(&self) -> Result<SecretRefCallbackFence, AuthBusContractError>;
}

impl RequestIdentity for RefreshWithSecretRefRequest {
    fn callback_fence(&self) -> Result<SecretRefCallbackFence, AuthBusContractError> {
        SecretRefCallbackFence::new(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            self.fencing_token.clone(),
        )
    }
}

impl RequestIdentity for RotateSecretRefRequest {
    fn callback_fence(&self) -> Result<SecretRefCallbackFence, AuthBusContractError> {
        SecretRefCallbackFence::new(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            self.fencing_token.clone(),
        )
    }
}

fn outcome_for_status(status: SecretProviderStatus) -> SecretRefOutcome {
    match status {
        SecretProviderStatus::Succeeded | SecretProviderStatus::Rotated => {
            SecretRefOutcome::Succeeded
        }
        SecretProviderStatus::InvalidGrant | SecretProviderStatus::Quarantined => {
            SecretRefOutcome::Quarantined
        }
        SecretProviderStatus::Unknown => SecretRefOutcome::Indeterminate,
        SecretProviderStatus::Unauthorized
        | SecretProviderStatus::Conflict
        | SecretProviderStatus::Timeout
        | SecretProviderStatus::Unavailable
        | SecretProviderStatus::Sealed
        | SecretProviderStatus::StaleFence
        | SecretProviderStatus::SchemaInvalid
        | SecretProviderStatus::TransientFailure => SecretRefOutcome::TransientFailure,
    }
}

fn event_for_outcome(outcome: SecretRefOutcome) -> SecretRefEvent {
    match outcome {
        SecretRefOutcome::Succeeded => SecretRefEvent::Rotated,
        SecretRefOutcome::Quarantined => SecretRefEvent::InvalidGrant,
        SecretRefOutcome::TransientFailure => SecretRefEvent::TransientFailure,
        SecretRefOutcome::Indeterminate => SecretRefEvent::ResponseUnknown,
    }
}

fn local_response_id(kind: &str, operation_id: &str) -> String {
    format!(
        "b3-{kind}-response:{}",
        Sha256Digest::for_bytes(format!("{kind}:{operation_id}").as_bytes()).as_str()
    )
}

fn local_response_digest(
    kind: &str,
    operation_id: &str,
    status: SecretProviderStatus,
) -> Sha256Digest {
    Sha256Digest::for_bytes(format!("{kind}:{operation_id}:{status:?}").as_bytes())
}
