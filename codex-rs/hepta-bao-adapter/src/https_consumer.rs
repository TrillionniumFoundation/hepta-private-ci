//! Explicitly enrolled HTTPS consumer. It cannot issue its own grant, follow
//! redirects, use an ambient proxy, or return secret bytes in its receipt.

use std::fmt;
use std::future::Future;
use std::time::Duration;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
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

#[path = "https_response.rs"]
mod response;
use response::KvResponse;

const MAX_RESPONSE_BYTES: usize = 1024 * 1024;

/// Provider credential injected by the enrolled host. Debug never reveals it.
pub struct BaoToken(Zeroizing<String>);

impl BaoToken {
    pub fn new(value: String) -> Result<Self, BaoClientError> {
        let value = Zeroizing::new(value);
        // Validate borrowed bytes: constructing a temporary HeaderValue would
        // allocate an unnecessary token copy which is not zeroized on drop.
        if value.is_empty()
            || value.len() > 8192
            || value
                .bytes()
                .any(|byte| byte != b'\t' && (byte < 32 || byte == 127))
        {
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
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoReadRequest {
    pub subject_id: String,
    pub consumer_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub consumer_configuration_sha256: Option<[u8; 32]>,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub field: String,
    pub version: u64,
    pub expected_secret_sha256: [u8; 32],
}

impl fmt::Debug for BaoReadRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoReadRequest")
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("consumer_configuration_sha256", &"[SENSITIVE DIGEST]")
            .field("namespace", &"[SENSITIVE IDENTIFIER]")
            .field("mount", &"[SENSITIVE IDENTIFIER]")
            .field("path", &"[SENSITIVE IDENTIFIER]")
            .field("field", &"[SENSITIVE IDENTIFIER]")
            .field("version", &self.version)
            .field("expected_secret_sha256", &"[SENSITIVE DIGEST]")
            .finish()
    }
}

pub use crate::lease_lifecycle::BaoSecretReceipt;

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

/// Exact authorization inputs for one metadata-bound provider read.
#[derive(Clone, Copy)]
pub struct BaoAuthorizedReadV1<'a> {
    pub admission: &'a BaoAuthBusAdmission,
    pub authority: &'a FinalUseAuthority,
    pub grant: &'a SignedFinalUseGrant,
    pub request: &'a BaoReadRequest,
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
    #[error("durable Bao owner failed: {0}")]
    DurableOwner(#[from] crate::SqliteBaoOwnerErrorV1),
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

pub(crate) enum BaoGuardedDeliveryError<Preparation, Consumer> {
    Preparation(Preparation),
    Consumer(Consumer),
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
            || request.consumer_configuration_sha256 == Some([0; 32])
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

    /// Product composition for a quota-controlled Bao read:
    /// authenticated time -> policy -> reservation -> durable dispatch fence ->
    /// kernel final-use claim -> provider observation -> signed settlement.
    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        read: BaoAuthorizedReadV1<'_>,
        evidence: &mut E,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoSecretReceipt, BaoAuthBusError> {
        self.consume_kv_v2_with_authbus_guarded(
            authbus,
            read,
            evidence,
            |_| Ok(()),
            |_| Ok(()),
            |secret, _receipt| consumer(secret),
        )
        .await
    }

    /// Claim a kernel permit, fetch exactly one version, then deliver only to
    /// the supplied trusted in-process consumer under a live revocation fence.
    /// No automatic retry occurs. The consumer must not reenter the authority.
    pub async fn consume_kv_v2(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoSecretReceipt, BaoClientError> {
        match self
            .consume_kv_v2_guarded(
                authority,
                grant,
                request,
                |_| Ok(()),
                |secret, _receipt| consumer(secret),
            )
            .await?
        {
            Ok(receipt) => Ok(receipt),
            Err(()) => Err(BaoClientError::ConsumerIndeterminate),
        }
    }
}

fn component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
}
fn segmented(value: &str) -> bool {
    value.len() <= 1024 && value.split('/').all(component)
}
pub(crate) async fn settle_observed<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusAuthorityHost,
    evidence: &mut E,
    reservation: &QuotaReservation,
    status: SettlementStatus,
    observed_cost: u64,
    terminal_evidence_digest: Digest32,
    receipt: Option<BaoSecretReceipt>,
) -> Result<Option<BaoSecretReceipt>, BaoAuthBusError> {
    let pending = |error: BaoAuthBusError| BaoAuthBusError::SettlementPending {
        reservation_id: reservation.reservation_id.clone(),
        receipt: receipt.clone(),
        control_error: error.to_string(),
    };
    let attestation = evidence.trusted_time().map_err(pending)?;
    let time = match authbus.observe_trusted_time_attestation(&attestation).await {
        Ok(time) => time,
        Err(error) => {
            return Err(BaoAuthBusError::SettlementPending {
                reservation_id: reservation.reservation_id.clone(),
                receipt,
                control_error: error.to_string(),
            });
        }
    };
    let signed = evidence
        .settlement_evidence(
            reservation,
            status,
            observed_cost,
            terminal_evidence_digest,
            time.wall_time_ms(),
        )
        .map_err(pending)?;
    let issuer = match authbus
        .settlement_issuer(&signed.claims.issuer_id, signed.claims.key_epoch)
        .await
    {
        Ok(issuer) => issuer,
        Err(error) => {
            return Err(BaoAuthBusError::SettlementPending {
                reservation_id: reservation.reservation_id.clone(),
                receipt,
                control_error: error.to_string(),
            });
        }
    };
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("settlement.before");
    if let Err(error) = authbus.settle(&issuer, &signed, time).await {
        return Err(BaoAuthBusError::SettlementPending {
            reservation_id: reservation.reservation_id.clone(),
            receipt,
            control_error: error.to_string(),
        });
    }
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("settlement.after");
    Ok(receipt)
}

fn ambiguous_after_dispatch(error: BaoClientError) -> bool {
    matches!(
        error,
        BaoClientError::TransportUnavailable
            | BaoClientError::TimedOut
            | BaoClientError::ConsumerIndeterminate
            | BaoClientError::Authority(_)
            | BaoClientError::InvalidConfiguration
            | BaoClientError::InvalidRequest
    )
}

fn transport_error(error: HttpError) -> BaoClientError {
    if error.is_timeout() {
        BaoClientError::TimedOut
    } else {
        BaoClientError::TransportUnavailable
    }
}

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

#[path = "provider_authbus_dispatch.rs"]
mod provider_authbus_dispatch;
#[path = "provider_final_use_dispatch.rs"]
mod provider_final_use_dispatch;
