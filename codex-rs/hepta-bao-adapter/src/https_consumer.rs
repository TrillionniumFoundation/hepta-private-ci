//! Explicitly enrolled HTTPS consumer. It cannot issue its own grant, follow
//! redirects, use an ambient proxy, or return secret bytes in its receipt.

use std::collections::BTreeMap;
use std::fmt;
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

/// Borrowed kernel authorization inputs, not a grant or an AuthBus authority.
/// The existing final-use verifier still validates and consumes the signed grant.
pub struct BaoFinalUseContext<'a> {
    pub authority: &'a FinalUseAuthority,
    pub grant: &'a SignedFinalUseGrant,
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

    /// Product composition for a quota-controlled Bao read:
    /// authenticated time -> policy -> reservation -> durable dispatch fence ->
    /// kernel final-use claim -> provider observation -> signed settlement.
    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        admission: &BaoAuthBusAdmission,
        final_use: BaoFinalUseContext<'_>,
        request: &BaoReadRequest,
        evidence: &mut E,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoSecretReceipt, BaoAuthBusError> {
        let BaoFinalUseContext { authority, grant } = final_use;
        if admission.policy_revision == 0
            || admission.expected_quota_revision == 0
            || admission.amount == 0
            || admission.expires_at_ms == 0
        {
            return Err(BaoClientError::InvalidRequest.into());
        }
        let binding = self.binding(request)?;
        let principal = StableId::new(binding.subject_id.clone())
            .map_err(|_| BaoClientError::InvalidRequest)?;
        let action =
            StableId::new("action:bao-read").map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = Digest32::from_array(binding.scope_sha256);
        let effect_digest = self.authbus_effect_digest(request, &admission.operation_id)?;

        let observed = evidence.trusted_time()?;
        let time = authbus.observe_trusted_time_attestation(&observed).await?;
        let decision = authbus
            .authorize(
                &principal,
                &action,
                scope,
                admission.policy_revision,
                time.clone(),
            )
            .await?;
        let reservation = authbus
            .reserve(
                &decision,
                ReservationRequest {
                    quota_key: admission.quota_key.clone(),
                    operation_id: admission.operation_id.clone(),
                    amount: admission.amount,
                    effect_digest,
                    expected_quota_revision: admission.expected_quota_revision,
                    expires_at_ms: admission.expires_at_ms,
                },
                time,
            )
            .await?;

        // Re-sample authenticated time immediately before the irreversible
        // boundary. Once this transition commits, timeout/transport uncertainty
        // can never refund quota without signed terminal evidence.
        let dispatch_time = authbus
            .observe_trusted_time_attestation(&evidence.trusted_time()?)
            .await?;
        let dispatched = authbus
            .mark_dispatch_attempted(
                &reservation.reservation_id,
                reservation.revision,
                effect_digest,
                dispatch_time,
            )
            .await?;

        let provider = self
            .consume_kv_v2(authority, grant, request, consumer)
            .await;
        match provider {
            Ok(receipt) => {
                let terminal = Digest32::of_bytes(
                    &serde_json::to_vec(&receipt)
                        .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?,
                );
                settle_observed(
                    authbus,
                    evidence,
                    &dispatched,
                    SettlementStatus::Completed,
                    admission.amount,
                    terminal,
                    Some(receipt),
                )
                .await?
                .ok_or(BaoAuthBusError::Evidence(
                    "successful settlement lost its receipt",
                ))
            }
            Err(error) if ambiguous_after_dispatch(error) => {
                let time = authbus
                    .observe_trusted_time_attestation(&evidence.trusted_time()?)
                    .await;
                match time {
                    Ok(time) => {
                        let _ = authbus
                            .mark_indeterminate(
                                &dispatched.reservation_id,
                                dispatched.revision,
                                time,
                            )
                            .await;
                    }
                    Err(_) => {
                        // The durable DispatchAttempted row remains conservative;
                        // restart reconciliation promotes it to Indeterminate.
                    }
                }
                Err(BaoAuthBusError::Indeterminate {
                    reservation_id: dispatched.reservation_id,
                    provider_error: error,
                })
            }
            Err(error) => {
                let terminal =
                    Digest32::of_bytes(format!("hepta.bao.terminal.v3:{error:?}").as_bytes());
                match settle_observed(
                    authbus,
                    evidence,
                    &dispatched,
                    SettlementStatus::Completed,
                    admission.amount,
                    terminal,
                    None,
                )
                .await
                {
                    Ok(None) => Err(BaoAuthBusError::Provider(error)),
                    Ok(Some(_)) => Err(BaoAuthBusError::Evidence(
                        "terminal provider failure unexpectedly produced a receipt",
                    )),
                    Err(pending) => Err(pending),
                }
            }
        }
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
            .consume_kv_v2_guarded(authority, grant, request, consumer)
            .await?
        {
            Ok(receipt) => Ok(receipt),
            Err(()) => Err(BaoClientError::ConsumerIndeterminate),
        }
    }

    /// Crate-private typed final-delivery gate used by the registered host.
    /// Provider I/O and secret validation complete first, then kernel authority
    /// is revalidated and this gate executes at the final consumer boundary.
    pub(crate) async fn consume_kv_v2_guarded<E>(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), E>,
    ) -> Result<Result<BaoSecretReceipt, E>, BaoClientError> {
        let binding = self.binding(request)?;
        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in request.mount.split('/') {
                parts.push(part);
            }
            parts.push("data");
            for part in request.path.split('/') {
                parts.push(part);
            }
        }
        url.query_pairs_mut()
            .append_pair("version", &request.version.to_string());
        let mut token = HeaderValue::from_str(&self.token.0)
            .map_err(|_| BaoClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        let mut network_request = self
            .client
            .get(url)
            .header("X-Vault-Token", token)
            .header("Accept", "application/json");
        if !request.namespace.is_empty() {
            network_request = network_request.header("X-Vault-Namespace", &request.namespace);
        }
        let verified =
            claim_final_use(authority, grant, &binding).map_err(BaoClientError::Authority)?;
        let mut response = network_request.send().await.map_err(transport_error)?;
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(BaoClientError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => return Err(BaoClientError::NotFound),
            _ => return Err(BaoClientError::ProviderUnavailable),
        }
        if response
            .content_length()
            .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
        {
            return Err(BaoClientError::ResponseTooLarge);
        }
        let mut body = Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
            if chunk.len() > MAX_RESPONSE_BYTES - body.len() {
                return Err(BaoClientError::ResponseTooLarge);
            }
            body.extend_from_slice(&chunk);
        }
        let decoded: KvResponse =
            serde_json::from_slice(&body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.data.metadata.version != request.version {
            return Err(BaoClientError::VersionMismatch);
        }
        let secret = decoded
            .data
            .data
            .get(&request.field)
            .ok_or(BaoClientError::InvalidResponse)?;
        let digest = Digest32::of_bytes(secret.as_bytes()).into_array();
        if digest != request.expected_secret_sha256 {
            return Err(BaoClientError::SecretDigestMismatch);
        }
        let receipt = BaoSecretReceipt {
            request_sha256: binding.request_sha256,
            response_sha256: Digest32::of_bytes(&body).into_array(),
            secret_sha256: digest,
            version: request.version,
            secret_bytes: secret.len(),
        };
        match deliver_final_use(authority, verified, &binding, || {
            consumer(secret.as_bytes())
        })
        .map_err(BaoClientError::Authority)?
        {
            Ok(()) => Ok(Ok(receipt)),
            Err(error) => Ok(Err(error)),
        }
    }
}

#[derive(Deserialize)]
struct KvResponse {
    data: KvPayload,
}
#[derive(Deserialize)]
struct KvPayload {
    data: BTreeMap<String, Zeroizing<String>>,
    metadata: KvMetadata,
}
#[derive(Deserialize)]
struct KvMetadata {
    version: u64,
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
async fn settle_observed<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusAuthorityHost,
    evidence: &mut E,
    reservation: &QuotaReservation,
    status: SettlementStatus,
    observed_cost: u64,
    terminal_evidence_digest: Digest32,
    receipt: Option<BaoSecretReceipt>,
) -> Result<Option<BaoSecretReceipt>, BaoAuthBusError> {
    let time = match authbus
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await
    {
        Ok(time) => time,
        Err(error) => {
            return Err(BaoAuthBusError::SettlementPending {
                reservation_id: reservation.reservation_id.clone(),
                receipt,
                control_error: error.to_string(),
            });
        }
    };
    let signed = evidence.settlement_evidence(
        reservation,
        status,
        observed_cost,
        terminal_evidence_digest,
        time.wall_time_ms(),
    )?;
    if let Err(error) = authbus.settle(&signed, time).await {
        return Err(BaoAuthBusError::SettlementPending {
            reservation_id: reservation.reservation_id.clone(),
            receipt,
            control_error: error.to_string(),
        });
    }
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
