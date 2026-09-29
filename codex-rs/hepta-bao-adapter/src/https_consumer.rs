//! Explicitly enrolled HTTPS consumer. It cannot issue its own grant, follow
//! redirects, use an ambient proxy, or return secret bytes in its receipt.

use std::collections::BTreeMap;
use std::fmt;
use std::time::Duration;

use codex_hepta_authbus::AsAuthBusEffectPort;
use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusEffectPort;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::deliver_final_use;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_http_client::HttpClient;
use codex_http_client::HttpClientBuilder;
use codex_http_client::HttpError;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use url::Url;
use zeroize::Zeroizing;

const MAX_RESPONSE_BYTES: usize = 1024 * 1024;

/// Provider credential injected by the enrolled host. Debug never reveals it.
pub struct BaoToken(Zeroizing<String>);

impl BaoToken {
    pub fn new(value: String) -> Result<Self, BaoClientError> {
        let value = Zeroizing::new(value);
        if value.is_empty() || value.len() > 8192 || HeaderValue::from_str(&value).is_err() {
            return Err(BaoClientError::InvalidConfiguration);
        }
        Ok(Self(value))
    }
}
impl fmt::Debug for BaoToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("BaoToken([REDACTED])")
    }
}

/// One exact KV v2 version and string field, bound to one named consumer.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoReadRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub field: String,
    pub version: u64,
    pub expected_secret_sha256: [u8; 32],
}

/// Contains observations only; it is never a reusable permission or secret.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoSecretReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub version: u64,
    pub secret_bytes: usize,
}

/// Host-selected AuthBus identities for one provider operation. The operation
/// identity is supplied by the durable operation owner and becomes part of the
/// reservation and exact final-use effect digest; this adapter never invents it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoAuthBusAdmission {
    pub policy_revision: u64,
    pub quota_key: StableId,
    pub expected_quota_revision: u64,
    pub operation_id: StableId,
    pub amount: u64,
    pub expires_at_ms: u64,
}

/// Independent evidence producer used by the product host. AuthBus verifies
/// every returned signature; the Bao adapter never owns trusted-time or
/// settlement signing keys.
pub trait BaoAuthBusEvidenceProvider {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError>;

    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        observed_cost: u64,
        terminal_evidence_digest: Digest32,
        observed_at_ms: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError>;
}

#[derive(Debug, thiserror::Error)]
pub enum BaoAuthBusError {
    #[error(transparent)]
    Provider(#[from] BaoClientError),
    #[error(transparent)]
    Control(#[from] AuthBusAuthorityError),
    #[error("AuthBus evidence producer failed: {0}")]
    Evidence(&'static str),
    #[error("provider outcome is indeterminate; reservation remains held")]
    Indeterminate {
        reservation_id: StableId,
        provider_error: BaoClientError,
    },
    #[error("provider effect completed but AuthBus terminal settlement is pending")]
    SettlementPending {
        reservation_id: StableId,
        receipt: Option<BaoSecretReceipt>,
        control_error: String,
    },
}

pub struct BaoClient {
    client: HttpClient,
    origin: Url,
    ca_sha256: [u8; 32],
    token: BaoToken,
}

impl fmt::Debug for BaoClient {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("BaoClient([ENROLLED HTTPS DESTINATION])")
    }
}

impl BaoClient {
    pub fn new(
        endpoint: &str,
        ca_pem: &[u8],
        token: BaoToken,
        timeout: Duration,
    ) -> Result<Self, BaoClientError> {
        if endpoint.len() > 2048
            || ca_pem.len() > 128 * 1024
            || timeout.is_zero()
            || timeout > Duration::from_secs(60)
        {
            return Err(BaoClientError::InvalidConfiguration);
        }
        let origin = Url::parse(endpoint).map_err(|_| BaoClientError::InvalidConfiguration)?;
        if origin.scheme() != "https"
            || origin.host_str().is_none()
            || !origin.username().is_empty()
            || origin.password().is_some()
            || origin.query().is_some()
            || origin.fragment().is_some()
            || origin.path() != "/"
        {
            return Err(BaoClientError::InvalidConfiguration);
        }
        let client = HttpClientBuilder::build_pinned_https_direct(ca_pem, timeout)
            .map_err(|_| BaoClientError::InvalidConfiguration)?;
        Ok(Self {
            client,
            origin,
            ca_sha256: Digest32::of_bytes(ca_pem).into_array(),
            token,
        })
    }

    /// Public metadata for the independent issuer to review and sign. This
    /// function performs no network activity and does not mint authority.
    pub fn binding(&self, request: &BaoReadRequest) -> Result<FinalUseBinding, BaoClientError> {
        if !component(&request.subject_id)
            || !component(&request.consumer_id)
            || (!request.namespace.is_empty() && !segmented(&request.namespace))
            || !segmented(&request.mount)
            || !segmented(&request.path)
            || !component(&request.field)
            || request.version == 0
            || request.expected_secret_sha256 == [0; 32]
        {
            return Err(BaoClientError::InvalidRequest);
        }
        let bytes = serde_json::to_vec(&(
            "hepta.bao.read.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.scope.v1",
            self.origin.as_str(),
            &request.namespace,
            &request.mount,
            &request.consumer_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&bytes).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: request.expected_secret_sha256,
        })
    }

    /// Canonical digest binding the durable operation identity to the exact
    /// kernel final-use tuple consumed by this provider request.
    pub fn authbus_effect_digest(
        &self,
        request: &BaoReadRequest,
        operation_id: &StableId,
    ) -> Result<Digest32, BaoClientError> {
        let binding = self.binding(request)?;
        let bytes = serde_json::to_vec(&(
            "hepta.authbus.bao-effect.v3",
            operation_id.as_str(),
            &binding,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

fn segmented(value: &str) -> bool {
    value.len() <= 1024 && value.split('/').all(component)
}

#[path = "https_consumer_effect.rs"]
mod effect;
#[path = "https_consumer_delivery.rs"]
mod delivery;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoClientError {
    InvalidConfiguration,
    InvalidRequest,
    Authority(FinalUseError),
    ProviderDenied,
    ProviderUnavailable,
    NotFound,
    TransportUnavailable,
    TimedOut,
    ResponseTooLarge,
    InvalidResponse,
    VersionMismatch,
    SecretDigestMismatch,
    ConsumerIndeterminate,
}
impl fmt::Display for BaoClientError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for BaoClientError {}

#[cfg(all(test, unix))]
#[path = "https_consumer_tests.rs"]
mod tests;
