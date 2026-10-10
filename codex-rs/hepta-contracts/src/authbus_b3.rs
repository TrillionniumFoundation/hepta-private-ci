//! B3 opaque-SecretRef refresh/rotation contracts.
//!
//! This module is a contracts-only seam for the process-bound AuthBus adapter
//! described by AUTHBUS.11 v1.3.  It deliberately has no provider client,
//! socket, listener, key store, or effect writer.  The only values that may
//! cross this boundary are opaque references and digests.  In particular, a
//! raw access token, refresh token, client secret, authorization header, or
//! provider response body cannot be represented by these types.

use serde::Deserialize;
use serde::Serialize;

use crate::Sha256Digest;

use super::AUTHBUS_CONTRACT_SCHEMA_VERSION;
use super::AuthBusContractError;
use super::canonical_json;
use super::contract_domain;
use super::domain_digest;
use super::validate_digest;
use super::validate_text;

/// B3 uses the same wire schema number as the B0--B2 contracts.
pub const AUTHBUS_B3_CONTRACT_SCHEMA_VERSION: u32 = AUTHBUS_CONTRACT_SCHEMA_VERSION;
/// This module is a qualification seam, never a production authority.
pub const AUTHBUS_B3_QUALIFICATION_ONLY: bool = true;
pub const AUTHBUS_B3_RAW_SECRET_BYTES_ALLOWED: bool = false;
pub const AUTHBUS_B3_STATUS_LOOKUP_ONLY: bool = true;

const MAX_ID_BYTES: usize = 512;
const MAX_MODE_BYTES: usize = 128;

fn error(message: impl Into<String>) -> AuthBusContractError {
    AuthBusContractError::new(message)
}

fn validate_schema(schema_version: u32, type_name: &str) -> Result<(), AuthBusContractError> {
    if schema_version != AUTHBUS_B3_CONTRACT_SCHEMA_VERSION {
        return Err(error(format!("unsupported {type_name} schema version")));
    }
    Ok(())
}

fn validate_id(value: &str, label: &str) -> Result<(), AuthBusContractError> {
    validate_text(value, label, MAX_ID_BYTES)
}

fn validate_nonzero(value: u64, label: &str) -> Result<(), AuthBusContractError> {
    if value == 0 {
        return Err(error(format!("{label} must be non-zero")));
    }
    Ok(())
}

fn push_bytes(buffer: &mut Vec<u8>, bytes: &[u8]) {
    buffer.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    buffer.extend_from_slice(bytes);
}

fn push_text(buffer: &mut Vec<u8>, value: &str) {
    push_bytes(buffer, value.as_bytes());
}

fn push_digest(buffer: &mut Vec<u8>, value: &Sha256Digest) {
    push_text(buffer, value.as_str());
}

fn push_u64(buffer: &mut Vec<u8>, value: u64) {
    push_bytes(buffer, &value.to_be_bytes());
}

/// Derive the durable operation key specified by the canonical registry.
/// The key is deterministic for the same operation and binds every identity,
/// payload, policy and fence component that can affect a refresh call.
#[allow(clippy::too_many_arguments)]
pub fn derive_refresh_operation_key(
    provider_id: &str,
    profile_id: &str,
    token_family_id: &str,
    idempotency_key: &str,
    expected_secret_revision: u64,
    scope_digest: &Sha256Digest,
    purpose_digest: &Sha256Digest,
    payload_digest: &Sha256Digest,
    policy_digest: &Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &Sha256Digest,
) -> String {
    let mut preimage = Vec::new();
    push_text(&mut preimage, provider_id);
    push_text(&mut preimage, profile_id);
    push_text(&mut preimage, token_family_id);
    push_text(&mut preimage, idempotency_key);
    push_u64(&mut preimage, expected_secret_revision);
    push_digest(&mut preimage, scope_digest);
    push_digest(&mut preimage, purpose_digest);
    push_digest(&mut preimage, payload_digest);
    push_digest(&mut preimage, policy_digest);
    push_u64(&mut preimage, authority_epoch);
    push_u64(&mut preimage, owner_epoch);
    push_u64(&mut preimage, generation);
    push_digest(&mut preimage, fencing_token);
    format!(
        "rok:{}",
        domain_digest("hepta.auth.refresh-operation.v1", &preimage).as_str()
    )
}

/// Derive the operation identifier bound to one refresh operation key.
pub fn derive_refresh_operation_id(
    refresh_operation_key: &str,
    idempotency_key: &str,
    payload_digest: &Sha256Digest,
) -> String {
    let mut preimage = Vec::new();
    push_text(&mut preimage, refresh_operation_key);
    push_text(&mut preimage, idempotency_key);
    push_digest(&mut preimage, payload_digest);
    format!(
        "op:{}",
        domain_digest("hepta.auth.refresh-operation-id.v1", &preimage).as_str()
    )
}

/// An opaque, process-bound reference to secret material.  The referenced
/// bytes never appear in a request, response, receipt, or log value.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OpaqueSecretRef {
    pub backend_id: String,
    pub mount: String,
    pub key_id: String,
    pub version: u64,
    pub secret_digest: Sha256Digest,
}

impl OpaqueSecretRef {
    pub fn new(
        backend_id: impl Into<String>,
        mount: impl Into<String>,
        key_id: impl Into<String>,
        version: u64,
        secret_digest: Sha256Digest,
    ) -> Result<Self, AuthBusContractError> {
        let secret_ref = Self {
            backend_id: backend_id.into(),
            mount: mount.into(),
            key_id: key_id.into(),
            version,
            secret_digest,
        };
        secret_ref.validate()?;
        Ok(secret_ref)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_id(&self.backend_id, "secret backend id")?;
        validate_id(&self.mount, "secret mount")?;
        validate_id(&self.key_id, "secret key id")?;
        validate_nonzero(self.version, "secret version")?;
        validate_digest(&self.secret_digest, "secret digest")
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("opaque-secret-ref"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Name used by adapter code and registry prose for the same wire shape.
pub type ProcessBoundSecretRef = OpaqueSecretRef;
/// Compatibility name for callers that use the registry's “binding” term.
pub type SecretRefBinding = OpaqueSecretRef;

/// Outcome of a refresh/rotation operation or a status lookup.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SecretRefOutcome {
    Succeeded,
    TransientFailure,
    Indeterminate,
    Quarantined,
}

impl SecretRefOutcome {
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Quarantined)
    }
}

/// Classification is metadata; it is not itself a durable state transition.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SecretRefErrorClass {
    None,
    InvalidGrant,
    Unauthorized,
    Conflict,
    Timeout,
    Unavailable,
    Sealed,
    StaleFence,
    SchemaInvalid,
}

/// Provider observation class.  No provider headers or response body are
/// carried; an adapter may only publish this bounded classification.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SecretProviderStatus {
    Succeeded,
    Rotated,
    InvalidGrant,
    Unauthorized,
    Conflict,
    Timeout,
    Unavailable,
    Sealed,
    StaleFence,
    SchemaInvalid,
    TransientFailure,
    Unknown,
    Quarantined,
}

impl SecretProviderStatus {
    pub fn error_class(self) -> SecretRefErrorClass {
        match self {
            Self::Succeeded | Self::Rotated => SecretRefErrorClass::None,
            Self::InvalidGrant => SecretRefErrorClass::InvalidGrant,
            Self::Unauthorized => SecretRefErrorClass::Unauthorized,
            Self::Conflict => SecretRefErrorClass::Conflict,
            Self::Timeout => SecretRefErrorClass::Timeout,
            Self::Unavailable | Self::TransientFailure | Self::Unknown => {
                SecretRefErrorClass::Unavailable
            }
            Self::Sealed => SecretRefErrorClass::Sealed,
            Self::StaleFence => SecretRefErrorClass::StaleFence,
            Self::SchemaInvalid => SecretRefErrorClass::SchemaInvalid,
            Self::Quarantined => SecretRefErrorClass::InvalidGrant,
        }
    }
}

/// Durable operation state.  `Succeeded` and `Quarantined` are terminal;
/// `Indeterminate` and `ManualRequired` are holds, never implicit success.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SecretRefState {
    Idle,
    Claimed,
    InFlight,
    Succeeded,
    TransientFailure,
    Indeterminate,
    Reconciling,
    Backoff,
    Quarantined,
    ManualRequired,
}

impl SecretRefState {
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Quarantined)
    }

    pub fn dispatch_allowed(self) -> bool {
        matches!(self, Self::Claimed)
    }

    pub fn reconcile_allowed(self) -> bool {
        matches!(
            self,
            Self::Indeterminate | Self::Reconciling | Self::ManualRequired
        )
    }

    /// Apply one explicit state-machine event.  There is intentionally no
    /// “retry” event from `Indeterminate`; only a status lookup is accepted.
    pub fn transition(self, event: SecretRefEvent) -> Result<Self, AuthBusContractError> {
        let next = match (self, event) {
            (Self::Idle, SecretRefEvent::Claim) => Self::Claimed,
            (Self::Claimed, SecretRefEvent::Dispatch) => Self::InFlight,
            (Self::InFlight, SecretRefEvent::Rotated) => Self::Succeeded,
            (Self::InFlight, SecretRefEvent::InvalidGrant) => Self::Quarantined,
            (Self::InFlight, SecretRefEvent::TransientFailure) => Self::TransientFailure,
            (Self::InFlight, SecretRefEvent::ResponseUnknown) => Self::Indeterminate,
            (Self::TransientFailure, SecretRefEvent::RetryScheduled) => Self::Backoff,
            (Self::TransientFailure, SecretRefEvent::RetryBudgetExhausted) => Self::ManualRequired,
            (Self::Indeterminate, SecretRefEvent::Lookup) => Self::Reconciling,
            (Self::Reconciling, SecretRefEvent::LookupRotated) => Self::Succeeded,
            (Self::Reconciling, SecretRefEvent::LookupInvalidGrant) => Self::Quarantined,
            (Self::Reconciling, SecretRefEvent::LookupTransientFailure)
            | (Self::Reconciling, SecretRefEvent::LookupRetryable) => Self::Backoff,
            (Self::Reconciling, SecretRefEvent::ManualRequired) => Self::ManualRequired,
            (Self::ManualRequired, SecretRefEvent::ManualEvidenceSubmitted) => Self::Reconciling,
            (Self::Backoff, SecretRefEvent::ClaimAgain) => Self::Claimed,
            _ => {
                return Err(error(format!(
                    "invalid SecretRef transition from {self:?} with {event:?}"
                )));
            }
        };
        Ok(next)
    }
}

/// Explicit state-machine events.  Names mirror the canonical registry; the
/// compatibility aliases are decode-only at the wire/projection layer.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretRefEvent {
    Claim,
    Dispatch,
    Rotated,
    InvalidGrant,
    TransientFailure,
    RetryScheduled,
    RetryBudgetExhausted,
    ResponseUnknown,
    Lookup,
    LookupRotated,
    LookupInvalidGrant,
    LookupTransientFailure,
    LookupRetryable,
    ManualRequired,
    ManualEvidenceSubmitted,
    ClaimAgain,
}

impl SecretRefEvent {
    /// Returns whether this event carries an observation or decision that
    /// crossed the provider/evidence boundary.  Such events must be checked
    /// against the operation's current identity fence before they can mutate
    /// a durable record.  Local scheduling events (claim, dispatch, lookup,
    /// and retry bookkeeping) do not carry an external callback and remain
    /// available through [`SecretRefOperationRecord::transition`].
    pub const fn requires_current_fence(self) -> bool {
        matches!(
            self,
            Self::Rotated
                | Self::InvalidGrant
                | Self::TransientFailure
                | Self::ResponseUnknown
                | Self::LookupRotated
                | Self::LookupInvalidGrant
                | Self::LookupTransientFailure
                | Self::LookupRetryable
                | Self::ManualRequired
                | Self::ManualEvidenceSubmitted
        )
    }
}

/// Identity fence supplied with an adapter response or reconciliation
/// decision.  It is intentionally separate from the operation record so a
/// callback cannot silently borrow the record's own (possibly stale) values.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretRefCallbackFence {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
}

impl SecretRefCallbackFence {
    pub fn new(
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: Sha256Digest,
    ) -> Result<Self, AuthBusContractError> {
        let fence = Self {
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token,
        };
        fence.validate()?;
        Ok(fence)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_nonzero(self.authority_epoch, "callback authority epoch")?;
        validate_nonzero(self.owner_epoch, "callback owner epoch")?;
        validate_nonzero(self.generation, "callback generation")?;
        validate_digest(&self.fencing_token, "callback fencing token")
    }
}

/// Bind the fields common to refresh and rotate requests and enforce the
/// registry's operation-key and operation-id formulas.
#[allow(clippy::too_many_arguments)]
fn validate_mutation_binding(
    operation_id: &str,
    refresh_operation_key: &str,
    command_id: &str,
    run_id: &str,
    profile_id: &str,
    provider_id: &str,
    token_family_id: &str,
    expected_secret_revision: u64,
    idempotency_key: &str,
    payload_digest: &Sha256Digest,
    policy_digest: &Sha256Digest,
    scope_digest: &Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &Sha256Digest,
    logical_clock: u64,
    causal_parent_event_id: &str,
    deadline_at: u64,
    purpose_digest: &Sha256Digest,
    audience: &str,
    secret_ref: &OpaqueSecretRef,
) -> Result<(), AuthBusContractError> {
    for (label, value) in [
        ("operation id", operation_id),
        ("refresh operation key", refresh_operation_key),
        ("command id", command_id),
        ("run id", run_id),
        ("profile id", profile_id),
        ("provider id", provider_id),
        ("token family id", token_family_id),
        ("idempotency key", idempotency_key),
        ("causal parent event id", causal_parent_event_id),
        ("audience", audience),
    ] {
        validate_id(value, label)?;
    }
    validate_nonzero(expected_secret_revision, "expected secret revision")?;
    validate_digest(payload_digest, "payload digest")?;
    validate_digest(policy_digest, "policy digest")?;
    validate_digest(scope_digest, "scope digest")?;
    validate_digest(purpose_digest, "purpose digest")?;
    validate_digest(fencing_token, "fencing token")?;
    for (label, value) in [
        ("authority epoch", authority_epoch),
        ("owner epoch", owner_epoch),
        ("generation", generation),
        ("logical clock", logical_clock),
        ("deadline", deadline_at),
    ] {
        validate_nonzero(value, label)?;
    }
    secret_ref.validate()?;
    let expected_key = derive_refresh_operation_key(
        provider_id,
        profile_id,
        token_family_id,
        idempotency_key,
        expected_secret_revision,
        scope_digest,
        purpose_digest,
        payload_digest,
        policy_digest,
        authority_epoch,
        owner_epoch,
        generation,
        fencing_token,
    );
    if refresh_operation_key != expected_key {
        return Err(error("refresh operation key binding mismatch"));
    }
    let expected_operation_id =
        derive_refresh_operation_id(refresh_operation_key, idempotency_key, payload_digest);
    if operation_id != expected_operation_id {
        return Err(error("refresh operation id binding mismatch"));
    }
    Ok(())
}

/// Request for a process-bound refresh operation.  All request fields are
/// explicit so serde's unknown-field rejection catches raw-token injections.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RefreshWithSecretRefRequest {
    pub schema_version: u32,
    pub operation_id: String,
    pub refresh_operation_key: String,
    pub command_id: String,
    pub run_id: String,
    pub profile_id: String,
    pub provider_id: String,
    pub token_family_id: String,
    pub secret_ref: OpaqueSecretRef,
    pub expected_secret_revision: u64,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub scope_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
    pub logical_clock: u64,
    pub causal_parent_event_id: String,
    pub deadline_at: u64,
    pub purpose_digest: Sha256Digest,
    pub audience: String,
}

impl RefreshWithSecretRefRequest {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "RefreshWithSecretRefRequest")?;
        validate_mutation_binding(
            &self.operation_id,
            &self.refresh_operation_key,
            &self.command_id,
            &self.run_id,
            &self.profile_id,
            &self.provider_id,
            &self.token_family_id,
            self.expected_secret_revision,
            &self.idempotency_key,
            &self.payload_digest,
            &self.policy_digest,
            &self.scope_digest,
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token,
            self.logical_clock,
            &self.causal_parent_event_id,
            self.deadline_at,
            &self.purpose_digest,
            &self.audience,
            &self.secret_ref,
        )
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("refresh-with-secret-ref-request"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Request for process-bound refresh-token rotation.  Its wire shape is
/// intentionally identical to refresh, with the operation name carried by
/// the endpoint/type rather than an extra field.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RotateSecretRefRequest {
    pub schema_version: u32,
    pub operation_id: String,
    pub refresh_operation_key: String,
    pub command_id: String,
    pub run_id: String,
    pub profile_id: String,
    pub provider_id: String,
    pub token_family_id: String,
    pub secret_ref: OpaqueSecretRef,
    pub expected_secret_revision: u64,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub scope_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
    pub logical_clock: u64,
    pub causal_parent_event_id: String,
    pub deadline_at: u64,
    pub purpose_digest: Sha256Digest,
    pub audience: String,
}

impl RotateSecretRefRequest {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "RotateSecretRefRequest")?;
        validate_mutation_binding(
            &self.operation_id,
            &self.refresh_operation_key,
            &self.command_id,
            &self.run_id,
            &self.profile_id,
            &self.provider_id,
            &self.token_family_id,
            self.expected_secret_revision,
            &self.idempotency_key,
            &self.payload_digest,
            &self.policy_digest,
            &self.scope_digest,
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token,
            self.logical_clock,
            &self.causal_parent_event_id,
            self.deadline_at,
            &self.purpose_digest,
            &self.audience,
            &self.secret_ref,
        )
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("rotate-secret-ref-request"),
            &self.canonical_bytes()?,
        ))
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_response_identity(
    response_id: &str,
    operation_id: &str,
    provider_id: &str,
    profile_id: &str,
    token_family_id: &str,
    refresh_operation_key: &str,
    idempotency_key: &str,
    payload_digest: &Sha256Digest,
    expected_secret_revision: u64,
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &Sha256Digest,
) -> Result<(), AuthBusContractError> {
    for (label, value) in [
        ("response id", response_id),
        ("response operation id", operation_id),
        ("response provider id", provider_id),
        ("response profile id", profile_id),
        ("response token family id", token_family_id),
        ("response refresh operation key", refresh_operation_key),
        ("response idempotency key", idempotency_key),
    ] {
        validate_id(value, label)?;
    }
    validate_nonzero(
        expected_secret_revision,
        "response expected secret revision",
    )?;
    validate_digest(payload_digest, "response payload digest")?;
    validate_digest(fencing_token, "response fencing token")?;
    for (label, value) in [
        ("response authority epoch", authority_epoch),
        ("response owner epoch", owner_epoch),
        ("response generation", generation),
    ] {
        validate_nonzero(value, label)?;
    }
    Ok(())
}

fn validate_ref_for_outcome(
    outcome: SecretRefOutcome,
    reference: Option<&OpaqueSecretRef>,
    label: &str,
) -> Result<(), AuthBusContractError> {
    if let Some(reference) = reference {
        reference.validate()?;
        if !matches!(outcome, SecretRefOutcome::Succeeded) {
            return Err(error(format!("{label} is forbidden for {outcome:?}")));
        }
    } else if outcome == SecretRefOutcome::Succeeded {
        return Err(error(format!("{label} is required for success")));
    }
    Ok(())
}

/// Keep the provider classification and durable outcome in the same
/// conservative projection.  A positive provider classification can never
/// be wrapped as a hold, and an unknown/negative classification can never be
/// presented as a successful refresh.  More specific quarantine and
/// indeterminate checks below retain their dedicated error messages.
fn validate_outcome_status(
    outcome: SecretRefOutcome,
    provider_status: SecretProviderStatus,
) -> Result<(), AuthBusContractError> {
    match outcome {
        SecretRefOutcome::Succeeded
            if !matches!(
                provider_status,
                SecretProviderStatus::Succeeded | SecretProviderStatus::Rotated
            ) =>
        {
            Err(error(
                "successful SecretRef outcome requires a positive provider status",
            ))
        }
        SecretRefOutcome::TransientFailure
            if matches!(
                provider_status,
                SecretProviderStatus::Succeeded
                    | SecretProviderStatus::Rotated
                    | SecretProviderStatus::InvalidGrant
                    | SecretProviderStatus::Quarantined
                    | SecretProviderStatus::Unknown
            ) =>
        {
            Err(error(
                "transient SecretRef outcome cannot carry a terminal or unknown provider status",
            ))
        }
        SecretRefOutcome::Indeterminate if provider_status != SecretProviderStatus::Unknown => Err(
            error("indeterminate SecretRef outcome requires unknown provider status"),
        ),
        SecretRefOutcome::Quarantined
            if !matches!(
                provider_status,
                SecretProviderStatus::InvalidGrant | SecretProviderStatus::Quarantined
            ) =>
        {
            Err(error(
                "quarantined SecretRef outcome requires invalid-grant provider status",
            ))
        }
        _ => Ok(()),
    }
}

/// Refresh response.  A non-success response cannot carry a new secret
/// reference; an indeterminate response is therefore safe to persist and
/// reconcile by operation key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RefreshWithSecretRefResponse {
    pub schema_version: u32,
    pub response_id: String,
    pub operation_id: String,
    pub provider_id: String,
    pub profile_id: String,
    pub token_family_id: String,
    pub outcome: SecretRefOutcome,
    pub access_secret_ref: Option<OpaqueSecretRef>,
    pub refresh_secret_ref: Option<OpaqueSecretRef>,
    pub secret_revision: Option<u64>,
    pub refresh_operation_key: String,
    pub provider_status: SecretProviderStatus,
    pub response_digest: Sha256Digest,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub expected_secret_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
}

impl RefreshWithSecretRefResponse {
    pub fn validate_against(
        &self,
        request: &RefreshWithSecretRefRequest,
    ) -> Result<(), AuthBusContractError> {
        request.validate()?;
        validate_schema(self.schema_version, "RefreshWithSecretRefResponse")?;
        validate_response_identity(
            &self.response_id,
            &self.operation_id,
            &self.provider_id,
            &self.profile_id,
            &self.token_family_id,
            &self.refresh_operation_key,
            &self.idempotency_key,
            &self.payload_digest,
            self.expected_secret_revision,
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token,
        )?;
        if self.operation_id != request.operation_id
            || self.provider_id != request.provider_id
            || self.profile_id != request.profile_id
            || self.token_family_id != request.token_family_id
            || self.refresh_operation_key != request.refresh_operation_key
            || self.idempotency_key != request.idempotency_key
            || self.payload_digest != request.payload_digest
            || self.expected_secret_revision != request.expected_secret_revision
            || self.authority_epoch != request.authority_epoch
            || self.owner_epoch != request.owner_epoch
            || self.generation != request.generation
            || self.fencing_token != request.fencing_token
        {
            return Err(error("refresh response request binding mismatch"));
        }
        validate_digest(&self.response_digest, "refresh response digest")?;
        validate_ref_for_outcome(
            self.outcome,
            self.access_secret_ref.as_ref(),
            "access secret reference",
        )?;
        validate_ref_for_outcome(
            self.outcome,
            self.refresh_secret_ref.as_ref(),
            "refresh secret reference",
        )?;
        validate_outcome_status(self.outcome, self.provider_status)?;
        if self.outcome == SecretRefOutcome::Succeeded {
            let revision = self
                .secret_revision
                .ok_or_else(|| error("successful refresh must include secret revision"))?;
            if revision <= self.expected_secret_revision {
                return Err(error("successful refresh revision must advance"));
            }
        } else if self.secret_revision.is_some_and(|revision| revision == 0) {
            return Err(error(
                "non-success refresh revision must be absent or non-zero",
            ));
        }
        if self.outcome == SecretRefOutcome::Indeterminate
            && self.provider_status != SecretProviderStatus::Unknown
        {
            return Err(error(
                "indeterminate refresh must report unknown provider status",
            ));
        }
        if self.outcome == SecretRefOutcome::Quarantined
            && !matches!(
                self.provider_status,
                SecretProviderStatus::InvalidGrant | SecretProviderStatus::Quarantined
            )
        {
            return Err(error(
                "quarantined refresh requires invalid-grant classification",
            ));
        }
        Ok(())
    }

    pub fn canonical_bytes(
        &self,
        request: &RefreshWithSecretRefRequest,
    ) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate_against(request)?;
        canonical_json(self)
    }

    pub fn digest(
        &self,
        request: &RefreshWithSecretRefRequest,
    ) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("refresh-with-secret-ref-response"),
            &self.canonical_bytes(request)?,
        ))
    }
}

/// Rotation response.  Unlike refresh, only the new refresh reference is
/// returned by this operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RotateSecretRefResponse {
    pub schema_version: u32,
    pub response_id: String,
    pub operation_id: String,
    pub provider_id: String,
    pub profile_id: String,
    pub token_family_id: String,
    pub outcome: SecretRefOutcome,
    pub new_refresh_secret_ref: Option<OpaqueSecretRef>,
    pub secret_revision: Option<u64>,
    pub refresh_operation_key: String,
    pub response_digest: Sha256Digest,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub expected_secret_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
}

impl RotateSecretRefResponse {
    pub fn validate_against(
        &self,
        request: &RotateSecretRefRequest,
    ) -> Result<(), AuthBusContractError> {
        request.validate()?;
        validate_schema(self.schema_version, "RotateSecretRefResponse")?;
        validate_response_identity(
            &self.response_id,
            &self.operation_id,
            &self.provider_id,
            &self.profile_id,
            &self.token_family_id,
            &self.refresh_operation_key,
            &self.idempotency_key,
            &self.payload_digest,
            self.expected_secret_revision,
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token,
        )?;
        if self.operation_id != request.operation_id
            || self.provider_id != request.provider_id
            || self.profile_id != request.profile_id
            || self.token_family_id != request.token_family_id
            || self.refresh_operation_key != request.refresh_operation_key
            || self.idempotency_key != request.idempotency_key
            || self.payload_digest != request.payload_digest
            || self.expected_secret_revision != request.expected_secret_revision
            || self.authority_epoch != request.authority_epoch
            || self.owner_epoch != request.owner_epoch
            || self.generation != request.generation
            || self.fencing_token != request.fencing_token
        {
            return Err(error("rotation response request binding mismatch"));
        }
        validate_digest(&self.response_digest, "rotation response digest")?;
        validate_ref_for_outcome(
            self.outcome,
            self.new_refresh_secret_ref.as_ref(),
            "new refresh secret reference",
        )?;
        if self.outcome == SecretRefOutcome::Succeeded {
            let revision = self
                .secret_revision
                .ok_or_else(|| error("successful rotation must include secret revision"))?;
            if revision <= self.expected_secret_revision {
                return Err(error("successful rotation revision must advance"));
            }
        } else if self.secret_revision.is_some_and(|revision| revision == 0) {
            return Err(error(
                "non-success rotation revision must be absent or non-zero",
            ));
        }
        Ok(())
    }

    pub fn canonical_bytes(
        &self,
        request: &RotateSecretRefRequest,
    ) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate_against(request)?;
        canonical_json(self)
    }

    pub fn digest(
        &self,
        request: &RotateSecretRefRequest,
    ) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("rotate-secret-ref-response"),
            &self.canonical_bytes(request)?,
        ))
    }
}

/// Lookup-only request used after a response was lost.  Dispatchers must not
/// accept this type as a new provider operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RefreshStatusByOperationKeyRequest {
    pub schema_version: u32,
    pub operation_id: String,
    pub provider_id: String,
    pub profile_id: String,
    pub token_family_id: String,
    pub refresh_operation_key: String,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub expected_secret_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
    pub deadline_at: u64,
    pub audience: String,
    pub expected_execution_mode: String,
    pub policy_digest: Sha256Digest,
}

impl RefreshStatusByOperationKeyRequest {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "RefreshStatusByOperationKeyRequest")?;
        for (label, value) in [
            ("status operation id", self.operation_id.as_str()),
            ("status provider id", self.provider_id.as_str()),
            ("status profile id", self.profile_id.as_str()),
            ("status token family id", self.token_family_id.as_str()),
            (
                "status refresh operation key",
                self.refresh_operation_key.as_str(),
            ),
            ("status idempotency key", self.idempotency_key.as_str()),
            ("status audience", self.audience.as_str()),
        ] {
            validate_id(value, label)?;
        }
        validate_text(
            &self.expected_execution_mode,
            "expected execution mode",
            MAX_MODE_BYTES,
        )?;
        validate_nonzero(
            self.expected_secret_revision,
            "status expected secret revision",
        )?;
        validate_nonzero(self.authority_epoch, "status authority epoch")?;
        validate_nonzero(self.owner_epoch, "status owner epoch")?;
        validate_nonzero(self.generation, "status generation")?;
        validate_nonzero(self.deadline_at, "status deadline")?;
        validate_digest(&self.payload_digest, "status payload digest")?;
        validate_digest(&self.fencing_token, "status fencing token")?;
        validate_digest(&self.policy_digest, "status policy digest")?;
        let expected_operation_id = derive_refresh_operation_id(
            &self.refresh_operation_key,
            &self.idempotency_key,
            &self.payload_digest,
        );
        if self.operation_id != expected_operation_id {
            return Err(error("status operation id binding mismatch"));
        }
        Ok(())
    }

    pub fn dispatch_allowed(&self) -> bool {
        false
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("refresh-status-by-operation-key-request"),
            &self.canonical_bytes()?,
        ))
    }
}

fn status_binding_digest(
    response: &RefreshStatusByOperationKeyResponse,
) -> Result<Sha256Digest, AuthBusContractError> {
    #[derive(Serialize)]
    struct Binding<'a> {
        provider_id: &'a str,
        profile_id: &'a str,
        token_family_id: &'a str,
        refresh_operation_key: &'a str,
        idempotency_key: &'a str,
        payload_digest: &'a Sha256Digest,
        expected_secret_revision: u64,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: &'a Sha256Digest,
        outcome: SecretRefOutcome,
        secret_revision: u64,
        execution_mode: &'a str,
        policy_digest: &'a Sha256Digest,
        audience: &'a str,
        key_epoch: u64,
        issuer: &'a str,
        evidence_profile: &'a str,
        provider_query_receipt_digest: &'a Sha256Digest,
        mode_attestation_digest: &'a Sha256Digest,
    }
    let bytes = canonical_json(&Binding {
        provider_id: &response.provider_id,
        profile_id: &response.profile_id,
        token_family_id: &response.token_family_id,
        refresh_operation_key: &response.refresh_operation_key,
        idempotency_key: &response.idempotency_key,
        payload_digest: &response.payload_digest,
        expected_secret_revision: response.expected_secret_revision,
        authority_epoch: response.authority_epoch,
        owner_epoch: response.owner_epoch,
        generation: response.generation,
        fencing_token: &response.fencing_token,
        outcome: response.outcome,
        secret_revision: response.secret_revision,
        execution_mode: &response.execution_mode,
        policy_digest: &response.policy_digest,
        audience: &response.audience,
        key_epoch: response.key_epoch,
        issuer: &response.issuer,
        evidence_profile: &response.evidence_profile,
        provider_query_receipt_digest: &response.provider_query_receipt_digest,
        mode_attestation_digest: &response.mode_attestation_digest,
    })?;
    Ok(domain_digest("hepta.auth.refresh-status.v1", &bytes))
}

/// Status observation.  It is a lookup result, never a dispatch permit.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RefreshStatusByOperationKeyResponse {
    pub schema_version: u32,
    pub response_id: String,
    pub operation_id: String,
    pub provider_id: String,
    pub profile_id: String,
    pub token_family_id: String,
    pub refresh_operation_key: String,
    pub idempotency_key: String,
    pub payload_digest: Sha256Digest,
    pub expected_secret_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
    pub outcome: SecretRefOutcome,
    pub secret_revision: u64,
    pub response_digest: Sha256Digest,
    pub provider_status: SecretProviderStatus,
    pub status_revision: u64,
    pub observed_at: u64,
    pub binding_digest: Sha256Digest,
    pub evidence_profile: String,
    pub provider_query_receipt_digest: Sha256Digest,
    pub execution_mode: String,
    pub mode_attestation_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub audience: String,
    pub key_epoch: u64,
    pub issuer: String,
    pub new_access_secret_ref: Option<OpaqueSecretRef>,
    pub new_refresh_secret_ref: Option<OpaqueSecretRef>,
    pub signature: Option<Sha256Digest>,
    pub key_id: Option<String>,
    pub issued_at: Option<u64>,
    pub expires_at: Option<u64>,
}

impl RefreshStatusByOperationKeyResponse {
    /// Recomputes the canonical binding digest without trusting the value
    /// carried by a deserialized provider response.  Adapters use this helper
    /// before exposing a status observation on the lookup-only boundary.
    pub fn expected_binding_digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        status_binding_digest(self)
    }

    pub fn validate_against(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<(), AuthBusContractError> {
        request.validate()?;
        validate_schema(self.schema_version, "RefreshStatusByOperationKeyResponse")?;
        for (label, value) in [
            ("status response id", self.response_id.as_str()),
            ("status response operation id", self.operation_id.as_str()),
            ("status response provider id", self.provider_id.as_str()),
            ("status response profile id", self.profile_id.as_str()),
            (
                "status response token family id",
                self.token_family_id.as_str(),
            ),
            (
                "status response operation key",
                self.refresh_operation_key.as_str(),
            ),
            (
                "status response idempotency key",
                self.idempotency_key.as_str(),
            ),
            ("status evidence profile", self.evidence_profile.as_str()),
            ("status execution mode", self.execution_mode.as_str()),
            ("status audience", self.audience.as_str()),
            ("status issuer", self.issuer.as_str()),
        ] {
            validate_id(value, label)?;
        }
        validate_digest(&self.payload_digest, "status response payload digest")?;
        validate_digest(&self.fencing_token, "status response fencing token")?;
        validate_digest(&self.response_digest, "status response digest")?;
        validate_digest(&self.binding_digest, "status binding digest")?;
        validate_digest(
            &self.provider_query_receipt_digest,
            "provider query receipt digest",
        )?;
        validate_digest(&self.mode_attestation_digest, "mode attestation digest")?;
        validate_digest(&self.policy_digest, "status response policy digest")?;
        if let Some(signature) = &self.signature {
            validate_digest(signature, "status signature")?;
        }
        validate_nonzero(
            self.expected_secret_revision,
            "status response expected revision",
        )?;
        validate_nonzero(self.authority_epoch, "status response authority epoch")?;
        validate_nonzero(self.owner_epoch, "status response owner epoch")?;
        validate_nonzero(self.generation, "status response generation")?;
        validate_nonzero(self.status_revision, "status revision")?;
        validate_nonzero(self.secret_revision, "status secret revision")?;
        validate_nonzero(self.observed_at, "status observed-at")?;
        if self.operation_id != request.operation_id
            || self.provider_id != request.provider_id
            || self.profile_id != request.profile_id
            || self.token_family_id != request.token_family_id
            || self.refresh_operation_key != request.refresh_operation_key
            || self.idempotency_key != request.idempotency_key
            || self.payload_digest != request.payload_digest
            || self.expected_secret_revision != request.expected_secret_revision
            || self.authority_epoch != request.authority_epoch
            || self.owner_epoch != request.owner_epoch
            || self.generation != request.generation
            || self.fencing_token != request.fencing_token
            || self.policy_digest != request.policy_digest
            || self.audience != request.audience
        {
            return Err(error("status lookup response binding mismatch"));
        }
        if self.execution_mode != request.expected_execution_mode {
            return Err(error("status execution mode does not match request"));
        }
        let expected_binding = status_binding_digest(self)?;
        if self.binding_digest != expected_binding {
            return Err(error("status binding digest mismatch"));
        }
        validate_outcome_status(self.outcome, self.provider_status)?;
        if self.outcome == SecretRefOutcome::Succeeded {
            if self.secret_revision <= self.expected_secret_revision {
                return Err(error("successful status revision must advance"));
            }
            if self.new_access_secret_ref.is_none() || self.new_refresh_secret_ref.is_none() {
                return Err(error(
                    "successful status must include both secret references",
                ));
            }
        } else if self.new_access_secret_ref.is_some() || self.new_refresh_secret_ref.is_some() {
            return Err(error(
                "non-success status cannot include new secret references",
            ));
        }
        if let Some(reference) = &self.new_access_secret_ref {
            reference.validate()?;
        }
        if let Some(reference) = &self.new_refresh_secret_ref {
            reference.validate()?;
        }
        if self.outcome == SecretRefOutcome::Indeterminate
            && self.provider_status != SecretProviderStatus::Unknown
        {
            return Err(error(
                "indeterminate status must report unknown provider status",
            ));
        }
        if self.outcome == SecretRefOutcome::Quarantined
            && !matches!(
                self.provider_status,
                SecretProviderStatus::InvalidGrant | SecretProviderStatus::Quarantined
            )
        {
            return Err(error(
                "quarantined status requires invalid-grant classification",
            ));
        }
        let local_sentinel = self.audience == "hepta.auth.local-mode"
            && self.key_epoch == 0
            && self.issuer == "local-mode-registry"
            && self.signature.is_none()
            && self.key_id.is_none()
            && self.issued_at.is_none()
            && self.expires_at.is_none();
        let external_attestation = self.signature.is_some()
            && self.key_id.is_some()
            && self.issued_at.is_some()
            && self.expires_at.is_some()
            && self.key_epoch != 0;
        if !local_sentinel && !external_attestation {
            return Err(error(
                "status evidence must be complete local sentinel or signed tuple",
            ));
        }
        if let Some(key_id) = &self.key_id {
            validate_id(key_id, "status key id")?;
        }
        if let (Some(issued_at), Some(expires_at)) = (self.issued_at, self.expires_at)
            && (issued_at == 0 || expires_at <= issued_at)
        {
            return Err(error("status evidence validity window is invalid"));
        }
        Ok(())
    }

    pub fn canonical_bytes(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate_against(request)?;
        canonical_json(self)
    }

    pub fn digest(
        &self,
        request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("refresh-status-by-operation-key-response"),
            &self.canonical_bytes(request)?,
        ))
    }
}

/// A small local record used by qualification tests to prove the state
/// machine does not dispatch lookup-only or stale operations.  It is not a
/// durable writer and intentionally carries no secret bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretRefOperationRecord {
    pub operation_id: String,
    pub refresh_operation_key: String,
    pub provider_id: String,
    pub profile_id: String,
    pub token_family_id: String,
    pub expected_secret_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: Sha256Digest,
    pub state: SecretRefState,
    pub attempt: u32,
    pub retry_budget: u32,
}

impl SecretRefOperationRecord {
    pub fn from_refresh_request(
        request: &RefreshWithSecretRefRequest,
        retry_budget: u32,
    ) -> Result<Self, AuthBusContractError> {
        request.validate()?;
        Ok(Self {
            operation_id: request.operation_id.clone(),
            refresh_operation_key: request.refresh_operation_key.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
            state: SecretRefState::Idle,
            attempt: 0,
            retry_budget,
        })
    }

    pub fn transition(&mut self, event: SecretRefEvent) -> Result<(), AuthBusContractError> {
        if event.requires_current_fence() {
            return Err(error(format!(
                "SecretRef event {event:?} requires an explicit current callback fence"
            )));
        }
        self.transition_unfenced(event)
    }

    /// Apply a provider/evidence callback only when it carries the exact
    /// identity fence captured by this operation.  Validation occurs before
    /// any state or attempt mutation, so stale callbacks are side-effect free.
    pub fn transition_with_fence(
        &mut self,
        event: SecretRefEvent,
        callback_fence: &SecretRefCallbackFence,
    ) -> Result<(), AuthBusContractError> {
        if !event.requires_current_fence() {
            return Err(error(format!(
                "SecretRef event {event:?} does not accept a callback fence"
            )));
        }
        callback_fence.validate()?;
        if callback_fence.authority_epoch != self.authority_epoch
            || callback_fence.owner_epoch != self.owner_epoch
            || callback_fence.generation != self.generation
            || callback_fence.fencing_token != self.fencing_token
        {
            return Err(error("SecretRef callback carries a stale identity fence"));
        }
        self.transition_unfenced(event)
    }

    fn transition_unfenced(&mut self, event: SecretRefEvent) -> Result<(), AuthBusContractError> {
        let next = self.state.transition(event)?;
        let next_attempt = if matches!(event, SecretRefEvent::Dispatch) {
            let attempt = self
                .attempt
                .checked_add(1)
                .ok_or_else(|| error("SecretRef attempt overflow"))?;
            if attempt > self.retry_budget.saturating_add(1) {
                return Err(error("SecretRef retry budget exhausted"));
            }
            Some(attempt)
        } else {
            None
        };
        // Validate every component before mutating the record.  In
        // particular, a retry-budget error must not consume an attempt while
        // leaving the state in its previous (dispatchable) phase.
        if let Some(attempt) = next_attempt {
            self.attempt = attempt;
        }
        self.state = next;
        Ok(())
    }

    pub fn dispatch_allowed(&self) -> bool {
        self.state.dispatch_allowed()
    }

    pub fn reconcile_allowed(&self) -> bool {
        self.state.reconcile_allowed()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn secret_ref(label: &str) -> OpaqueSecretRef {
        OpaqueSecretRef::new("qualification-backend", "oauth", label, 1, digest(label))
            .expect("valid opaque ref")
    }

    fn refresh_request() -> RefreshWithSecretRefRequest {
        let provider = "provider-a";
        let profile = "profile-a";
        let family = "family-a";
        let idem = "idem-a";
        let payload = digest("payload");
        let policy = digest("policy");
        let scope = digest("scope");
        let purpose = digest("purpose");
        let fence = digest("fence");
        let key = derive_refresh_operation_key(
            provider, profile, family, idem, 2, &scope, &purpose, &payload, &policy, 3, 4, 5,
            &fence,
        );
        let operation_id = derive_refresh_operation_id(&key, idem, &payload);
        RefreshWithSecretRefRequest {
            schema_version: AUTHBUS_B3_CONTRACT_SCHEMA_VERSION,
            operation_id,
            refresh_operation_key: key,
            command_id: "command-a".to_string(),
            run_id: "run-a".to_string(),
            profile_id: profile.to_string(),
            provider_id: provider.to_string(),
            token_family_id: family.to_string(),
            secret_ref: secret_ref("refresh-key"),
            expected_secret_revision: 2,
            idempotency_key: idem.to_string(),
            payload_digest: payload,
            policy_digest: policy,
            scope_digest: scope,
            authority_epoch: 3,
            owner_epoch: 4,
            generation: 5,
            fencing_token: fence,
            logical_clock: 6,
            causal_parent_event_id: "parent-event".to_string(),
            deadline_at: 100,
            purpose_digest: purpose,
            audience: "hepta.auth.local-mode".to_string(),
        }
    }

    fn rotation_request() -> RotateSecretRefRequest {
        let request = refresh_request();
        RotateSecretRefRequest {
            schema_version: request.schema_version,
            operation_id: request.operation_id,
            refresh_operation_key: request.refresh_operation_key,
            command_id: request.command_id,
            run_id: request.run_id,
            profile_id: request.profile_id,
            provider_id: request.provider_id,
            token_family_id: request.token_family_id,
            secret_ref: request.secret_ref,
            expected_secret_revision: request.expected_secret_revision,
            idempotency_key: request.idempotency_key,
            payload_digest: request.payload_digest,
            policy_digest: request.policy_digest,
            scope_digest: request.scope_digest,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token,
            logical_clock: request.logical_clock,
            causal_parent_event_id: request.causal_parent_event_id,
            deadline_at: request.deadline_at,
            purpose_digest: request.purpose_digest,
            audience: request.audience,
        }
    }

    fn status_request() -> RefreshStatusByOperationKeyRequest {
        let request = refresh_request();
        RefreshStatusByOperationKeyRequest {
            schema_version: request.schema_version,
            operation_id: request.operation_id,
            provider_id: request.provider_id,
            profile_id: request.profile_id,
            token_family_id: request.token_family_id,
            refresh_operation_key: request.refresh_operation_key,
            idempotency_key: request.idempotency_key,
            payload_digest: request.payload_digest,
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token,
            deadline_at: request.deadline_at,
            audience: request.audience,
            expected_execution_mode: "qualification".to_string(),
            policy_digest: request.policy_digest,
        }
    }

    fn callback_fence() -> SecretRefCallbackFence {
        let request = refresh_request();
        SecretRefCallbackFence::new(
            request.authority_epoch,
            request.owner_epoch,
            request.generation,
            request.fencing_token,
        )
        .expect("callback fence")
    }

    fn local_status_response(
        request: &RefreshStatusByOperationKeyRequest,
    ) -> RefreshStatusByOperationKeyResponse {
        let mut response = RefreshStatusByOperationKeyResponse {
            schema_version: request.schema_version,
            response_id: "status-response".to_string(),
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
            outcome: SecretRefOutcome::Indeterminate,
            secret_revision: request.expected_secret_revision,
            response_digest: digest("status-response"),
            provider_status: SecretProviderStatus::Unknown,
            status_revision: 1,
            observed_at: 10,
            binding_digest: digest("pending-binding"),
            evidence_profile: "local-qualification".to_string(),
            provider_query_receipt_digest: digest("query"),
            execution_mode: request.expected_execution_mode.clone(),
            mode_attestation_digest: digest("mode"),
            policy_digest: request.policy_digest.clone(),
            audience: request.audience.clone(),
            key_epoch: 0,
            issuer: "local-mode-registry".to_string(),
            new_access_secret_ref: None,
            new_refresh_secret_ref: None,
            signature: None,
            key_id: None,
            issued_at: None,
            expires_at: None,
        };
        response.binding_digest = status_binding_digest(&response).expect("binding digest");
        response
    }

    #[test]
    fn operation_key_and_id_are_deterministically_bound() {
        let request = refresh_request();
        request.validate().expect("valid request");
        assert_eq!(
            request.operation_id,
            derive_refresh_operation_id(
                &request.refresh_operation_key,
                &request.idempotency_key,
                &request.payload_digest
            )
        );
        let mut changed = request.clone();
        changed.payload_digest = digest("changed");
        assert!(changed.validate().is_err());
        assert_ne!(
            request.digest().expect("digest"),
            changed.digest().unwrap_or_else(|_| digest("invalid"))
        );
    }

    #[test]
    fn mutation_binding_rejects_epoch_generation_fence_and_payload_tamper() {
        let request = refresh_request();
        request.validate().expect("valid request");

        let mut tampered = request.clone();
        tampered.authority_epoch += 1;
        assert!(tampered.validate().is_err());

        let mut tampered = request.clone();
        tampered.owner_epoch += 1;
        assert!(tampered.validate().is_err());

        let mut tampered = request.clone();
        tampered.generation += 1;
        assert!(tampered.validate().is_err());

        let mut tampered = request.clone();
        tampered.fencing_token = digest("different-fence");
        assert!(tampered.validate().is_err());

        let mut tampered = request;
        tampered.payload_digest = digest("different-payload");
        assert!(tampered.validate().is_err());

        let mut status = local_status_response(&status_request());
        let status_request = status_request();
        status
            .validate_against(&status_request)
            .expect("valid status");
        status.owner_epoch += 1;
        assert!(status.validate_against(&status_request).is_err());
    }

    #[test]
    fn raw_secret_fields_and_unknown_fields_are_rejected() {
        let value = serde_json::to_value(refresh_request()).expect("json");
        let mut object = value.as_object().expect("object").clone();
        object.insert("access_token".to_string(), serde_json::json!("raw"));
        assert!(
            serde_json::from_value::<RefreshWithSecretRefRequest>(serde_json::Value::Object(
                object
            ))
            .is_err()
        );
        let mut secret = serde_json::to_value(secret_ref("x")).expect("json");
        secret
            .as_object_mut()
            .expect("object")
            .insert("secret_bytes".to_string(), serde_json::json!("raw"));
        assert!(serde_json::from_value::<OpaqueSecretRef>(secret).is_err());
    }

    #[test]
    fn refresh_success_requires_opaque_refs_and_advancing_revision() {
        let request = refresh_request();
        let response = RefreshWithSecretRefResponse {
            schema_version: request.schema_version,
            response_id: "response-a".to_string(),
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome: SecretRefOutcome::Succeeded,
            access_secret_ref: Some(secret_ref("access")),
            refresh_secret_ref: Some(secret_ref("refresh-new")),
            secret_revision: Some(3),
            refresh_operation_key: request.refresh_operation_key.clone(),
            provider_status: SecretProviderStatus::Rotated,
            response_digest: digest("response"),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        response.validate_against(&request).expect("valid success");
        let mut invalid = response.clone();
        invalid.access_secret_ref = None;
        assert!(invalid.validate_against(&request).is_err());
        invalid = response;
        invalid.provider_status = SecretProviderStatus::Unknown;
        assert!(invalid.validate_against(&request).is_err());
    }

    #[test]
    fn indeterminate_and_quarantine_forbid_new_refs() {
        let request = refresh_request();
        let base = RefreshWithSecretRefResponse {
            schema_version: request.schema_version,
            response_id: "response-b".to_string(),
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome: SecretRefOutcome::Indeterminate,
            access_secret_ref: None,
            refresh_secret_ref: None,
            secret_revision: None,
            refresh_operation_key: request.refresh_operation_key.clone(),
            provider_status: SecretProviderStatus::Unknown,
            response_digest: digest("unknown"),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        base.validate_against(&request)
            .expect("valid indeterminate");
        let mut invalid = base.clone();
        invalid.refresh_secret_ref = Some(secret_ref("must-not-leak"));
        assert!(invalid.validate_against(&request).is_err());
        invalid = base;
        invalid.outcome = SecretRefOutcome::Quarantined;
        invalid.provider_status = SecretProviderStatus::InvalidGrant;
        invalid
            .validate_against(&request)
            .expect("valid quarantine");
    }

    #[test]
    fn status_lookup_is_binding_checked_and_lookup_only() {
        let request = status_request();
        request.validate().expect("valid status request");
        assert!(!request.dispatch_allowed());
        let response = local_status_response(&request);
        response.validate_against(&request).expect("valid status");
        let mut stale = response.clone();
        stale.generation += 1;
        assert!(stale.validate_against(&request).is_err());
        let mut missing_revision = response;
        missing_revision.secret_revision = 0;
        assert!(missing_revision.validate_against(&request).is_err());
    }

    #[test]
    fn state_machine_is_fail_closed_after_response_loss() {
        let mut record =
            SecretRefOperationRecord::from_refresh_request(&refresh_request(), 1).expect("record");
        assert!(!record.dispatch_allowed());
        record.transition(SecretRefEvent::Claim).expect("claim");
        record
            .transition(SecretRefEvent::Dispatch)
            .expect("dispatch");
        record
            .transition_with_fence(SecretRefEvent::ResponseUnknown, &callback_fence())
            .expect("unknown");
        assert!(record.reconcile_allowed());
        assert!(!record.dispatch_allowed());
        assert!(record.transition(SecretRefEvent::Dispatch).is_err());
        record.transition(SecretRefEvent::Lookup).expect("lookup");
        record
            .transition_with_fence(SecretRefEvent::LookupRotated, &callback_fence())
            .expect("rotated");
        assert!(record.state.is_terminal());
        assert!(record.transition(SecretRefEvent::ClaimAgain).is_err());
    }

    #[test]
    fn retry_budget_error_does_not_partially_mutate_record() {
        let mut record =
            SecretRefOperationRecord::from_refresh_request(&refresh_request(), 0).expect("record");
        record.transition(SecretRefEvent::Claim).expect("claim");
        record
            .transition(SecretRefEvent::Dispatch)
            .expect("first dispatch");
        record
            .transition_with_fence(SecretRefEvent::TransientFailure, &callback_fence())
            .expect("transient failure");
        record
            .transition(SecretRefEvent::RetryScheduled)
            .expect("retry schedule");
        record
            .transition(SecretRefEvent::ClaimAgain)
            .expect("claim again");
        let before = record.clone();
        assert!(record.transition(SecretRefEvent::Dispatch).is_err());
        assert_eq!(record, before);

        let mut overflow = before;
        overflow.attempt = u32::MAX;
        assert!(overflow.transition(SecretRefEvent::Dispatch).is_err());
        assert_eq!(overflow.attempt, u32::MAX);
    }

    #[test]
    fn rotation_wire_shape_is_strict_and_terminal_rules_hold() {
        let request = rotation_request();
        request.validate().expect("valid rotation");
        let response = RotateSecretRefResponse {
            schema_version: request.schema_version,
            response_id: "rotate-response".to_string(),
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            profile_id: request.profile_id.clone(),
            token_family_id: request.token_family_id.clone(),
            outcome: SecretRefOutcome::Succeeded,
            new_refresh_secret_ref: Some(secret_ref("rotated")),
            secret_revision: Some(3),
            refresh_operation_key: request.refresh_operation_key.clone(),
            response_digest: digest("rotate-response"),
            idempotency_key: request.idempotency_key.clone(),
            payload_digest: request.payload_digest.clone(),
            expected_secret_revision: request.expected_secret_revision,
            authority_epoch: request.authority_epoch,
            owner_epoch: request.owner_epoch,
            generation: request.generation,
            fencing_token: request.fencing_token.clone(),
        };
        response.validate_against(&request).expect("valid rotation");
        let mut unknown = serde_json::to_value(response).expect("json");
        unknown
            .as_object_mut()
            .expect("object")
            .insert("access_token".to_string(), serde_json::json!("raw"));
        assert!(serde_json::from_value::<RotateSecretRefResponse>(unknown).is_err());
    }

    #[test]
    fn callback_events_require_current_fence_and_reject_stale_without_mutation() {
        let mut record =
            SecretRefOperationRecord::from_refresh_request(&refresh_request(), 1).expect("record");
        record.transition(SecretRefEvent::Claim).expect("claim");
        record
            .transition(SecretRefEvent::Dispatch)
            .expect("dispatch");

        let before = record.clone();
        assert!(record.transition(SecretRefEvent::ResponseUnknown).is_err());
        assert_eq!(record, before);

        let mut stale_authority = callback_fence();
        stale_authority.authority_epoch += 1;
        let mut stale_owner = callback_fence();
        stale_owner.owner_epoch += 1;
        let mut stale_generation = callback_fence();
        stale_generation.generation += 1;
        let mut stale_token = callback_fence();
        stale_token.fencing_token = digest("stale-token");
        for stale in [
            &stale_authority,
            &stale_owner,
            &stale_generation,
            &stale_token,
        ] {
            assert!(
                record
                    .transition_with_fence(SecretRefEvent::ResponseUnknown, stale)
                    .is_err()
            );
            assert_eq!(record, before);
        }

        let current = callback_fence();
        record
            .transition_with_fence(SecretRefEvent::ResponseUnknown, &current)
            .expect("current response-loss callback");
        record.transition(SecretRefEvent::Lookup).expect("lookup");

        let before = record.clone();
        assert!(
            record
                .transition_with_fence(SecretRefEvent::LookupRotated, &stale_generation)
                .is_err()
        );
        assert_eq!(record, before);
        record
            .transition_with_fence(SecretRefEvent::LookupRotated, &current)
            .expect("current lookup callback");
        assert_eq!(record.state, SecretRefState::Succeeded);
    }
}
