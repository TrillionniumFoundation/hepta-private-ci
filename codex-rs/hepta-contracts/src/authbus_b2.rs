//! B2 contract-only surfaces for the Hepta AuthBus plan.
//!
//! These types are wire contracts and immutable evidence, not an authbusd,
//! provider adapter, listener, or authority implementation.  Every contract
//! is secret-free, versioned, strict on deserialization, and explicitly
//! non-authoritative.  Epochs, generations, and fencing digests are carried on
//! each boundary so a later implementation cannot silently accept stale state.

use serde::Deserialize;
use serde::Serialize;

use crate::Sha256Digest;

use super::AUTHBUS_CONTRACT_SCHEMA_VERSION;
use super::AuthBusContractError;
use super::Principal;
use super::SubjectRef;
use super::canonical_json;
use super::contract_domain;
use super::domain_digest;
use super::validate_digest;
use super::validate_text;
use super::validate_window;

/// B2 contracts use the same wire version and domain namespace as B0/B3.
pub const AUTHBUS_B2_CONTRACT_SCHEMA_VERSION: u32 = AUTHBUS_CONTRACT_SCHEMA_VERSION;
/// A B2 contract can only be an observation or a proposed command payload.
pub const AUTHBUS_B2_AUTHORITY_DEFAULT: bool = false;

const MAX_LIST_ITEMS: usize = 64;
const MAX_CLOCK_UNCERTAINTY_MILLIS: u64 = 86_400_000;

fn error(message: impl Into<String>) -> AuthBusContractError {
    AuthBusContractError::new(message)
}

fn validate_schema(schema_version: u32, kind: &str) -> Result<(), AuthBusContractError> {
    if schema_version != AUTHBUS_B2_CONTRACT_SCHEMA_VERSION {
        return Err(error(format!("unsupported {kind} schema version")));
    }
    Ok(())
}

fn validate_id(value: &str, label: &str) -> Result<(), AuthBusContractError> {
    validate_text(value, label, /*max_bytes*/ 512)
}

fn validate_authority(authority: bool) -> Result<(), AuthBusContractError> {
    if authority != AUTHBUS_B2_AUTHORITY_DEFAULT {
        return Err(error("B2 contracts cannot carry authority"));
    }
    Ok(())
}

fn validate_epochs(
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token_sha256: &Sha256Digest,
) -> Result<(), AuthBusContractError> {
    if authority_epoch == 0 || owner_epoch == 0 || generation == 0 {
        return Err(error(
            "authority epoch, owner epoch and generation must be non-zero",
        ));
    }
    validate_digest(fencing_token_sha256, "fencing token")
}

fn validate_subject_generation(
    subject: &SubjectRef,
    generation: u64,
) -> Result<(), AuthBusContractError> {
    subject.validate()?;
    if subject.generation != generation {
        return Err(error(
            "subject generation does not match contract generation",
        ));
    }
    Ok(())
}

fn validate_revision_pair(
    expected_revision: u64,
    revision: u64,
) -> Result<(), AuthBusContractError> {
    if expected_revision == 0 || revision == 0 {
        return Err(error("expected revision and revision must be non-zero"));
    }
    Ok(())
}

fn validate_digest_list(values: &[Sha256Digest], label: &str) -> Result<(), AuthBusContractError> {
    if values.is_empty() || values.len() > MAX_LIST_ITEMS {
        return Err(error(format!(
            "{label} must contain 1..={MAX_LIST_ITEMS} digests"
        )));
    }
    for value in values {
        validate_digest(value, label)?;
    }
    Ok(())
}

macro_rules! impl_contract_methods {
    ($type:ty, $domain:literal) => {
        impl $type {
            /// Validate and encode this contract using deterministic JSON field order.
            pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
                self.validate()?;
                canonical_json(self)
            }

            /// Domain-separated digest of the validated canonical wire bytes.
            pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
                Ok(domain_digest(
                    &contract_domain($domain),
                    &self.canonical_bytes()?,
                ))
            }
        }
    };
}

/// Policy result.  `Deny` is the fail-closed default for a missing policy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AdmissionDecisionKind {
    Allow,
    Deny,
    Indeterminate,
}

/// Versioned admission outcome bound to one request, subject and policy head.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionDecision {
    pub schema_version: u32,
    pub decision_id: String,
    pub request_sha256: Sha256Digest,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub policy_sha256: Sha256Digest,
    pub decision: AdmissionDecisionKind,
    pub reason_code: String,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub expected_revision: u64,
    pub observed_revision: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl AdmissionDecision {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "AdmissionDecision")?;
        validate_id(&self.decision_id, "decision id")?;
        validate_digest(&self.request_sha256, "decision request")?;
        validate_subject_generation(&self.subject, self.generation)?;
        validate_digest(&self.resource_sha256, "decision resource")?;
        validate_digest(&self.policy_sha256, "decision policy")?;
        validate_text(&self.reason_code, "decision reason code", /*max_bytes*/ 128)?;
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_revision_pair(self.expected_revision, self.observed_revision)?;
        validate_window(self.issued_at_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(AdmissionDecision, "admission-decision");

/// Canonical v1.3 lifecycle of a local quota reservation.
///
/// `DispatchAccepted` is only a provider queue acknowledgement and
/// `PartiallyConsumed` is a metering state; neither is an effect terminal.
/// `Released`, `Refunded`, and `Expired` are reservation outcomes and must not
/// be projected as effect success.  The upper-case spellings and the old
/// snake-case spellings below are decode-only compatibility aliases.  New
/// bytes always emit the canonical registry spelling.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum QuotaReservationState {
    #[serde(rename = "Proposed", alias = "PROPOSED", alias = "proposed")]
    Proposed,
    #[serde(rename = "Held", alias = "HELD", alias = "held")]
    Held,
    #[serde(
        rename = "DispatchAttempted",
        alias = "DISPATCH_ATTEMPTED",
        alias = "dispatch_attempted"
    )]
    DispatchAttempted,
    #[serde(
        rename = "DispatchAccepted",
        alias = "DISPATCH_ACCEPTED",
        alias = "DISPATCHED",
        alias = "dispatch_accepted",
        alias = "dispatched"
    )]
    DispatchAccepted,
    #[serde(
        rename = "PartiallyConsumed",
        alias = "PARTIAL",
        alias = "partial",
        alias = "partially_consumed"
    )]
    PartiallyConsumed,
    #[serde(
        rename = "Indeterminate",
        alias = "INDETERMINATE",
        alias = "indeterminate"
    )]
    Indeterminate,
    #[serde(rename = "Released", alias = "RELEASED", alias = "released")]
    Released,
    #[serde(rename = "Refunded", alias = "REFUNDED", alias = "refunded")]
    Refunded,
    #[serde(rename = "Expired", alias = "EXPIRED", alias = "expired")]
    Expired,
}

impl QuotaReservationState {
    /// The closed canonical state set published by the v1.3 registry.
    pub const fn all() -> [Self; 9] {
        [
            Self::Proposed,
            Self::Held,
            Self::DispatchAttempted,
            Self::DispatchAccepted,
            Self::PartiallyConsumed,
            Self::Indeterminate,
            Self::Released,
            Self::Refunded,
            Self::Expired,
        ]
    }

    /// Canonical registry spelling for this state.
    pub const fn canonical_name(self) -> &'static str {
        match self {
            Self::Proposed => "Proposed",
            Self::Held => "Held",
            Self::DispatchAttempted => "DispatchAttempted",
            Self::DispatchAccepted => "DispatchAccepted",
            Self::PartiallyConsumed => "PartiallyConsumed",
            Self::Indeterminate => "Indeterminate",
            Self::Released => "Released",
            Self::Refunded => "Refunded",
            Self::Expired => "Expired",
        }
    }

    /// Reservation outcomes are terminal and immutable.
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Released | Self::Refunded | Self::Expired)
    }

    /// Every non-terminal state remains held until a verified outcome or
    /// reconciliation closes the reservation.
    pub const fn is_non_terminal(self) -> bool {
        !self.is_terminal()
    }

    /// State edges for the qualification-only local reservation model.
    ///
    /// The model deliberately requires an explicit dispatch-attempt marker
    /// before acceptance and routes post-dispatch uncertainty through
    /// `Indeterminate`; this prevents a caller from releasing a potentially
    /// effected reservation without reconciliation evidence.
    pub const fn can_transition_to(self, next: Self) -> bool {
        matches!(
            (self, next),
            (Self::Proposed, Self::Proposed)
                | (Self::Held, Self::Held)
                | (Self::DispatchAttempted, Self::DispatchAttempted)
                | (Self::DispatchAccepted, Self::DispatchAccepted)
                | (Self::PartiallyConsumed, Self::PartiallyConsumed)
                | (Self::Indeterminate, Self::Indeterminate)
                | (Self::Released, Self::Released)
                | (Self::Refunded, Self::Refunded)
                | (Self::Expired, Self::Expired)
                | (Self::Proposed, Self::Held | Self::Released | Self::Expired)
                | (
                    Self::Held,
                    Self::DispatchAttempted | Self::Released | Self::Expired
                )
                | (
                    Self::DispatchAttempted,
                    Self::DispatchAccepted | Self::Indeterminate
                )
                | (
                    Self::DispatchAccepted,
                    Self::PartiallyConsumed | Self::Indeterminate
                )
                | (Self::PartiallyConsumed, Self::Indeterminate)
                | (
                    Self::Indeterminate,
                    Self::Released | Self::Refunded | Self::Expired
                )
        )
    }
}

/// Quota hold created after admission and before a physical effect.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaReservation {
    pub schema_version: u32,
    pub reservation_id: String,
    pub operation_sha256: Sha256Digest,
    pub decision_sha256: Sha256Digest,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub reserved_requests: u64,
    pub reserved_tokens: u64,
    pub reserved_concurrency: u32,
    pub reserved_day_budget: u64,
    pub state: QuotaReservationState,
    pub expected_revision: u64,
    pub revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl QuotaReservation {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "QuotaReservation")?;
        validate_id(&self.reservation_id, "reservation id")?;
        validate_digest(&self.operation_sha256, "reservation operation")?;
        validate_digest(&self.decision_sha256, "reservation decision")?;
        validate_subject_generation(&self.subject, self.generation)?;
        validate_digest(&self.resource_sha256, "reservation resource")?;
        if self.reserved_requests == 0
            && self.reserved_tokens == 0
            && self.reserved_concurrency == 0
            && self.reserved_day_budget == 0
        {
            return Err(error("quota reservation must hold a non-zero amount"));
        }
        validate_revision_pair(self.expected_revision, self.revision)?;
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }

    /// Apply an owner-CAS state transition without reopening a terminal hold.
    pub fn transition(
        &self,
        expected_revision: u64,
        authority_epoch: u64,
        next_state: QuotaReservationState,
    ) -> Result<Self, AuthBusContractError> {
        self.validate()?;
        if self.revision != expected_revision {
            return Err(error("quota reservation revision CAS mismatch"));
        }
        if self.authority_epoch != authority_epoch {
            return Err(error("quota reservation authority epoch mismatch"));
        }
        if self.state == next_state {
            return Ok(self.clone());
        }
        if !self.state.can_transition_to(next_state) {
            return Err(error("invalid quota reservation state transition"));
        }
        let revision = self
            .revision
            .checked_add(1)
            .ok_or_else(|| error("quota reservation revision overflow"))?;
        let mut next = self.clone();
        next.revision = revision;
        next.expected_revision = expected_revision;
        next.state = next_state;
        next.validate()?;
        Ok(next)
    }
}

impl_contract_methods!(QuotaReservation, "quota-reservation");

/// Conservative provider observation.  This is status evidence only; it never
/// grants a provider call or changes an external quota.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderStatusKind {
    Healthy,
    Degraded,
    RateLimited,
    Unavailable,
    Quarantined,
    Unknown,
}

/// Versioned provider-health observation with an owner-CAS revision.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderStatus {
    pub schema_version: u32,
    pub status_id: String,
    pub provider_id: String,
    pub resource_sha256: Option<Sha256Digest>,
    pub status: ProviderStatusKind,
    pub reason_code: Option<String>,
    pub observed_at_unix_seconds: u64,
    pub retry_after_seconds: Option<u32>,
    pub expected_revision: u64,
    pub revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    #[serde(default)]
    pub authority: bool,
}

impl ProviderStatus {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "ProviderStatus")?;
        validate_id(&self.status_id, "provider status id")?;
        validate_text(&self.provider_id, "provider id", /*max_bytes*/ 512)?;
        if let Some(resource) = &self.resource_sha256 {
            validate_digest(resource, "provider status resource")?;
        }
        if let Some(reason) = &self.reason_code {
            validate_text(reason, "provider status reason code", /*max_bytes*/ 128)?;
        }
        if self.observed_at_unix_seconds == 0 {
            return Err(error(
                "provider status observation timestamp must be non-zero",
            ));
        }
        if let Some(retry_after) = self.retry_after_seconds
            && retry_after == 0
        {
            return Err(error("provider status retry-after must be non-zero"));
        }
        validate_revision_pair(self.expected_revision, self.revision)?;
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_authority(self.authority)
    }

    /// Record a newer observation under an owner-CAS revision.
    pub fn transition(
        &self,
        expected_revision: u64,
        authority_epoch: u64,
        next_status: ProviderStatusKind,
    ) -> Result<Self, AuthBusContractError> {
        self.validate()?;
        if self.revision != expected_revision {
            return Err(error("provider status revision CAS mismatch"));
        }
        if self.authority_epoch != authority_epoch {
            return Err(error("provider status authority epoch mismatch"));
        }
        if self.status == next_status {
            return Ok(self.clone());
        }
        let revision = self
            .revision
            .checked_add(1)
            .ok_or_else(|| error("provider status revision overflow"))?;
        let mut next = self.clone();
        next.expected_revision = expected_revision;
        next.revision = revision;
        next.status = next_status;
        next.validate()?;
        Ok(next)
    }
}

impl_contract_methods!(ProviderStatus, "provider-status");

/// Compatibility alias for callers that name the health enum as a state.
pub type ProviderStatusState = ProviderStatusKind;

/// Stable reference to one operation across admission, reservation and effect seams.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperationRef {
    pub schema_version: u32,
    pub operation_id: String,
    pub operation_kind: String,
    pub request_sha256: Sha256Digest,
    pub decision_sha256: Option<Sha256Digest>,
    pub reservation_sha256: Option<Sha256Digest>,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub created_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl OperationRef {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "OperationRef")?;
        validate_id(&self.operation_id, "operation id")?;
        validate_text(&self.operation_kind, "operation kind", /*max_bytes*/ 128)?;
        validate_digest(&self.request_sha256, "operation request")?;
        if let Some(decision) = &self.decision_sha256 {
            validate_digest(decision, "operation decision")?;
        }
        if let Some(reservation) = &self.reservation_sha256 {
            validate_digest(reservation, "operation reservation")?;
        }
        validate_subject_generation(&self.subject, self.generation)?;
        validate_digest(&self.resource_sha256, "operation resource")?;
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_window(self.created_at_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(OperationRef, "operation-ref");

/// A narrower delegated capability.  Transfer is always disabled in B2.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityAttenuation {
    pub schema_version: u32,
    pub attenuation_id: String,
    pub parent_capability_sha256: Sha256Digest,
    pub subject: SubjectRef,
    pub operation: String,
    pub resource_sha256: Sha256Digest,
    pub scope_sha256: Sha256Digest,
    pub policy_sha256: Sha256Digest,
    pub audience: String,
    pub max_usage: u64,
    pub transferable: bool,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl CapabilityAttenuation {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "CapabilityAttenuation")?;
        validate_id(&self.attenuation_id, "attenuation id")?;
        validate_digest(&self.parent_capability_sha256, "parent capability")?;
        validate_subject_generation(&self.subject, self.generation)?;
        validate_text(&self.operation, "attenuated operation", /*max_bytes*/ 128)?;
        validate_digest(&self.resource_sha256, "attenuated resource")?;
        validate_digest(&self.scope_sha256, "attenuated scope")?;
        validate_digest(&self.policy_sha256, "attenuated policy")?;
        validate_text(&self.audience, "attenuated audience", /*max_bytes*/ 512)?;
        if self.max_usage == 0 {
            return Err(error("attenuated max usage must be non-zero"));
        }
        if self.transferable {
            return Err(error("B2 attenuations must be non-transferable"));
        }
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(CapabilityAttenuation, "capability-attenuation");

/// Evidence level used when a peer session crosses a process boundary.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PeerTrustMode {
    SameProcess,
    ServiceUid,
    AuditToken,
    TrustDomain,
}

/// Host-local peer session envelope.  Peer identity is represented only by a digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PeerSession {
    pub schema_version: u32,
    pub session_id: String,
    pub peer: Principal,
    pub subject: SubjectRef,
    pub peer_identity_sha256: Sha256Digest,
    pub session_nonce_sha256: Sha256Digest,
    pub capability_sha256: Sha256Digest,
    pub trust_mode: PeerTrustMode,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl PeerSession {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "PeerSession")?;
        validate_id(&self.session_id, "peer session id")?;
        validate_text(self.peer.as_str(), "peer principal", /*max_bytes*/ 512)?;
        validate_subject_generation(&self.subject, self.generation)?;
        validate_digest(&self.peer_identity_sha256, "peer identity")?;
        validate_digest(&self.session_nonce_sha256, "session nonce")?;
        validate_digest(&self.capability_sha256, "session capability")?;
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(PeerSession, "peer-session");

/// Clock evidence source.  `Unknown` is accepted only as bounded, conservative evidence.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ClockSource {
    MonotonicWall,
    HostAttested,
    Unknown,
}

/// Bounded wall/monotonic clock observation used for TTL and reconciliation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClockSnapshot {
    pub schema_version: u32,
    pub snapshot_id: String,
    pub source: ClockSource,
    pub wall_time_unix_seconds: u64,
    pub monotonic_ticks: u64,
    pub uncertainty_millis: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    #[serde(default)]
    pub authority: bool,
}

impl ClockSnapshot {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "ClockSnapshot")?;
        validate_id(&self.snapshot_id, "clock snapshot id")?;
        if self.wall_time_unix_seconds == 0 || self.monotonic_ticks == 0 {
            return Err(error("clock snapshot times must be non-zero"));
        }
        if self.uncertainty_millis > MAX_CLOCK_UNCERTAINTY_MILLIS {
            return Err(error("clock snapshot uncertainty is unbounded"));
        }
        if self.source == ClockSource::Unknown && self.uncertainty_millis == 0 {
            return Err(error(
                "unknown clock source must carry non-zero uncertainty",
            ));
        }
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(ClockSnapshot, "clock-snapshot");

/// Lifecycle state advertised to a scheduler or a peer.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceAdvertisementState {
    Available,
    Draining,
    Unavailable,
}

/// Secret-free description of one resource and its quota/capability digests.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceAdvertisement {
    pub schema_version: u32,
    pub advertisement_id: String,
    pub resource_id: String,
    pub owner: Principal,
    pub subject: Option<SubjectRef>,
    pub provider_id: String,
    pub model: Option<String>,
    pub resource_sha256: Sha256Digest,
    pub quota_sha256: Sha256Digest,
    pub capability_sha256: Vec<Sha256Digest>,
    pub state: ResourceAdvertisementState,
    pub revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    #[serde(default)]
    pub authority: bool,
}

impl ResourceAdvertisement {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_schema(self.schema_version, "ResourceAdvertisement")?;
        validate_id(&self.advertisement_id, "advertisement id")?;
        validate_id(&self.resource_id, "advertised resource id")?;
        validate_text(self.owner.as_str(), "advertisement owner", /*max_bytes*/ 512)?;
        if let Some(subject) = &self.subject {
            validate_subject_generation(subject, self.generation)?;
        }
        validate_text(&self.provider_id, "advertised provider", /*max_bytes*/ 512)?;
        if let Some(model) = &self.model {
            validate_text(model, "advertised model", /*max_bytes*/ 512)?;
        }
        validate_digest(&self.resource_sha256, "advertised resource")?;
        validate_digest(&self.quota_sha256, "advertised quota")?;
        validate_digest_list(&self.capability_sha256, "advertised capabilities")?;
        if self.revision == 0 {
            return Err(error("advertisement revision must be non-zero"));
        }
        validate_epochs(
            self.authority_epoch,
            self.owner_epoch,
            self.generation,
            &self.fencing_token_sha256,
        )?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        validate_authority(self.authority)
    }
}

impl_contract_methods!(ResourceAdvertisement, "resource-advertisement");

#[cfg(test)]
#[path = "authbus_b2_tests.rs"]
mod tests;
