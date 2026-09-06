//! Versioned, secret-free contracts for the Hepta AuthBus capability plane.
//!
//! This module is deliberately limited to the B0--B3 qualification slice.  It
//! does not open a listener, call a provider, mint a credential, or grant
//! production authority.  The wire namespace is independent from Basil's
//! `basil.broker.v1` namespace; an adapter may translate between the two only
//! after applying the Basil default-deny policy.

use std::error::Error;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::Sha256Digest;

#[path = "authbus_b2.rs"]
pub mod b2;

#[path = "authbus_b1.rs"]
pub mod b1;

#[path = "authbus_b3.rs"]
pub mod b3;

/// Stable schema number for the first Hepta-owned AuthBus contract family.
pub const AUTHBUS_CONTRACT_SCHEMA_VERSION: u32 = 1;
/// Versioned namespace reserved for Hepta-owned AuthBus messages.
pub const AUTHBUS_CONTRACT_NAMESPACE: &str = "hepta.auth.v1";
/// Schema identifier for the B0 source/provenance manifest.
pub const AUTHBUS_SOURCE_MANIFEST_SCHEMA: &str = "hepta.authbus.source-manifest.v1";
/// Plan identifier recorded by the E.41 AuthBus append.
pub const AUTHBUS_PLAN_ID: &str = "AUTHBUS-PLAN-2026-08-26";
/// Exact Basil source repository recorded by E.41.
pub const BASIL_UPSTREAM_REPOSITORY: &str = "https://github.com/openbasil/basil";
/// Exact Basil commit pinned by E.41.  This is a research pin, not a runtime
/// checkout or production release authority.
pub const BASIL_UPSTREAM_COMMIT: &str = "1fd29adb8e7356968eacbff9309e056cec9bafd7";
/// Workspace version associated with the pinned Basil snapshot.
pub const BASIL_WORKSPACE_VERSION: &str = "0.7.2-main-snapshot";
/// Latest published Basil release at the time of the append.
pub const BASIL_LATEST_RELEASE: &str = "v0.7.1";
/// Basil's declared license.
pub const BASIL_LICENSE: &str = "Apache-2.0";

const MAX_TEXT_BYTES: usize = 512;
const MAX_REASON_BYTES: usize = 128;

/// Errors returned when a contract is malformed or cannot be canonically
/// encoded.  Validation is intentionally explicit so a caller cannot mistake
/// a deserialized observation for an authority grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusContractError(String);

impl AuthBusContractError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for AuthBusContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Error for AuthBusContractError {}

impl From<serde_json::Error> for AuthBusContractError {
    fn from(error: serde_json::Error) -> Self {
        Self::new(format!("canonical AuthBus encoding failed: {error}"))
    }
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), AuthBusContractError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(AuthBusContractError::new(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), AuthBusContractError> {
    Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
        AuthBusContractError::new(format!("{label} must be a lowercase SHA-256 digest"))
    })?;
    Ok(())
}

fn validate_lowercase_hex(
    value: &str,
    label: &str,
    expected_len: usize,
) -> Result<(), AuthBusContractError> {
    if value.len() != expected_len
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AuthBusContractError::new(format!(
            "{label} must contain exactly {expected_len} lowercase hexadecimal characters"
        )));
    }
    Ok(())
}

fn validate_window(
    not_before_unix_seconds: u64,
    expires_at_unix_seconds: u64,
) -> Result<(), AuthBusContractError> {
    if not_before_unix_seconds == 0 {
        return Err(AuthBusContractError::new(
            "not-before timestamp must be non-zero",
        ));
    }
    if expires_at_unix_seconds <= not_before_unix_seconds {
        return Err(AuthBusContractError::new(
            "expiry must be strictly after not-before",
        ));
    }
    Ok(())
}

fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, AuthBusContractError> {
    Ok(serde_json::to_vec(value)?)
}

/// Compute a digest over a length-delimited domain and canonical JSON bytes.
/// Length-prefixing prevents concatenation ambiguities and the domain keeps
/// an AuthBus digest from being replayed as a digest in another Hepta family.
fn domain_digest(domain: &str, bytes: &[u8]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hasher.update((domain.len() as u64).to_be_bytes());
    hasher.update(domain.as_bytes());
    hasher.update((bytes.len() as u64).to_be_bytes());
    hasher.update(bytes);
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn contract_domain(kind: &str) -> String {
    format!("{AUTHBUS_CONTRACT_NAMESPACE}/{kind}")
}

/// A stable principal name.  The value is an identity label, never a token or
/// private key.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Principal(String);

impl Principal {
    pub fn new(value: impl Into<String>) -> Result<Self, AuthBusContractError> {
        let value = value.into();
        validate_text(&value, "principal", MAX_TEXT_BYTES)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for Principal {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

/// The opaque reference passed to a secret backend.  No raw secret material is
/// representable in this type.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretRef {
    pub backend: String,
    pub reference: String,
}

impl SecretRef {
    pub fn new(
        backend: impl Into<String>,
        reference: impl Into<String>,
    ) -> Result<Self, AuthBusContractError> {
        let secret_ref = Self {
            backend: backend.into(),
            reference: reference.into(),
        };
        secret_ref.validate()?;
        Ok(secret_ref)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        validate_text(&self.backend, "secret backend", /*max_bytes*/ 128)?;
        validate_text(&self.reference, "secret reference", MAX_TEXT_BYTES)?;
        Ok(())
    }
}

/// Tenant/workspace/agent binding used by every lease and permit.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SubjectRef {
    pub tenant: String,
    pub workspace: String,
    pub agent: String,
    pub service: String,
    pub generation: u64,
}

impl SubjectRef {
    pub fn new(
        tenant: impl Into<String>,
        workspace: impl Into<String>,
        agent: impl Into<String>,
        service: impl Into<String>,
        generation: u64,
    ) -> Result<Self, AuthBusContractError> {
        let subject = Self {
            tenant: tenant.into(),
            workspace: workspace.into(),
            agent: agent.into(),
            service: service.into(),
            generation,
        };
        subject.validate()?;
        Ok(subject)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        for (label, value) in [
            ("subject tenant", self.tenant.as_str()),
            ("subject workspace", self.workspace.as_str()),
            ("subject agent", self.agent.as_str()),
            ("subject service", self.service.as_str()),
        ] {
            validate_text(value, label, MAX_TEXT_BYTES)?;
        }
        if self.generation == 0 {
            return Err(AuthBusContractError::new(
                "subject generation must be non-zero",
            ));
        }
        Ok(())
    }
}

/// A single owner-controlled auth or compute resource.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthResource {
    pub schema_version: u32,
    pub resource_id: String,
    pub owner: Principal,
    pub provider_id: String,
    pub model: Option<String>,
    pub scope_sha256: Sha256Digest,
    pub secret_ref: SecretRef,
    pub owner_epoch: u64,
}

impl AuthResource {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported AuthResource schema version",
            ));
        }
        validate_text(&self.resource_id, "resource id", MAX_TEXT_BYTES)?;
        validate_text(&self.provider_id, "provider id", MAX_TEXT_BYTES)?;
        if let Some(model) = &self.model {
            validate_text(model, "resource model", MAX_TEXT_BYTES)?;
        }
        self.secret_ref.validate()?;
        validate_digest(&self.scope_sha256, "resource scope")?;
        if self.owner_epoch == 0 {
            return Err(AuthBusContractError::new(
                "resource owner epoch must be non-zero",
            ));
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("resource"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Static quota limits attached to a resource.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaContract {
    pub schema_version: u32,
    pub requests_per_window: u64,
    pub tokens_per_window: u64,
    pub window_seconds: u32,
    pub max_concurrency: u32,
    pub policy_sha256: Sha256Digest,
}

impl QuotaContract {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported QuotaContract schema version",
            ));
        }
        if self.requests_per_window == 0
            || self.tokens_per_window == 0
            || self.window_seconds == 0
            || self.max_concurrency == 0
        {
            return Err(AuthBusContractError::new(
                "quota limits must all be non-zero",
            ));
        }
        validate_digest(&self.policy_sha256, "quota policy")
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("quota"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Confidence attached to an observed provider quota.  Unknown quota is
/// conservative and must never be interpreted as unlimited capacity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QuotaConfidence {
    Known,
    Conservative,
    Unknown,
}

/// Read-only quota observation used by a scheduler; it grants no permit.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaSnapshot {
    pub schema_version: u32,
    pub confidence: QuotaConfidence,
    pub remaining_requests: Option<u64>,
    pub remaining_tokens: Option<u64>,
    pub observed_at_unix_seconds: u64,
    pub retry_after_seconds: Option<u32>,
}

impl QuotaSnapshot {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported QuotaSnapshot schema version",
            ));
        }
        if self.observed_at_unix_seconds == 0 {
            return Err(AuthBusContractError::new(
                "quota observation timestamp must be non-zero",
            ));
        }
        if self.confidence == QuotaConfidence::Known
            && (self.remaining_requests.is_none() || self.remaining_tokens.is_none())
        {
            return Err(AuthBusContractError::new(
                "known quota must include request and token remainder",
            ));
        }
        Ok(())
    }
}

/// Admission request.  Payload/model material crosses the boundary only as
/// digests; the request itself never contains prompts or credentials.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthRequest {
    pub schema_version: u32,
    pub request_id: String,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub model_sha256: Option<Sha256Digest>,
    pub audience: String,
    pub max_usage: u64,
    pub deadline_unix_seconds: u64,
    pub expected_revision: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub policy_sha256: Sha256Digest,
    pub nonce_sha256: Sha256Digest,
}

impl AuthRequest {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported AuthRequest schema version",
            ));
        }
        validate_text(&self.request_id, "request id", MAX_TEXT_BYTES)?;
        self.subject.validate()?;
        if self.subject.generation != self.generation {
            return Err(AuthBusContractError::new(
                "request subject generation does not match request generation",
            ));
        }
        validate_digest(&self.resource_sha256, "request resource")?;
        validate_digest(&self.payload_sha256, "request payload")?;
        if let Some(model) = &self.model_sha256 {
            validate_digest(model, "request model")?;
        }
        validate_text(&self.audience, "request audience", MAX_TEXT_BYTES)?;
        if self.max_usage == 0 {
            return Err(AuthBusContractError::new(
                "request max usage must be non-zero",
            ));
        }
        if self.deadline_unix_seconds == 0 {
            return Err(AuthBusContractError::new(
                "request deadline must be non-zero",
            ));
        }
        if self.owner_epoch == 0 || self.generation == 0 {
            return Err(AuthBusContractError::new(
                "request owner epoch and generation must be non-zero",
            ));
        }
        validate_digest(&self.policy_sha256, "request policy")?;
        validate_digest(&self.nonce_sha256, "request nonce")
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("request"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Lease lifecycle.  Terminal states cannot be reopened by a stale caller.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseState {
    Pending,
    Active,
    Rejected,
    Revoked,
    Expired,
    Indeterminate,
}

/// Owner-issued lease.  `revision` is the local CAS head; `authority_epoch`
/// fences permits after a revoke or owner restart.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceLease {
    pub schema_version: u32,
    pub lease_id: String,
    pub request: AuthRequest,
    pub owner: Principal,
    pub authority_epoch: u64,
    pub revision: u64,
    pub state: LeaseState,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
}

impl ResourceLease {
    pub fn new(
        lease_id: impl Into<String>,
        request: AuthRequest,
        owner: Principal,
        authority_epoch: u64,
        not_before_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<Self, AuthBusContractError> {
        let lease = Self {
            schema_version: AUTHBUS_CONTRACT_SCHEMA_VERSION,
            lease_id: lease_id.into(),
            request,
            owner,
            authority_epoch,
            revision: 1,
            state: LeaseState::Pending,
            not_before_unix_seconds,
            expires_at_unix_seconds,
        };
        lease.validate()?;
        Ok(lease)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported ResourceLease schema version",
            ));
        }
        validate_text(&self.lease_id, "lease id", MAX_TEXT_BYTES)?;
        self.request.validate()?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        if self.authority_epoch == 0 || self.revision == 0 {
            return Err(AuthBusContractError::new(
                "lease authority epoch and revision must be non-zero",
            ));
        }
        if self.request.deadline_unix_seconds > self.expires_at_unix_seconds {
            return Err(AuthBusContractError::new(
                "lease expiry must cover the request deadline",
            ));
        }
        Ok(())
    }

    /// Apply one owner-CAS lifecycle transition.  Equal-state replay is
    /// idempotent; every other transition requires the current revision and
    /// authority epoch, then advances the revision exactly once.
    pub fn transition(
        &self,
        expected_revision: u64,
        authority_epoch: u64,
        next_state: LeaseState,
    ) -> Result<Self, AuthBusContractError> {
        self.validate()?;
        if self.revision != expected_revision {
            return Err(AuthBusContractError::new("lease revision CAS mismatch"));
        }
        if self.authority_epoch != authority_epoch {
            return Err(AuthBusContractError::new("lease authority epoch mismatch"));
        }
        if self.state == next_state {
            return Ok(self.clone());
        }
        let allowed = match self.state {
            LeaseState::Pending => matches!(
                next_state,
                LeaseState::Active
                    | LeaseState::Rejected
                    | LeaseState::Revoked
                    | LeaseState::Indeterminate
            ),
            LeaseState::Active => matches!(
                next_state,
                LeaseState::Revoked | LeaseState::Expired | LeaseState::Indeterminate
            ),
            LeaseState::Rejected
            | LeaseState::Revoked
            | LeaseState::Expired
            | LeaseState::Indeterminate => false,
        };
        if !allowed {
            return Err(AuthBusContractError::new(format!(
                "invalid lease transition from {:?} to {:?}",
                self.state, next_state
            )));
        }
        let revision = self
            .revision
            .checked_add(1)
            .ok_or_else(|| AuthBusContractError::new("lease revision overflow"))?;
        let mut transitioned = self.clone();
        transitioned.revision = revision;
        transitioned.state = next_state;
        transitioned.validate()?;
        Ok(transitioned)
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("lease"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Permit scoped to one active lease and one physical-use audience.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UsagePermit {
    pub schema_version: u32,
    pub permit_id: String,
    pub lease_id: String,
    pub owner: Principal,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub model_sha256: Option<Sha256Digest>,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub nonce_sha256: Sha256Digest,
    pub audience: String,
    pub not_before_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub max_usage: u64,
    pub policy_sha256: Sha256Digest,
    pub lease_revision: u64,
    pub fencing_token_sha256: Sha256Digest,
}

impl UsagePermit {
    pub fn from_lease(
        lease: &ResourceLease,
        permit_id: impl Into<String>,
        fencing_token_sha256: Sha256Digest,
    ) -> Result<Self, AuthBusContractError> {
        lease.validate()?;
        if lease.state != LeaseState::Active {
            return Err(AuthBusContractError::new(
                "only an active lease may mint a usage permit",
            ));
        }
        let permit = Self {
            schema_version: AUTHBUS_CONTRACT_SCHEMA_VERSION,
            permit_id: permit_id.into(),
            lease_id: lease.lease_id.clone(),
            owner: lease.owner.clone(),
            subject: lease.request.subject.clone(),
            resource_sha256: lease.request.resource_sha256.clone(),
            payload_sha256: lease.request.payload_sha256.clone(),
            model_sha256: lease.request.model_sha256.clone(),
            authority_epoch: lease.authority_epoch,
            owner_epoch: lease.request.owner_epoch,
            generation: lease.request.generation,
            nonce_sha256: lease.request.nonce_sha256.clone(),
            audience: lease.request.audience.clone(),
            not_before_unix_seconds: lease.not_before_unix_seconds,
            expires_at_unix_seconds: lease.expires_at_unix_seconds,
            max_usage: lease.request.max_usage,
            policy_sha256: lease.request.policy_sha256.clone(),
            lease_revision: lease.revision,
            fencing_token_sha256,
        };
        permit.validate()?;
        Ok(permit)
    }

    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported UsagePermit schema version",
            ));
        }
        validate_text(&self.permit_id, "permit id", MAX_TEXT_BYTES)?;
        validate_text(&self.lease_id, "permit lease id", MAX_TEXT_BYTES)?;
        self.subject.validate()?;
        if self.subject.generation != self.generation {
            return Err(AuthBusContractError::new(
                "permit subject generation does not match permit generation",
            ));
        }
        validate_digest(&self.resource_sha256, "permit resource")?;
        validate_digest(&self.payload_sha256, "permit payload")?;
        if let Some(model) = &self.model_sha256 {
            validate_digest(model, "permit model")?;
        }
        if self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.generation == 0
            || self.lease_revision == 0
        {
            return Err(AuthBusContractError::new(
                "permit epochs, generation and lease revision must be non-zero",
            ));
        }
        validate_digest(&self.nonce_sha256, "permit nonce")?;
        validate_text(&self.audience, "permit audience", MAX_TEXT_BYTES)?;
        validate_window(self.not_before_unix_seconds, self.expires_at_unix_seconds)?;
        if self.max_usage == 0 {
            return Err(AuthBusContractError::new(
                "permit max usage must be non-zero",
            ));
        }
        validate_digest(&self.policy_sha256, "permit policy")?;
        validate_digest(&self.fencing_token_sha256, "permit fencing token")
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("permit"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Provider-use terminal observation.  `Indeterminate` is deliberately not a
/// success state and requires explicit reconciliation by a later stage.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum UsageTerminal {
    Consumed { used: u64 },
    Rejected { reason_code: String },
    Indeterminate { reason_code: String },
}

impl UsageTerminal {
    fn validate(&self, max_usage: u64) -> Result<(), AuthBusContractError> {
        match self {
            Self::Consumed { used } if *used == 0 || *used > max_usage => Err(
                AuthBusContractError::new("consumed usage must be within permit maximum"),
            ),
            Self::Consumed { .. } => Ok(()),
            Self::Rejected { reason_code } | Self::Indeterminate { reason_code } => {
                validate_text(reason_code, "usage reason code", MAX_REASON_BYTES)
            }
        }
    }
}

#[derive(Serialize)]
struct UsageReceiptDigest<'a> {
    schema_version: u32,
    receipt_id: &'a str,
    permit_id: &'a str,
    lease_id: &'a str,
    permit_sha256: &'a Sha256Digest,
    resource_sha256: &'a Sha256Digest,
    authority_epoch: u64,
    generation: u64,
    observed_at_unix_seconds: u64,
    terminal: &'a UsageTerminal,
}

/// Receipt bound to exactly one permit digest.  A receipt is an observation;
/// it is not an external effect acknowledgement or production approval.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UsageReceipt {
    pub schema_version: u32,
    pub receipt_id: String,
    pub permit_id: String,
    pub lease_id: String,
    pub permit_sha256: Sha256Digest,
    pub resource_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub generation: u64,
    pub observed_at_unix_seconds: u64,
    pub terminal: UsageTerminal,
    pub receipt_sha256: Sha256Digest,
}

impl UsageReceipt {
    pub fn new(
        permit: &UsagePermit,
        receipt_id: impl Into<String>,
        observed_at_unix_seconds: u64,
        terminal: UsageTerminal,
    ) -> Result<Self, AuthBusContractError> {
        permit.validate()?;
        let receipt_id = receipt_id.into();
        validate_text(&receipt_id, "receipt id", MAX_TEXT_BYTES)?;
        if observed_at_unix_seconds == 0 {
            return Err(AuthBusContractError::new(
                "receipt observation timestamp must be non-zero",
            ));
        }
        terminal.validate(permit.max_usage)?;
        let mut receipt = Self {
            schema_version: AUTHBUS_CONTRACT_SCHEMA_VERSION,
            receipt_id,
            permit_id: permit.permit_id.clone(),
            lease_id: permit.lease_id.clone(),
            permit_sha256: permit.digest()?,
            resource_sha256: permit.resource_sha256.clone(),
            authority_epoch: permit.authority_epoch,
            generation: permit.generation,
            observed_at_unix_seconds,
            terminal,
            receipt_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        receipt.receipt_sha256 = receipt.compute_digest()?;
        receipt.validate_against(permit)?;
        Ok(receipt)
    }

    pub fn validate_against(&self, permit: &UsagePermit) -> Result<(), AuthBusContractError> {
        permit.validate()?;
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported UsageReceipt schema version",
            ));
        }
        validate_text(&self.receipt_id, "receipt id", MAX_TEXT_BYTES)?;
        if self.permit_id != permit.permit_id || self.lease_id != permit.lease_id {
            return Err(AuthBusContractError::new(
                "usage receipt permit binding mismatch",
            ));
        }
        if self.permit_sha256 != permit.digest()? {
            return Err(AuthBusContractError::new(
                "usage receipt permit digest mismatch",
            ));
        }
        if self.resource_sha256 != permit.resource_sha256
            || self.authority_epoch != permit.authority_epoch
            || self.generation != permit.generation
        {
            return Err(AuthBusContractError::new(
                "usage receipt scope or epoch mismatch",
            ));
        }
        if self.observed_at_unix_seconds == 0 {
            return Err(AuthBusContractError::new(
                "receipt observation timestamp must be non-zero",
            ));
        }
        self.terminal.validate(permit.max_usage)?;
        if self.receipt_sha256 != self.compute_digest()? {
            return Err(AuthBusContractError::new("usage receipt digest mismatch"));
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        validate_digest(&self.receipt_sha256, "receipt digest")?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("receipt"),
            &self.canonical_bytes()?,
        ))
    }

    fn compute_digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        let payload = canonical_json(&UsageReceiptDigest {
            schema_version: self.schema_version,
            receipt_id: &self.receipt_id,
            permit_id: &self.permit_id,
            lease_id: &self.lease_id,
            permit_sha256: &self.permit_sha256,
            resource_sha256: &self.resource_sha256,
            authority_epoch: self.authority_epoch,
            generation: self.generation,
            observed_at_unix_seconds: self.observed_at_unix_seconds,
            terminal: &self.terminal,
        })?;
        Ok(domain_digest(&contract_domain("receipt"), &payload))
    }
}

/// Owner-authored revocation fence.  Applying a revoke must compare both the
/// lease revision and authority epoch before advancing the owner head.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Revoke {
    pub schema_version: u32,
    pub revoke_id: String,
    pub lease_id: String,
    pub owner: Principal,
    pub resource_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub expected_revision: u64,
    pub revocation_revision: u64,
    pub reason_code: String,
    pub effective_at_unix_seconds: u64,
}

impl Revoke {
    pub fn for_lease(
        lease: &ResourceLease,
        revoke_id: impl Into<String>,
        reason_code: impl Into<String>,
        effective_at_unix_seconds: u64,
    ) -> Result<Self, AuthBusContractError> {
        lease.validate()?;
        let revocation_revision = lease
            .revision
            .checked_add(1)
            .ok_or_else(|| AuthBusContractError::new("lease revision overflow"))?;
        let revoke = Self {
            schema_version: AUTHBUS_CONTRACT_SCHEMA_VERSION,
            revoke_id: revoke_id.into(),
            lease_id: lease.lease_id.clone(),
            owner: lease.owner.clone(),
            resource_sha256: lease.request.resource_sha256.clone(),
            authority_epoch: lease.authority_epoch,
            owner_epoch: lease.request.owner_epoch,
            generation: lease.request.generation,
            expected_revision: lease.revision,
            revocation_revision,
            reason_code: reason_code.into(),
            effective_at_unix_seconds,
        };
        revoke.validate_against(lease)?;
        Ok(revoke)
    }

    pub fn validate_against(&self, lease: &ResourceLease) -> Result<(), AuthBusContractError> {
        lease.validate()?;
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported Revoke schema version",
            ));
        }
        validate_text(&self.revoke_id, "revoke id", MAX_TEXT_BYTES)?;
        validate_text(&self.lease_id, "revoke lease id", MAX_TEXT_BYTES)?;
        validate_digest(&self.resource_sha256, "revoke resource")?;
        validate_text(&self.reason_code, "revoke reason code", MAX_REASON_BYTES)?;
        if self.effective_at_unix_seconds == 0 {
            return Err(AuthBusContractError::new(
                "revoke effective timestamp must be non-zero",
            ));
        }
        if self.lease_id != lease.lease_id
            || self.owner != lease.owner
            || self.resource_sha256 != lease.request.resource_sha256
            || self.authority_epoch != lease.authority_epoch
            || self.owner_epoch != lease.request.owner_epoch
            || self.generation != lease.request.generation
            || self.expected_revision != lease.revision
            || self.revocation_revision != lease.revision.saturating_add(1)
        {
            return Err(AuthBusContractError::new("revoke lease binding mismatch"));
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        if self.schema_version != AUTHBUS_CONTRACT_SCHEMA_VERSION {
            return Err(AuthBusContractError::new(
                "unsupported Revoke schema version",
            ));
        }
        validate_text(&self.revoke_id, "revoke id", MAX_TEXT_BYTES)?;
        validate_text(&self.lease_id, "revoke lease id", MAX_TEXT_BYTES)?;
        validate_digest(&self.resource_sha256, "revoke resource")?;
        validate_text(&self.reason_code, "revoke reason code", MAX_REASON_BYTES)?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("revoke"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Basil pin and current candidate binding for B0.  The manifest intentionally
/// records missing source/SBOM/build evidence instead of manufacturing it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusUpstreamPin {
    pub repository: String,
    pub commit: String,
    pub workspace_version: String,
    pub latest_published_release: String,
    pub license: String,
    pub source_status: String,
    pub sbom_status: String,
    pub native_build_status: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusCandidateBinding {
    pub branch: String,
    pub commit: String,
    pub tree: String,
    pub lane: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusSourceAttachment {
    pub path: String,
    pub bytes: u64,
    pub sha256: Sha256Digest,
    pub kind: String,
    pub binding_status: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusRefSet {
    pub upstream: String,
    pub base: String,
    pub integration: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusAuthorityFlags {
    pub authority: bool,
    pub production_caller: bool,
    pub production_writer: bool,
    pub effect_authority: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub g5_allowed: bool,
    pub execute_allowed: bool,
    pub production_listener: bool,
    pub provider_effect: bool,
    pub model_inference: bool,
    pub shared_kg_write: bool,
}

impl AuthBusAuthorityFlags {
    pub(crate) fn all_false(&self) -> bool {
        !self.authority
            && !self.production_caller
            && !self.production_writer
            && !self.effect_authority
            && !self.operator_acceptance
            && !self.promotion
            && !self.g5_allowed
            && !self.execute_allowed
            && !self.production_listener
            && !self.provider_effect
            && !self.model_inference
            && !self.shared_kg_write
    }
}

/// Append-only local source manifest.  `LOCAL_QUALIFICATION_ONLY` is the only
/// accepted status in this slice.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthBusSourceManifest {
    pub schema: String,
    pub plan_id: String,
    pub status: String,
    pub source_binding_status: String,
    pub captured_at: String,
    pub upstream: AuthBusUpstreamPin,
    pub candidate: AuthBusCandidateBinding,
    pub refs: AuthBusRefSet,
    pub attachments: Vec<AuthBusSourceAttachment>,
    pub authority: AuthBusAuthorityFlags,
    pub gaps: Vec<String>,
}

impl AuthBusSourceManifest {
    pub fn validate(&self) -> Result<(), AuthBusContractError> {
        if self.schema != AUTHBUS_SOURCE_MANIFEST_SCHEMA {
            return Err(AuthBusContractError::new(
                "unsupported AuthBus source manifest schema",
            ));
        }
        if self.plan_id != AUTHBUS_PLAN_ID {
            return Err(AuthBusContractError::new(
                "unexpected AuthBus source manifest plan",
            ));
        }
        if self.status != "LOCAL_QUALIFICATION_ONLY" {
            return Err(AuthBusContractError::new(
                "source manifest must remain qualification-only",
            ));
        }
        if self.source_binding_status != "CAPTURED_LOCAL_SNAPSHOT" {
            return Err(AuthBusContractError::new(
                "source manifest must identify its snapshot binding",
            ));
        }
        validate_text(
            &self.captured_at,
            "source manifest capture time",
            MAX_TEXT_BYTES,
        )?;
        if self.upstream.repository != BASIL_UPSTREAM_REPOSITORY
            || self.upstream.commit != BASIL_UPSTREAM_COMMIT
            || self.upstream.workspace_version != BASIL_WORKSPACE_VERSION
            || self.upstream.latest_published_release != BASIL_LATEST_RELEASE
            || self.upstream.license != BASIL_LICENSE
        {
            return Err(AuthBusContractError::new(
                "Basil source pin does not match E.41",
            ));
        }
        for (label, value) in [
            (
                "upstream source status",
                self.upstream.source_status.as_str(),
            ),
            ("upstream SBOM status", self.upstream.sbom_status.as_str()),
            (
                "upstream native build status",
                self.upstream.native_build_status.as_str(),
            ),
        ] {
            validate_text(value, label, MAX_TEXT_BYTES)?;
        }
        for (label, value) in [
            ("candidate branch", self.candidate.branch.as_str()),
            ("candidate lane", self.candidate.lane.as_str()),
        ] {
            validate_text(value, label, MAX_TEXT_BYTES)?;
        }
        validate_lowercase_hex(&self.candidate.commit, "candidate commit", /*expected_len*/ 40)?;
        validate_lowercase_hex(&self.candidate.tree, "candidate tree", /*expected_len*/ 40)?;
        for (label, value) in [
            ("upstream ref", self.refs.upstream.as_str()),
            ("base ref", self.refs.base.as_str()),
            ("integration ref", self.refs.integration.as_str()),
        ] {
            validate_text(value, label, MAX_TEXT_BYTES)?;
        }
        if self.attachments.is_empty() {
            return Err(AuthBusContractError::new(
                "source manifest must include at least one attachment",
            ));
        }
        let mut paths = std::collections::BTreeSet::new();
        for attachment in &self.attachments {
            validate_text(&attachment.path, "source attachment path", MAX_TEXT_BYTES)?;
            if attachment.bytes == 0 {
                return Err(AuthBusContractError::new(
                    "source attachment byte length must be non-zero",
                ));
            }
            validate_text(&attachment.kind, "source attachment kind", MAX_TEXT_BYTES)?;
            if attachment.binding_status != "OBSERVED_SOURCE_BYTES" {
                return Err(AuthBusContractError::new(
                    "source attachment binding status is not observed",
                ));
            }
            validate_digest(&attachment.sha256, "source attachment digest")?;
            if !paths.insert(&attachment.path) {
                return Err(AuthBusContractError::new(
                    "source attachment paths must be unique",
                ));
            }
        }
        if self.gaps.is_empty() {
            return Err(AuthBusContractError::new(
                "source manifest must record current B0 gaps",
            ));
        }
        for gap in &self.gaps {
            validate_text(gap, "source manifest gap", MAX_TEXT_BYTES)?;
        }
        if !self.authority.all_false() {
            return Err(AuthBusContractError::new(
                "source manifest crosses an authority boundary",
            ));
        }
        Ok(())
    }

    /// Validate this manifest against the exact candidate checkout observed by
    /// the caller.  `validate` only checks the wire shape and the qualification
    /// policy; it cannot know which git checkout is currently under test.  A
    /// consumer must therefore supply the observed commit and tree and use this
    /// guard before treating the manifest as evidence for that checkout.
    ///
    /// This remains a provenance check only.  It never enables an authority,
    /// effect, listener, or promotion boundary.
    pub fn validate_for_candidate(
        &self,
        expected_commit: &str,
        expected_tree: &str,
    ) -> Result<(), AuthBusContractError> {
        self.validate()?;
        validate_lowercase_hex(expected_commit, "expected candidate commit", /*expected_len*/ 40)?;
        validate_lowercase_hex(expected_tree, "expected candidate tree", /*expected_len*/ 40)?;
        if self.candidate.commit != expected_commit {
            return Err(AuthBusContractError::new(
                "source manifest candidate commit does not match observed checkout",
            ));
        }
        if self.candidate.tree != expected_tree {
            return Err(AuthBusContractError::new(
                "source manifest candidate tree does not match observed checkout",
            ));
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AuthBusContractError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn digest(&self) -> Result<Sha256Digest, AuthBusContractError> {
        Ok(domain_digest(
            &contract_domain("source-manifest"),
            &self.canonical_bytes()?,
        ))
    }
}

/// Embedded B0 manifest.  The fixture is source data, not generated runtime
/// state; Bazel lists it as compile data alongside the crate manifest.
pub const AUTHBUS_SOURCE_MANIFEST_JSON: &str =
    include_str!("../fixtures/AUTHBUS_SOURCE_MANIFEST.v1.json");

/// Parse and validate the checked-in B0 manifest.
pub fn embedded_source_manifest() -> Result<AuthBusSourceManifest, AuthBusContractError> {
    let manifest: AuthBusSourceManifest = serde_json::from_str(AUTHBUS_SOURCE_MANIFEST_JSON)?;
    manifest.validate()?;
    Ok(manifest)
}

/// Parse the embedded manifest and require an exact observed candidate
/// commit/tree binding before returning it to a consumer.
pub fn embedded_source_manifest_for_candidate(
    expected_commit: &str,
    expected_tree: &str,
) -> Result<AuthBusSourceManifest, AuthBusContractError> {
    let manifest = embedded_source_manifest()?;
    manifest.validate_for_candidate(expected_commit, expected_tree)?;
    Ok(manifest)
}
