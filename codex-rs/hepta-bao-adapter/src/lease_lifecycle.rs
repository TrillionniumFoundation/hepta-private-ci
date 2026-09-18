//! Dynamic HeptaBao lease lifecycle.
//!
//! The provider boundary is deliberately non-retrying. A durable transition to
//! Requesting/Renewing/RevokePending happens before the provider call. Any
//! transport or ambiguous provider outcome is quarantined and must be
//! reconciled; issuance without an observed provider lease id can never be
//! retried automatically.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SecretLeaseCreateDisposition;
use codex_hepta_contracts::SecretLeaseOperation;
use codex_hepta_contracts::SecretLeaseRecord;
use codex_hepta_contracts::SecretLeaseState;
use codex_hepta_contracts::SecretLeaseStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_http_client::HttpResponse;
use codex_http_client::RequestBuilder;
use http::Method;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use url::Url;
use zeroize::Zeroizing;

use crate::https_consumer::BaoClient;
use crate::https_consumer::BaoClientError;
use crate::https_consumer::component;
use crate::https_consumer::segmented;
use crate::https_consumer::transport_error;

const MAX_DYNAMIC_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_DYNAMIC_REQUEST_FIELDS: usize = 32;
const MAX_DYNAMIC_SECRET_FIELDS: usize = 16;
const MAX_DYNAMIC_VALUE_BYTES: usize = 8192;
const MAX_PROVIDER_LEASE_SECONDS: u64 = 366 * 24 * 60 * 60;
const MAX_RENEW_INCREMENT_SECONDS: u64 = 30 * 24 * 60 * 60;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoLeaseIssueMethod {
    Get,
    Post,
}

/// Dynamic-secret issuance request.
///
/// Values in `request_body` are zeroized by this owner when dropped and are
/// redacted from Debug. Lower HTTP/TLS layers can still create temporary copies.
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseIssueRequest {
    pub lease_key: String,
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub path: String,
    pub method: BaoLeaseIssueMethod,
    pub request_body: BTreeMap<String, Zeroizing<String>>,
    pub secret_fields: Vec<String>,
}

impl fmt::Debug for BaoLeaseIssueRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BaoLeaseIssueRequest")
            .field("lease_key", &self.lease_key)
            .field("operation_id", &self.operation_id)
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("namespace", &self.namespace)
            .field("path", &self.path)
            .field("method", &self.method)
            .field(
                "request_body",
                &format_args!("[REDACTED; {} fields]", self.request_body.len()),
            )
            .field("secret_fields", &self.secret_fields)
            .finish()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRenewRequest {
    pub lease_key: String,
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRevokeRequest {
    pub lease_key: String,
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseReconcileRequest {
    pub lease_key: String,
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
}

/// Ephemeral dynamic-secret values exposed only inside the trusted callback.
pub struct BaoSecretFields<'a> {
    values: &'a BTreeMap<String, Zeroizing<String>>,
}

impl<'a> BaoSecretFields<'a> {
    pub fn get(&self, field: &str) -> Option<&[u8]> {
        self.values.get(field).map(|value| value.as_bytes())
    }

    pub fn contains(&self, field: &str) -> bool {
        self.values.contains_key(field)
    }

    pub fn len(&self) -> usize {
        self.values.len()
    }

    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
}

impl fmt::Debug for BaoSecretFields<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BaoSecretFields")
            .field("field_names", &self.values.keys().collect::<Vec<_>>())
            .finish()
    }
}

impl BaoClient {
    /// Metadata for an independent issuer. The provider's dynamic values are
    /// intentionally not known yet; the grant binds the exact issuance effect,
    /// requested fields and registered final consumer.
    pub fn request_secret_lease_binding(
        &self,
        request: &BaoLeaseIssueRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        let bytes = issue_preimage(self, request)?;
        let request_sha256 = Digest32::of_bytes(&bytes).into_array();
        effect_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.lease_key,
            request_sha256,
            "issue",
        )
    }

    pub async fn renew_secret_lease_binding<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        request: &BaoLeaseRenewRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_renew_request(request)?;
        let record = load_record(store, &request.lease_key).await?;
        if record.state != SecretLeaseState::Active
            || !record.renewable
            || record.provider_lease_id.is_none()
        {
            return Err(BaoClientError::LeaseState);
        }
        operation_binding(
            self,
            &record,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            "renew",
            Some(request.increment_seconds),
        )
    }

    pub async fn revoke_secret_lease_binding<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_common_operation(
            &request.lease_key,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
        )?;
        let record = load_record(store, &request.lease_key).await?;
        if record.state != SecretLeaseState::Active || record.provider_lease_id.is_none() {
            return Err(BaoClientError::LeaseState);
        }
        operation_binding(
            self,
            &record,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            "revoke",
            None,
        )
    }

    pub async fn reconcile_secret_lease_binding<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        request: &BaoLeaseReconcileRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_common_operation(
            &request.lease_key,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
        )?;
        let record = load_record(store, &request.lease_key).await?;
        if !matches!(
            record.state,
            SecretLeaseState::Requesting
                | SecretLeaseState::Renewing
                | SecretLeaseState::RevokePending
                | SecretLeaseState::Unknown
        ) {
            return Err(BaoClientError::LeaseState);
        }
        reconcile_binding(self, &record, request)
    }

    /// Issue one provider-native dynamic lease and deliver only selected string
    /// fields to the trusted final consumer. The durable Requesting record is
    /// inserted before the provider boundary and only the insert winner may
    /// dispatch. No automatic retry is performed.
    pub async fn request_secret_lease<S, F>(
        &self,
        store: &S,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseIssueRequest,
        consumer: F,
    ) -> Result<SecretLeaseRecord, BaoClientError>
    where
        S: SecretLeaseStore + ?Sized,
        F: FnOnce(&BaoSecretFields<'_>) -> Result<(), ()>,
    {
        let binding = self.request_secret_lease_binding(request)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        let request_bytes = issue_preimage(self, request)?;
        let request_digest = Sha256Digest::for_bytes(&request_bytes);
        let requesting = SecretLeaseRecord::requesting(
            request.lease_key.clone(),
            "provider:heptabao".into(),
            request.namespace.clone(),
            request.path.clone(),
            request_digest.clone(),
            request.operation_id.clone(),
            request_digest,
        )
        .map_err(|error| {
            BaoClientError::LeaseStore(codex_hepta_contracts::SecretLeaseStoreError::InvalidRecord(
                error,
            ))
        })?;
        match store
            .create(&requesting)
            .await
            .map_err(BaoClientError::LeaseStore)?
        {
            SecretLeaseCreateDisposition::Inserted => {}
            SecretLeaseCreateDisposition::AlreadyPresent => {
                return Err(BaoClientError::LeaseOperationAlreadyStarted);
            }
        }

        let url = provider_url(&self.origin, &request.path)?;
        let mut network_request = provider_request(self, request.method.into(), url, &request.namespace)?;
        if request.method == BaoLeaseIssueMethod::Post {
            network_request = network_request.json(&request.request_body);
        }

        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                let mapped = transport_error(error);
                transition_unknown(
                    store,
                    &requesting,
                    None,
                    error_code_for_transport(mapped),
                )
                .await?;
                return Err(mapped);
            }
        };
        let status = response.status();
        if !status.is_success() {
            if status.is_client_error() {
                transition_rejected_issue(store, &requesting, rejection_code(status)).await?;
                return Err(provider_status_error(status));
            }
            transition_unknown(store, &requesting, None, "provider_5xx").await?;
            return Err(BaoClientError::ProviderUnavailable);
        }

        let body = match read_body(response).await {
            Ok(body) => body,
            Err(error) => {
                transition_unknown(store, &requesting, None, ambiguity_code(error)).await?;
                return Err(error);
            }
        };
        let mut decoded: DynamicIssueResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                transition_unknown(store, &requesting, None, "invalid_issue_response").await?;
                return Err(BaoClientError::InvalidResponse);
            }
        };
        let observed_lease_id = decoded
            .lease_id
            .take()
            .filter(|value| provider_lease_handle(value));
        let Some(provider_lease_id) = observed_lease_id else {
            transition_unknown(store, &requesting, None, "missing_provider_lease_id").await?;
            return Err(BaoClientError::InvalidResponse);
        };
        let (Some(lease_seconds), Some(renewable), Some(mut data)) = (
            decoded.lease_duration,
            decoded.renewable,
            decoded.data.take(),
        ) else {
            transition_unknown(
                store,
                &requesting,
                Some(provider_lease_id),
                "incomplete_issue_response",
            )
            .await?;
            return Err(BaoClientError::InvalidResponse);
        };
        let Some(expires_at_ms) = expiry_from_now(lease_seconds)? else {
            transition_unknown(
                store,
                &requesting,
                Some(provider_lease_id),
                "invalid_issue_ttl",
            )
            .await?;
            return Err(BaoClientError::InvalidResponse);
        };

        let mut selected = BTreeMap::new();
        for field in &request.secret_fields {
            let Some(value) = data.remove(field) else {
                transition_unknown(
                    store,
                    &requesting,
                    Some(provider_lease_id),
                    "missing_secret_field",
                )
                .await?;
                return Err(BaoClientError::InvalidResponse);
            };
            selected.insert(field.clone(), value);
        }

        let issued_at_ms = now_ms()?;
        let active = SecretLeaseRecord {
            schema_version: requesting.schema_version,
            lease_key: requesting.lease_key.clone(),
            provider_id: requesting.provider_id.clone(),
            provider_namespace: requesting.provider_namespace.clone(),
            provider_path: requesting.provider_path.clone(),
            request_sha256: requesting.request_sha256.clone(),
            provider_lease_id: Some(provider_lease_id),
            state: SecretLeaseState::Active,
            renewable,
            generation: 1,
            issued_at_ms: Some(issued_at_ms),
            expires_at_ms: Some(expires_at_ms),
            revision: next_revision(requesting.revision)?,
            pending_operation: None,
            pending_operation_id: None,
            pending_request_sha256: None,
            last_error_code: None,
        };
        store
            .compare_and_swap(requesting.revision, &active)
            .await
            .map_err(BaoClientError::LeaseStore)?;

        let fields = BaoSecretFields { values: &selected };
        authority
            .with_verified_use(verified, &binding, || consumer(&fields))
            .map_err(BaoClientError::Authority)?
            .map_err(|()| BaoClientError::ConsumerIndeterminate)?;
        Ok(active)
    }

    /// Renew an existing provider lease. The requested increment is advisory;
    /// the returned provider TTL/renewable values become authoritative.
    pub async fn renew_secret_lease<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRenewRequest,
    ) -> Result<SecretLeaseRecord, BaoClientError> {
        validate_renew_request(request)?;
        let current = load_record(store, &request.lease_key).await?;
        if current.state != SecretLeaseState::Active
            || !current.renewable
            || current.provider_lease_id.is_none()
        {
            return Err(BaoClientError::LeaseState);
        }
        let binding = operation_binding(
            self,
            &current,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            "renew",
            Some(request.increment_seconds),
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;

        let operation_sha256 = Sha256Digest::for_bytes(&operation_preimage(
            self,
            &current,
            &request.operation_id,
            "renew",
            Some(request.increment_seconds),
        )?);
        let renewing = SecretLeaseRecord {
            state: SecretLeaseState::Renewing,
            revision: next_revision(current.revision)?,
            pending_operation: Some(SecretLeaseOperation::Renew),
            pending_operation_id: Some(request.operation_id.clone()),
            pending_request_sha256: Some(operation_sha256),
            last_error_code: None,
            ..current.clone()
        };
        store
            .compare_and_swap(current.revision, &renewing)
            .await
            .map_err(BaoClientError::LeaseStore)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(BaoClientError::Authority)?;

        let provider_lease_id = renewing
            .provider_lease_id
            .as_deref()
            .ok_or(BaoClientError::LeaseState)?;
        let url = provider_url(&self.origin, "sys/leases/renew")?;
        let response = match provider_request(self, Method::POST, url, &renewing.provider_namespace)?
            .json(&RenewBody {
                lease_id: provider_lease_id,
                increment: request.increment_seconds,
            })
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                let mapped = transport_error(error);
                transition_unknown(store, &renewing, None, error_code_for_transport(mapped)).await?;
                return Err(mapped);
            }
        };
        let status = response.status();
        if !status.is_success() {
            if status == StatusCode::NOT_FOUND {
                let expired = transition_expired(store, &renewing, "renew_not_found").await?;
                return Ok(expired);
            }
            if status.is_client_error() {
                let active =
                    transition_active_no_effect(store, &renewing, rejection_code(status)).await?;
                let _ = active;
                return Err(provider_status_error(status));
            }
            transition_unknown(store, &renewing, None, "provider_5xx").await?;
            return Err(BaoClientError::ProviderUnavailable);
        }

        let body = match read_body(response).await {
            Ok(body) => body,
            Err(error) => {
                transition_unknown(store, &renewing, None, ambiguity_code(error)).await?;
                return Err(error);
            }
        };
        let decoded: LeaseRenewResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                transition_unknown(store, &renewing, None, "invalid_renew_response").await?;
                return Err(BaoClientError::InvalidResponse);
            }
        };
        if decoded.lease_id.as_deref() != Some(provider_lease_id) {
            transition_unknown(store, &renewing, None, "renew_lease_id_mismatch").await?;
            return Err(BaoClientError::InvalidResponse);
        }
        let (Some(lease_seconds), Some(renewable)) =
            (decoded.lease_duration, decoded.renewable)
        else {
            transition_unknown(store, &renewing, None, "incomplete_renew_response").await?;
            return Err(BaoClientError::InvalidResponse);
        };
        let Some(expires_at_ms) = expiry_from_now(lease_seconds)? else {
            transition_unknown(store, &renewing, None, "invalid_renew_ttl").await?;
            return Err(BaoClientError::InvalidResponse);
        };
        let generation = renewing
            .generation
            .checked_add(1)
            .ok_or(BaoClientError::LeaseState)?;
        let active = SecretLeaseRecord {
            state: SecretLeaseState::Active,
            renewable,
            generation,
            expires_at_ms: Some(expires_at_ms),
            revision: next_revision(renewing.revision)?,
            pending_operation: None,
            pending_operation_id: None,
            pending_request_sha256: None,
            last_error_code: None,
            ..renewing.clone()
        };
        store
            .compare_and_swap(renewing.revision, &active)
            .await
            .map_err(BaoClientError::LeaseStore)?;
        Ok(active)
    }

    /// Revoke using OpenBao's synchronous mode. A lost response is still
    /// ambiguous and is never converted into a retry.
    pub async fn revoke_secret_lease<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<SecretLeaseRecord, BaoClientError> {
        validate_common_operation(
            &request.lease_key,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
        )?;
        let current = load_record(store, &request.lease_key).await?;
        if current.state != SecretLeaseState::Active || current.provider_lease_id.is_none() {
            return Err(BaoClientError::LeaseState);
        }
        let binding = operation_binding(
            self,
            &current,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            "revoke",
            None,
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        let operation_sha256 = Sha256Digest::for_bytes(&operation_preimage(
            self,
            &current,
            &request.operation_id,
            "revoke",
            None,
        )?);
        let pending = SecretLeaseRecord {
            state: SecretLeaseState::RevokePending,
            revision: next_revision(current.revision)?,
            pending_operation: Some(SecretLeaseOperation::Revoke),
            pending_operation_id: Some(request.operation_id.clone()),
            pending_request_sha256: Some(operation_sha256),
            last_error_code: None,
            ..current.clone()
        };
        store
            .compare_and_swap(current.revision, &pending)
            .await
            .map_err(BaoClientError::LeaseStore)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(BaoClientError::Authority)?;

        let provider_lease_id = pending
            .provider_lease_id
            .as_deref()
            .ok_or(BaoClientError::LeaseState)?;
        let url = provider_url(&self.origin, "sys/leases/revoke")?;
        let response = match provider_request(self, Method::POST, url, &pending.provider_namespace)?
            .json(&RevokeBody {
                lease_id: provider_lease_id,
                sync: true,
            })
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                let mapped = transport_error(error);
                transition_unknown(store, &pending, None, error_code_for_transport(mapped)).await?;
                return Err(mapped);
            }
        };
        let status = response.status();
        if status.is_success() || status == StatusCode::NOT_FOUND {
            return transition_revoked(store, &pending, None).await;
        }
        if status.is_client_error() {
            let active = transition_active_no_effect(store, &pending, rejection_code(status)).await?;
            let _ = active;
            return Err(provider_status_error(status));
        }
        transition_unknown(store, &pending, None, "provider_5xx").await?;
        Err(BaoClientError::ProviderUnavailable)
    }

    /// Reconcile a previously ambiguous lease operation through the provider's
    /// lease lookup endpoint. Generic issuance without an observed lease id
    /// cannot be reconciled automatically and remains fail-closed.
    pub async fn reconcile_secret_lease<S: SecretLeaseStore + ?Sized>(
        &self,
        store: &S,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseReconcileRequest,
    ) -> Result<SecretLeaseRecord, BaoClientError> {
        validate_common_operation(
            &request.lease_key,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
        )?;
        let current = load_record(store, &request.lease_key).await?;
        if !matches!(
            current.state,
            SecretLeaseState::Requesting
                | SecretLeaseState::Renewing
                | SecretLeaseState::RevokePending
                | SecretLeaseState::Unknown
        ) {
            return Err(BaoClientError::LeaseState);
        }
        let binding = reconcile_binding(self, &current, request)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(BaoClientError::Authority)?;

        let Some(provider_lease_id) = current.provider_lease_id.as_deref() else {
            return Err(BaoClientError::ReconciliationRequired);
        };
        let pending_operation = current
            .pending_operation
            .ok_or(BaoClientError::LeaseState)?;

        let url = provider_url(&self.origin, "sys/leases/lookup")?;
        let response = provider_request(self, Method::POST, url, &current.provider_namespace)?
            .json(&LookupBody {
                lease_id: provider_lease_id,
            })
            .send()
            .await
            .map_err(transport_error)?;
        let status = response.status();
        if status == StatusCode::NOT_FOUND {
            return match pending_operation {
                SecretLeaseOperation::Revoke => transition_revoked(store, &current, None).await,
                SecretLeaseOperation::Issue | SecretLeaseOperation::Renew => {
                    transition_expired(store, &current, "lease_not_found").await
                }
            };
        }
        if !status.is_success() {
            return Err(provider_status_error(status));
        }
        let body = read_body(response).await?;
        let decoded: LeaseLookupResponse =
            serde_json::from_slice(&body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.data.ttl == 0 {
            return match pending_operation {
                SecretLeaseOperation::Revoke => {
                    Err(BaoClientError::ReconciliationRequired)
                }
                SecretLeaseOperation::Issue | SecretLeaseOperation::Renew => {
                    transition_expired(store, &current, "lease_zero_ttl").await
                }
            };
        }

        match pending_operation {
            SecretLeaseOperation::Revoke => Err(BaoClientError::ReconciliationRequired),
            SecretLeaseOperation::Issue | SecretLeaseOperation::Renew => {
                let Some(expires_at_ms) = expiry_from_now(decoded.data.ttl)? else {
                    return Err(BaoClientError::InvalidResponse);
                };
                let generation = match pending_operation {
                    SecretLeaseOperation::Issue => 1,
                    SecretLeaseOperation::Renew => current
                        .generation
                        .checked_add(1)
                        .ok_or(BaoClientError::LeaseState)?,
                    SecretLeaseOperation::Revoke => unreachable!(),
                };
                let issued_at_ms = current.issued_at_ms.or(Some(now_ms()?));
                let active = SecretLeaseRecord {
                    state: SecretLeaseState::Active,
                    renewable: decoded.data.renewable,
                    generation,
                    issued_at_ms,
                    expires_at_ms: Some(expires_at_ms),
                    revision: next_revision(current.revision)?,
                    pending_operation: None,
                    pending_operation_id: None,
                    pending_request_sha256: None,
                    last_error_code: None,
                    ..current.clone()
                };
                store
                    .compare_and_swap(current.revision, &active)
                    .await
                    .map_err(BaoClientError::LeaseStore)?;
                Ok(active)
            }
        }
    }
}

impl From<BaoLeaseIssueMethod> for Method {
    fn from(value: BaoLeaseIssueMethod) -> Self {
        match value {
            BaoLeaseIssueMethod::Get => Method::GET,
            BaoLeaseIssueMethod::Post => Method::POST,
        }
    }
}

#[derive(Deserialize)]
struct DynamicIssueResponse {
    lease_id: Option<String>,
    lease_duration: Option<u64>,
    renewable: Option<bool>,
    data: Option<BTreeMap<String, Zeroizing<String>>>,
}

#[derive(Deserialize)]
struct LeaseRenewResponse {
    lease_id: Option<String>,
    lease_duration: Option<u64>,
    renewable: Option<bool>,
}

#[derive(Deserialize)]
struct LeaseLookupResponse {
    data: LeaseLookupData,
}

#[derive(Deserialize)]
struct LeaseLookupData {
    ttl: u64,
    renewable: bool,
}

#[derive(Serialize)]
struct RenewBody<'a> {
    lease_id: &'a str,
    increment: u64,
}

#[derive(Serialize)]
struct RevokeBody<'a> {
    lease_id: &'a str,
    sync: bool,
}

#[derive(Serialize)]
struct LookupBody<'a> {
    lease_id: &'a str,
}

fn validate_issue_request(request: &BaoLeaseIssueRequest) -> Result<(), BaoClientError> {
    if !bounded_id(&request.lease_key)
        || !bounded_id(&request.operation_id)
        || !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.path)
        || request.secret_fields.is_empty()
        || request.secret_fields.len() > MAX_DYNAMIC_SECRET_FIELDS
        || request.request_body.len() > MAX_DYNAMIC_REQUEST_FIELDS
        || (request.method == BaoLeaseIssueMethod::Get && !request.request_body.is_empty())
    {
        return Err(BaoClientError::InvalidRequest);
    }
    let mut fields = BTreeSet::new();
    if request
        .secret_fields
        .iter()
        .any(|field| !component(field) || !fields.insert(field))
    {
        return Err(BaoClientError::InvalidRequest);
    }
    if request.request_body.iter().any(|(key, value)| {
        !component(key) || value.len() > MAX_DYNAMIC_VALUE_BYTES
    }) {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_renew_request(request: &BaoLeaseRenewRequest) -> Result<(), BaoClientError> {
    validate_common_operation(
        &request.lease_key,
        &request.operation_id,
        &request.subject_id,
        &request.consumer_id,
    )?;
    if request.increment_seconds == 0 || request.increment_seconds > MAX_RENEW_INCREMENT_SECONDS {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_common_operation(
    lease_key: &str,
    operation_id: &str,
    subject_id: &str,
    consumer_id: &str,
) -> Result<(), BaoClientError> {
    if !bounded_id(lease_key)
        || !bounded_id(operation_id)
        || !component(subject_id)
        || !component(consumer_id)
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn bounded_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn provider_lease_handle(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 2048
        && value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !matches!(byte, b'?' | b'#'))
}

fn issue_preimage(
    client: &BaoClient,
    request: &BaoLeaseIssueRequest,
) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    validate_issue_request(request)?;
    serde_json::to_vec(&(
        "hepta.bao.dynamic-lease.issue.v1",
        client.origin.as_str(),
        client.ca_sha256,
        request,
    ))
    .map(Zeroizing::new)
    .map_err(|_| BaoClientError::InvalidRequest)
}

fn operation_preimage(
    client: &BaoClient,
    record: &SecretLeaseRecord,
    operation_id: &str,
    operation: &str,
    increment_seconds: Option<u64>,
) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    let provider_lease_id = record
        .provider_lease_id
        .as_deref()
        .ok_or(BaoClientError::LeaseState)?;
    serde_json::to_vec(&(
        "hepta.bao.dynamic-lease.operation.v1",
        client.origin.as_str(),
        client.ca_sha256,
        &record.lease_key,
        &record.provider_namespace,
        &record.provider_path,
        provider_lease_id,
        record.revision,
        operation_id,
        operation,
        increment_seconds,
    ))
    .map(Zeroizing::new)
    .map_err(|_| BaoClientError::InvalidRequest)
}

fn operation_binding(
    client: &BaoClient,
    record: &SecretLeaseRecord,
    subject_id: &str,
    consumer_id: &str,
    operation_id: &str,
    operation: &str,
    increment_seconds: Option<u64>,
) -> Result<FinalUseBinding, BaoClientError> {
    let bytes = operation_preimage(
        client,
        record,
        operation_id,
        operation,
        increment_seconds,
    )?;
    effect_binding(
        client,
        subject_id,
        consumer_id,
        &record.provider_namespace,
        &record.lease_key,
        Digest32::of_bytes(&bytes).into_array(),
        operation,
    )
}

fn reconcile_binding(
    client: &BaoClient,
    record: &SecretLeaseRecord,
    request: &BaoLeaseReconcileRequest,
) -> Result<FinalUseBinding, BaoClientError> {
    let bytes = serde_json::to_vec(&(
        "hepta.bao.dynamic-lease.reconcile.v1",
        client.origin.as_str(),
        client.ca_sha256,
        &record.lease_key,
        &record.provider_namespace,
        &record.provider_path,
        &record.provider_lease_id,
        record.revision,
        record.pending_operation,
        &record.pending_operation_id,
        &request.operation_id,
    ))
    .map(Zeroizing::new)
    .map_err(|_| BaoClientError::InvalidRequest)?;
    effect_binding(
        client,
        &request.subject_id,
        &request.consumer_id,
        &record.provider_namespace,
        &record.lease_key,
        Digest32::of_bytes(&bytes).into_array(),
        "reconcile",
    )
}

fn effect_binding(
    client: &BaoClient,
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
    lease_key: &str,
    request_sha256: [u8; 32],
    operation: &str,
) -> Result<FinalUseBinding, BaoClientError> {
    if !component(subject_id)
        || !component(consumer_id)
        || !bounded_id(lease_key)
        || (!namespace.is_empty() && !segmented(namespace))
    {
        return Err(BaoClientError::InvalidRequest);
    }
    let scope = Zeroizing::new(
        serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.scope.v1",
            client.origin.as_str(),
            namespace,
            lease_key,
            consumer_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?,
    );
    let payload = Zeroizing::new(
        serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.effect.v1",
            operation,
            lease_key,
            request_sha256,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?,
    );
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id: "provider:heptabao".to_owned(),
        request_sha256,
        scope_sha256: Digest32::of_bytes(&scope).into_array(),
        payload_sha256: Digest32::of_bytes(&payload).into_array(),
    })
}

fn provider_url(origin: &Url, path: &str) -> Result<Url, BaoClientError> {
    if !segmented(path) {
        return Err(BaoClientError::InvalidRequest);
    }
    let mut url = origin.clone();
    {
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoClientError::InvalidRequest)?;
        parts.clear().push("v1");
        for part in path.split('/') {
            parts.push(part);
        }
    }
    Ok(url)
}

fn provider_request(
    client: &BaoClient,
    method: Method,
    url: Url,
    namespace: &str,
) -> Result<RequestBuilder, BaoClientError> {
    let mut token = HeaderValue::from_str(&client.token.0)
        .map_err(|_| BaoClientError::InvalidConfiguration)?;
    token.set_sensitive(true);
    let mut request = client
        .client
        .request(method, url)
        .header("X-Vault-Token", token)
        .header("Accept", "application/json");
    if !namespace.is_empty() {
        request = request.header("X-Vault-Namespace", namespace);
    }
    Ok(request)
}

async fn read_body(mut response: HttpResponse) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_DYNAMIC_RESPONSE_BYTES as u64)
    {
        return Err(BaoClientError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
        if chunk.len() > MAX_DYNAMIC_RESPONSE_BYTES - body.len() {
            return Err(BaoClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

async fn load_record<S: SecretLeaseStore + ?Sized>(
    store: &S,
    lease_key: &str,
) -> Result<SecretLeaseRecord, BaoClientError> {
    store
        .load(lease_key)
        .await
        .map_err(BaoClientError::LeaseStore)?
        .ok_or(BaoClientError::LeaseState)
}

async fn transition_unknown<S: SecretLeaseStore + ?Sized>(
    store: &S,
    current: &SecretLeaseRecord,
    observed_provider_lease_id: Option<String>,
    code: &'static str,
) -> Result<SecretLeaseRecord, BaoClientError> {
    let mut next = current.clone();
    next.state = SecretLeaseState::Unknown;
    next.revision = next_revision(current.revision)?;
    if let Some(provider_lease_id) = observed_provider_lease_id {
        next.provider_lease_id = Some(provider_lease_id);
    }
    next.last_error_code = Some(code.into());
    store
        .compare_and_swap(current.revision, &next)
        .await
        .map_err(BaoClientError::LeaseStore)?;
    Ok(next)
}

async fn transition_rejected_issue<S: SecretLeaseStore + ?Sized>(
    store: &S,
    current: &SecretLeaseRecord,
    code: &'static str,
) -> Result<SecretLeaseRecord, BaoClientError> {
    let next = SecretLeaseRecord {
        state: SecretLeaseState::Rejected,
        renewable: false,
        revision: next_revision(current.revision)?,
        pending_operation: None,
        pending_operation_id: None,
        pending_request_sha256: None,
        last_error_code: Some(code.into()),
        ..current.clone()
    };
    store
        .compare_and_swap(current.revision, &next)
        .await
        .map_err(BaoClientError::LeaseStore)?;
    Ok(next)
}

async fn transition_active_no_effect<S: SecretLeaseStore + ?Sized>(
    store: &S,
    current: &SecretLeaseRecord,
    code: &'static str,
) -> Result<SecretLeaseRecord, BaoClientError> {
    let next = SecretLeaseRecord {
        state: SecretLeaseState::Active,
        revision: next_revision(current.revision)?,
        pending_operation: None,
        pending_operation_id: None,
        pending_request_sha256: None,
        last_error_code: Some(code.into()),
        ..current.clone()
    };
    store
        .compare_and_swap(current.revision, &next)
        .await
        .map_err(BaoClientError::LeaseStore)?;
    Ok(next)
}

async fn transition_revoked<S: SecretLeaseStore + ?Sized>(
    store: &S,
    current: &SecretLeaseRecord,
    code: Option<&'static str>,
) -> Result<SecretLeaseRecord, BaoClientError> {
    let next = SecretLeaseRecord {
        state: SecretLeaseState::Revoked,
        renewable: false,
        revision: next_revision(current.revision)?,
        pending_operation: None,
        pending_operation_id: None,
        pending_request_sha256: None,
        last_error_code: code.map(str::to_owned),
        ..current.clone()
    };
    store
        .compare_and_swap(current.revision, &next)
        .await
        .map_err(BaoClientError::LeaseStore)?;
    Ok(next)
}

async fn transition_expired<S: SecretLeaseStore + ?Sized>(
    store: &S,
    current: &SecretLeaseRecord,
    code: &'static str,
) -> Result<SecretLeaseRecord, BaoClientError> {
    let generation = if current.pending_operation == Some(SecretLeaseOperation::Issue)
        && current.generation == 0
    {
        1
    } else {
        current.generation
    };
    let next = SecretLeaseRecord {
        state: SecretLeaseState::Expired,
        renewable: false,
        generation,
        revision: next_revision(current.revision)?,
        pending_operation: None,
        pending_operation_id: None,
        pending_request_sha256: None,
        last_error_code: Some(code.into()),
        ..current.clone()
    };
    store
        .compare_and_swap(current.revision, &next)
        .await
        .map_err(BaoClientError::LeaseStore)?;
    Ok(next)
}

fn next_revision(revision: u64) -> Result<u64, BaoClientError> {
    revision.checked_add(1).ok_or(BaoClientError::LeaseState)
}

fn now_ms() -> Result<u64, BaoClientError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| BaoClientError::ClockUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| BaoClientError::ClockUnavailable)
}

fn expiry_from_now(seconds: u64) -> Result<Option<u64>, BaoClientError> {
    if seconds == 0 || seconds > MAX_PROVIDER_LEASE_SECONDS {
        return Ok(None);
    }
    let now = now_ms()?;
    Ok(seconds
        .checked_mul(1000)
        .and_then(|delta| now.checked_add(delta)))
}

fn provider_status_error(status: StatusCode) -> BaoClientError {
    match status {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => BaoClientError::ProviderDenied,
        StatusCode::NOT_FOUND => BaoClientError::NotFound,
        value if value.is_client_error() => BaoClientError::ProviderRejected,
        _ => BaoClientError::ProviderUnavailable,
    }
}

fn rejection_code(status: StatusCode) -> &'static str {
    match status {
        StatusCode::UNAUTHORIZED => "provider_unauthorized",
        StatusCode::FORBIDDEN => "provider_forbidden",
        StatusCode::NOT_FOUND => "provider_not_found",
        StatusCode::TOO_MANY_REQUESTS => "provider_rate_limited",
        _ => "provider_rejected",
    }
}

fn error_code_for_transport(error: BaoClientError) -> &'static str {
    match error {
        BaoClientError::TimedOut => "transport_timeout",
        BaoClientError::TransportUnavailable => "transport_unavailable",
        _ => "transport_unknown",
    }
}

fn ambiguity_code(error: BaoClientError) -> &'static str {
    match error {
        BaoClientError::TimedOut => "response_timeout",
        BaoClientError::TransportUnavailable => "response_transport",
        BaoClientError::ResponseTooLarge => "response_too_large",
        _ => "response_unknown",
    }
}
