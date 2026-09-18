//! Provider-native HeptaBao dynamic-secret lease client.
//!
//! Mutation authority is claimed before the network boundary.  No mutation is
//! automatically retried: transport loss, an oversized/malformed success
//! response, or a post-dispatch authority failure is reported as an unknown
//! outcome that must be reconciled by lease lookup/pending-operation readback.
//! Generated secret bytes are released only to the synchronous trusted
//! consumer supplied to `request_secret_lease`; receipts contain metadata and
//! digests only.

use std::fmt;

use base64::{Engine as _, engine::general_purpose::STANDARD};
use codex_hepta_contracts::{
    FinalUseAuthority, FinalUseBinding, FinalUseError, SignedFinalUseGrant,
};
use codex_hepta_types::Digest32;
use http::{StatusCode, header::HeaderValue};
use serde::{Deserialize, Serialize};
use url::Url;
use zeroize::Zeroizing;

use crate::https_consumer::BaoClient;

const MAX_PROVIDER_REQUEST_BYTES: usize = 128 * 1024;
const MAX_DYNAMIC_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
const MAX_LEASE_TTL_SECONDS: u64 = 366 * 24 * 60 * 60;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoLeaseState {
    Active,
    Revoked,
    Expired,
    ReconciliationRequired,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseMetadata {
    pub lease_id: String,
    pub scope: String,
    pub state: BaoLeaseState,
    pub issued_at: u64,
    pub expires_at: u64,
    pub renewable: bool,
    pub generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseIssueReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub secret_bytes: usize,
    pub lease: BaoLeaseMetadata,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseMutationReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub lease: BaoLeaseMetadata,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoPendingLeaseOperation {
    pub lease_id: String,
    pub operation: String,
    pub generation: u64,
}

pub struct BaoLeaseIssueRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub operation_id: String,
    pub scope: String,
    pub ttl_seconds: u64,
    pub renewable: bool,
    provider_request: Zeroizing<Vec<u8>>,
}

impl fmt::Debug for BaoLeaseIssueRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoLeaseIssueRequest")
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("namespace", &self.namespace)
            .field("operation_id", &self.operation_id)
            .field("scope", &self.scope)
            .field("ttl_seconds", &self.ttl_seconds)
            .field("renewable", &self.renewable)
            .field("provider_request", &"[REDACTED]")
            .finish()
    }
}

impl BaoLeaseIssueRequest {
    pub fn new(
        subject_id: String,
        consumer_id: String,
        namespace: String,
        operation_id: String,
        scope: String,
        ttl_seconds: u64,
        renewable: bool,
        provider_request: Vec<u8>,
    ) -> Result<Self, BaoLeaseClientError> {
        let request = Self {
            subject_id,
            consumer_id,
            namespace,
            operation_id,
            scope,
            ttl_seconds,
            renewable,
            provider_request: Zeroizing::new(provider_request),
        };
        request.validate()?;
        Ok(request)
    }

    fn validate(&self) -> Result<(), BaoLeaseClientError> {
        validate_subject_consumer(&self.subject_id, &self.consumer_id, &self.namespace)?;
        if !heptabao_id(&self.operation_id)
            || !canonical_scope(&self.scope)
            || !(1..=MAX_LEASE_TTL_SECONDS).contains(&self.ttl_seconds)
            || self.provider_request.is_empty()
            || self.provider_request.len() > MAX_PROVIDER_REQUEST_BYTES
        {
            return Err(BaoLeaseClientError::InvalidRequest);
        }
        Ok(())
    }
}

pub struct BaoLeaseRenewRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub operation_id: String,
    pub lease_id: String,
    pub ttl_seconds: u64,
    provider_request: Zeroizing<Vec<u8>>,
}

impl fmt::Debug for BaoLeaseRenewRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoLeaseRenewRequest")
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("namespace", &self.namespace)
            .field("operation_id", &self.operation_id)
            .field("lease_id", &self.lease_id)
            .field("ttl_seconds", &self.ttl_seconds)
            .field("provider_request", &"[REDACTED]")
            .finish()
    }
}

impl BaoLeaseRenewRequest {
    pub fn new(
        subject_id: String,
        consumer_id: String,
        namespace: String,
        operation_id: String,
        lease_id: String,
        ttl_seconds: u64,
        provider_request: Vec<u8>,
    ) -> Result<Self, BaoLeaseClientError> {
        let request = Self {
            subject_id,
            consumer_id,
            namespace,
            operation_id,
            lease_id,
            ttl_seconds,
            provider_request: Zeroizing::new(provider_request),
        };
        request.validate()?;
        Ok(request)
    }

    fn validate(&self) -> Result<(), BaoLeaseClientError> {
        validate_subject_consumer(&self.subject_id, &self.consumer_id, &self.namespace)?;
        if !heptabao_id(&self.operation_id)
            || !heptabao_id(&self.lease_id)
            || !(1..=MAX_LEASE_TTL_SECONDS).contains(&self.ttl_seconds)
            || self.provider_request.is_empty()
            || self.provider_request.len() > MAX_PROVIDER_REQUEST_BYTES
        {
            return Err(BaoLeaseClientError::InvalidRequest);
        }
        Ok(())
    }
}

pub struct BaoLeaseRevokeRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub operation_id: String,
    pub lease_id: String,
    provider_request: Zeroizing<Vec<u8>>,
}

impl fmt::Debug for BaoLeaseRevokeRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoLeaseRevokeRequest")
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("namespace", &self.namespace)
            .field("operation_id", &self.operation_id)
            .field("lease_id", &self.lease_id)
            .field("provider_request", &"[REDACTED]")
            .finish()
    }
}

impl BaoLeaseRevokeRequest {
    pub fn new(
        subject_id: String,
        consumer_id: String,
        namespace: String,
        operation_id: String,
        lease_id: String,
        provider_request: Vec<u8>,
    ) -> Result<Self, BaoLeaseClientError> {
        let request = Self {
            subject_id,
            consumer_id,
            namespace,
            operation_id,
            lease_id,
            provider_request: Zeroizing::new(provider_request),
        };
        request.validate()?;
        Ok(request)
    }

    fn validate(&self) -> Result<(), BaoLeaseClientError> {
        validate_subject_consumer(&self.subject_id, &self.consumer_id, &self.namespace)?;
        if !heptabao_id(&self.operation_id)
            || !heptabao_id(&self.lease_id)
            || self.provider_request.is_empty()
            || self.provider_request.len() > MAX_PROVIDER_REQUEST_BYTES
        {
            return Err(BaoLeaseClientError::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct IssueWire<'a> {
    operation_id: &'a str,
    scope: &'a str,
    ttl: u64,
    renewable: bool,
    provider_request_base64: &'a str,
}

#[derive(Serialize)]
struct RenewWire<'a> {
    operation_id: &'a str,
    lease_id: &'a str,
    ttl: u64,
    provider_request_base64: &'a str,
}

#[derive(Serialize)]
struct RevokeWire<'a> {
    operation_id: &'a str,
    lease_id: &'a str,
    provider_request_base64: &'a str,
}

struct PreparedMutation {
    body: Zeroizing<Vec<u8>>,
    binding: FinalUseBinding,
}

#[derive(Deserialize)]
struct IssueEnvelope {
    data: IssueData,
}

#[derive(Deserialize)]
struct IssueData {
    lease: BaoLeaseMetadata,
    value_base64: Zeroizing<String>,
}

#[derive(Deserialize)]
struct LeaseEnvelope {
    data: BaoLeaseMetadata,
}

#[derive(Deserialize)]
struct PendingEnvelope {
    data: PendingData,
}

#[derive(Deserialize)]
struct PendingData {
    pending: Option<BaoPendingLeaseOperation>,
}

#[derive(Default, Deserialize)]
struct MutationErrorEnvelope {
    #[serde(default)]
    reconciliation_required: bool,
    #[serde(default)]
    retryable_before_entry: bool,
}

impl BaoClient {
    /// Binding proposal for an independently signed dynamic-secret issue grant.
    /// `payload_sha256` binds the exact serialized provider mutation request;
    /// the generated secret does not exist yet and is never used as authority.
    pub fn lease_issue_binding(
        &self,
        request: &BaoLeaseIssueRequest,
    ) -> Result<FinalUseBinding, BaoLeaseClientError> {
        Ok(self.prepare_issue(request)?.binding)
    }

    pub fn lease_renew_binding(
        &self,
        request: &BaoLeaseRenewRequest,
    ) -> Result<FinalUseBinding, BaoLeaseClientError> {
        Ok(self.prepare_renew(request)?.binding)
    }

    pub fn lease_revoke_binding(
        &self,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<FinalUseBinding, BaoLeaseClientError> {
        Ok(self.prepare_revoke(request)?.binding)
    }

    /// Issue one provider-native dynamic lease and release its generated secret
    /// only to the trusted synchronous consumer under the final-use revocation
    /// fence.  This method never retries a mutation.
    pub async fn request_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseIssueRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoLeaseIssueReceipt, BaoLeaseClientError> {
        let prepared = self.prepare_issue(request)?;
        let verified = authority
            .claim(grant, &prepared.binding)
            .map_err(BaoLeaseClientError::Authority)?;
        let url = self.endpoint(&["sys", "dynamic-secrets", "issue"])?;
        let (status, body) = self
            .post_mutation(url, &request.namespace, prepared.body.as_slice())
            .await?;
        require_mutation_success(status, &body)?;
        let response_sha256 = Digest32::of_bytes(&body).into_array();
        let decoded: IssueEnvelope =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseClientError::OutcomeUnknown)?;
        validate_issue_lease(&decoded.data.lease, request)?;
        let secret = Zeroizing::new(
            STANDARD
                .decode(decoded.data.value_base64.as_bytes())
                .map_err(|_| BaoLeaseClientError::OutcomeUnknown)?,
        );
        if secret.is_empty() || secret.len() > 1024 * 1024 {
            return Err(BaoLeaseClientError::OutcomeUnknown);
        }
        let secret_sha256 = Digest32::of_bytes(&secret).into_array();
        let receipt = BaoLeaseIssueReceipt {
            request_sha256: prepared.binding.request_sha256,
            response_sha256,
            secret_sha256,
            secret_bytes: secret.len(),
            lease: decoded.data.lease,
        };
        authority
            .with_verified_use(verified, &prepared.binding, || consumer(&secret))
            .map_err(BaoLeaseClientError::PostDispatchAuthority)?
            .map_err(|()| BaoLeaseClientError::ConsumerIndeterminate)?;
        Ok(receipt)
    }

    /// Renew exactly one existing provider lease.  A lost response is unknown,
    /// not retryable; callers reconcile with `lookup_secret_lease` and the
    /// provider pending-operation projection before requesting fresh authority.
    pub async fn renew_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRenewRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseClientError> {
        let prepared = self.prepare_renew(request)?;
        let verified = authority
            .claim(grant, &prepared.binding)
            .map_err(BaoLeaseClientError::Authority)?;
        let url = self.endpoint(&["sys", "leases", "renew"])?;
        let (status, body) = self
            .post_mutation(url, &request.namespace, prepared.body.as_slice())
            .await?;
        require_mutation_success(status, &body)?;
        let response_sha256 = Digest32::of_bytes(&body).into_array();
        let decoded: LeaseEnvelope =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseClientError::OutcomeUnknown)?;
        validate_renewed_lease(&decoded.data, request)?;
        authority
            .with_verified_use(verified, &prepared.binding, || ())
            .map_err(BaoLeaseClientError::PostDispatchAuthority)?;
        Ok(BaoLeaseMutationReceipt {
            request_sha256: prepared.binding.request_sha256,
            response_sha256,
            lease: decoded.data,
        })
    }

    pub async fn revoke_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseClientError> {
        let prepared = self.prepare_revoke(request)?;
        let verified = authority
            .claim(grant, &prepared.binding)
            .map_err(BaoLeaseClientError::Authority)?;
        let url = self.endpoint(&["sys", "leases", "revoke"])?;
        let (status, body) = self
            .post_mutation(url, &request.namespace, prepared.body.as_slice())
            .await?;
        require_mutation_success(status, &body)?;
        let response_sha256 = Digest32::of_bytes(&body).into_array();
        let decoded: LeaseEnvelope =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseClientError::OutcomeUnknown)?;
        validate_revoked_lease(&decoded.data, request)?;
        authority
            .with_verified_use(verified, &prepared.binding, || ())
            .map_err(BaoLeaseClientError::PostDispatchAuthority)?;
        Ok(BaoLeaseMutationReceipt {
            request_sha256: prepared.binding.request_sha256,
            response_sha256,
            lease: decoded.data,
        })
    }

    /// Read-only reconciliation projection.  It never creates, renews or
    /// revokes a provider lease and therefore is safe to repeat.
    pub async fn lookup_secret_lease(
        &self,
        namespace: &str,
        lease_id: &str,
    ) -> Result<BaoLeaseMetadata, BaoLeaseClientError> {
        if (!namespace.is_empty() && !segmented(namespace)) || !heptabao_id(lease_id) {
            return Err(BaoLeaseClientError::InvalidRequest);
        }
        let url = self.endpoint(&["sys", "dynamic-secrets", "leases", lease_id])?;
        let (status, body) = self.get_projection(url, namespace).await?;
        match status {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(BaoLeaseClientError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => return Err(BaoLeaseClientError::NotFound),
            _ => return Err(BaoLeaseClientError::ProviderUnavailable),
        }
        let decoded: LeaseEnvelope =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseClientError::InvalidResponse)?;
        if decoded.data.lease_id != lease_id
            || !canonical_scope(&decoded.data.scope)
            || decoded.data.generation == 0
        {
            return Err(BaoLeaseClientError::InvalidResponse);
        }
        Ok(decoded.data)
    }

    /// Returns the one durable provider invocation requiring reconciliation,
    /// if any.  This read-only endpoint is repeatable and never clears the
    /// provider fence.
    pub async fn pending_secret_lease_operation(
        &self,
        namespace: &str,
    ) -> Result<Option<BaoPendingLeaseOperation>, BaoLeaseClientError> {
        if !namespace.is_empty() && !segmented(namespace) {
            return Err(BaoLeaseClientError::InvalidRequest);
        }
        let url = self.endpoint(&["sys", "dynamic-secrets", "pending"])?;
        let (status, body) = self.get_projection(url, namespace).await?;
        match status {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(BaoLeaseClientError::ProviderDenied);
            }
            _ => return Err(BaoLeaseClientError::ProviderUnavailable),
        }
        let decoded: PendingEnvelope =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseClientError::InvalidResponse)?;
        if decoded.data.pending.as_ref().is_some_and(|pending| {
            !heptabao_id(&pending.lease_id)
                || pending.generation == 0
                || !matches!(pending.operation.as_str(), "issue" | "renew" | "revoke")
        }) {
            return Err(BaoLeaseClientError::InvalidResponse);
        }
        Ok(decoded.data.pending)
    }

    fn prepare_issue(
        &self,
        request: &BaoLeaseIssueRequest,
    ) -> Result<PreparedMutation, BaoLeaseClientError> {
        request.validate()?;
        let encoded = Zeroizing::new(STANDARD.encode(request.provider_request.as_slice()));
        let wire = IssueWire {
            operation_id: &request.operation_id,
            scope: &request.scope,
            ttl: request.ttl_seconds,
            renewable: request.renewable,
            provider_request_base64: &encoded,
        };
        let body = Zeroizing::new(
            serde_json::to_vec(&wire).map_err(|_| BaoLeaseClientError::InvalidRequest)?,
        );
        let binding = self.dynamic_binding(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "issue",
            &request.scope,
            &body,
        )?;
        Ok(PreparedMutation { body, binding })
    }

    fn prepare_renew(
        &self,
        request: &BaoLeaseRenewRequest,
    ) -> Result<PreparedMutation, BaoLeaseClientError> {
        request.validate()?;
        let encoded = Zeroizing::new(STANDARD.encode(request.provider_request.as_slice()));
        let wire = RenewWire {
            operation_id: &request.operation_id,
            lease_id: &request.lease_id,
            ttl: request.ttl_seconds,
            provider_request_base64: &encoded,
        };
        let body = Zeroizing::new(
            serde_json::to_vec(&wire).map_err(|_| BaoLeaseClientError::InvalidRequest)?,
        );
        let binding = self.dynamic_binding(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "renew",
            &request.lease_id,
            &body,
        )?;
        Ok(PreparedMutation { body, binding })
    }

    fn prepare_revoke(
        &self,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<PreparedMutation, BaoLeaseClientError> {
        request.validate()?;
        let encoded = Zeroizing::new(STANDARD.encode(request.provider_request.as_slice()));
        let wire = RevokeWire {
            operation_id: &request.operation_id,
            lease_id: &request.lease_id,
            provider_request_base64: &encoded,
        };
        let body = Zeroizing::new(
            serde_json::to_vec(&wire).map_err(|_| BaoLeaseClientError::InvalidRequest)?,
        );
        let binding = self.dynamic_binding(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "revoke",
            &request.lease_id,
            &body,
        )?;
        Ok(PreparedMutation { body, binding })
    }

    fn dynamic_binding(
        &self,
        subject_id: &str,
        consumer_id: &str,
        namespace: &str,
        operation: &str,
        resource: &str,
        body: &[u8],
    ) -> Result<FinalUseBinding, BaoLeaseClientError> {
        validate_subject_consumer(subject_id, consumer_id, namespace)?;
        let payload_sha256 = Digest32::of_bytes(body).into_array();
        let request = serde_json::to_vec(&(
            "hepta.bao.dynamic-mutation.v1",
            self.origin.as_str(),
            self.ca_sha256,
            namespace,
            operation,
            resource,
            payload_sha256,
        ))
        .map_err(|_| BaoLeaseClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.dynamic-scope.v1",
            self.origin.as_str(),
            namespace,
            operation,
            resource,
            consumer_id,
        ))
        .map_err(|_| BaoLeaseClientError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: subject_id.to_owned(),
            destination_id: "provider:heptabao.dynamic".to_owned(),
            request_sha256: Digest32::of_bytes(&request).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256,
        })
    }

    fn endpoint(&self, segments: &[&str]) -> Result<Url, BaoLeaseClientError> {
        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoLeaseClientError::InvalidConfiguration)?;
            parts.clear().push("v1");
            for segment in segments {
                parts.push(segment);
            }
        }
        Ok(url)
    }

    async fn post_mutation(
        &self,
        url: Url,
        namespace: &str,
        body: &[u8],
    ) -> Result<(StatusCode, Zeroizing<Vec<u8>>), BaoLeaseClientError> {
        let token = self.token_header()?;
        let mut request = self
            .client
            .post(url)
            .header("X-Vault-Token", token)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .body(body.to_vec());
        if !namespace.is_empty() {
            request = request.header("X-Vault-Namespace", namespace);
        }
        let response = request
            .send()
            .await
            .map_err(|_| BaoLeaseClientError::OutcomeUnknown)?;
        let status = response.status();
        let body = read_bounded(response, MAX_DYNAMIC_RESPONSE_BYTES)
            .await
            .map_err(|_| BaoLeaseClientError::OutcomeUnknown)?;
        Ok((status, body))
    }

    async fn get_projection(
        &self,
        url: Url,
        namespace: &str,
    ) -> Result<(StatusCode, Zeroizing<Vec<u8>>), BaoLeaseClientError> {
        let token = self.token_header()?;
        let mut request = self
            .client
            .get(url)
            .header("X-Vault-Token", token)
            .header("Accept", "application/json");
        if !namespace.is_empty() {
            request = request.header("X-Vault-Namespace", namespace);
        }
        let response = request
            .send()
            .await
            .map_err(|_| BaoLeaseClientError::ProviderUnavailable)?;
        let status = response.status();
        let body = read_bounded(response, MAX_DYNAMIC_RESPONSE_BYTES)
            .await
            .map_err(|_| BaoLeaseClientError::InvalidResponse)?;
        Ok((status, body))
    }

    fn token_header(&self) -> Result<HeaderValue, BaoLeaseClientError> {
        let mut token = HeaderValue::from_str(&self.token.0)
            .map_err(|_| BaoLeaseClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        Ok(token)
    }
}

async fn read_bounded(
    mut response: codex_http_client::HttpResponse,
    maximum: usize,
) -> Result<Zeroizing<Vec<u8>>, ()> {
    if response
        .content_length()
        .is_some_and(|length| length > maximum as u64)
    {
        return Err(());
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(|_| ())? {
        if chunk.len() > maximum.saturating_sub(body.len()) {
            return Err(());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn require_mutation_success(
    status: StatusCode,
    body: &[u8],
) -> Result<(), BaoLeaseClientError> {
    if status == StatusCode::OK {
        return Ok(());
    }
    match status {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => Err(BaoLeaseClientError::ProviderDenied),
        StatusCode::NOT_FOUND => Err(BaoLeaseClientError::NotFound),
        StatusCode::CONFLICT => Err(BaoLeaseClientError::Conflict),
        StatusCode::BAD_REQUEST | StatusCode::METHOD_NOT_ALLOWED => {
            Err(BaoLeaseClientError::ProviderRejected)
        }
        StatusCode::NOT_IMPLEMENTED => Err(BaoLeaseClientError::ProviderUnavailable),
        StatusCode::SERVICE_UNAVAILABLE => {
            let error: MutationErrorEnvelope = serde_json::from_slice(body).unwrap_or_default();
            if error.reconciliation_required {
                Err(BaoLeaseClientError::ReconciliationRequired)
            } else if error.retryable_before_entry {
                Err(BaoLeaseClientError::ProviderBeforeEntry)
            } else {
                Err(BaoLeaseClientError::OutcomeUnknown)
            }
        }
        _ => Err(BaoLeaseClientError::OutcomeUnknown),
    }
}

fn validate_issue_lease(
    lease: &BaoLeaseMetadata,
    request: &BaoLeaseIssueRequest,
) -> Result<(), BaoLeaseClientError> {
    if !heptabao_id(&lease.lease_id)
        || lease.scope != request.scope
        || lease.state != BaoLeaseState::Active
        || lease.generation != 1
        || lease.issued_at >= lease.expires_at
        || lease.renewable != request.renewable
    {
        return Err(BaoLeaseClientError::OutcomeUnknown);
    }
    Ok(())
}

fn validate_renewed_lease(
    lease: &BaoLeaseMetadata,
    request: &BaoLeaseRenewRequest,
) -> Result<(), BaoLeaseClientError> {
    if lease.lease_id != request.lease_id
        || !canonical_scope(&lease.scope)
        || lease.state != BaoLeaseState::Active
        || lease.generation < 2
        || lease.issued_at >= lease.expires_at
    {
        return Err(BaoLeaseClientError::OutcomeUnknown);
    }
    Ok(())
}

fn validate_revoked_lease(
    lease: &BaoLeaseMetadata,
    request: &BaoLeaseRevokeRequest,
) -> Result<(), BaoLeaseClientError> {
    if lease.lease_id != request.lease_id
        || !canonical_scope(&lease.scope)
        || lease.state != BaoLeaseState::Revoked
        || lease.generation < 2
    {
        return Err(BaoLeaseClientError::OutcomeUnknown);
    }
    Ok(())
}

fn validate_subject_consumer(
    subject: &str,
    consumer: &str,
    namespace: &str,
) -> Result<(), BaoLeaseClientError> {
    if !component(subject)
        || !component(consumer)
        || (!namespace.is_empty() && !segmented(namespace))
    {
        return Err(BaoLeaseClientError::InvalidRequest);
    }
    Ok(())
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

fn canonical_scope(value: &str) -> bool {
    value.len() <= 1024
        && value.starts_with('/')
        && (value == "/" || !value.ends_with('/'))
        && value
            .split('/')
            .skip(1)
            .all(|segment| component(segment))
}

fn heptabao_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && !value.starts_with(['-', '_'])
        && !value.ends_with(['-', '_'])
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'_'))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoLeaseClientError {
    InvalidConfiguration,
    InvalidRequest,
    Authority(FinalUseError),
    /// The provider mutation may already have completed, but the authority
    /// changed before the local receipt/secret could be released.
    PostDispatchAuthority(FinalUseError),
    ProviderDenied,
    ProviderRejected,
    ProviderUnavailable,
    ProviderBeforeEntry,
    NotFound,
    Conflict,
    /// A mutation crossed (or may have crossed) the network/provider boundary
    /// and no authoritative terminal result is available. Never blind-retry.
    OutcomeUnknown,
    ReconciliationRequired,
    InvalidResponse,
    ConsumerIndeterminate,
}

impl fmt::Display for BaoLeaseClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for BaoLeaseClientError {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{BaoToken, BaoClient};
    use std::time::Duration;

    const TEST_CA: &str = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";

    #[test]
    fn issue_debug_redacts_provider_request() {
        let request = BaoLeaseIssueRequest::new(
            "subject".into(),
            "consumer".into(),
            "".into(),
            "operation_1".into(),
            "/database/creds/app".into(),
            60,
            true,
            b"canary-provider-secret".to_vec(),
        )
        .expect("valid request");
        let debug = format!("{request:?}");
        assert!(!debug.contains("canary-provider-secret"));
        assert!(debug.contains("[REDACTED]"));
    }

    #[test]
    fn request_id_and_scope_are_bounded_before_network() {
        assert!(BaoLeaseIssueRequest::new(
            "subject".into(),
            "consumer".into(),
            "".into(),
            "UPPERCASE".into(),
            "/database/creds/app".into(),
            60,
            true,
            vec![1],
        ).is_err());
        assert!(BaoLeaseIssueRequest::new(
            "subject".into(),
            "consumer".into(),
            "".into(),
            "operation_1".into(),
            "/database/../escape".into(),
            60,
            true,
            vec![1],
        ).is_err());
    }

    #[test]
    fn generated_secret_is_not_part_of_pre_dispatch_authority() {
        // Structural regression: issue binding accepts only provider request
        // material, because a generated credential cannot exist pre-dispatch.
        let source = include_str!("lease_client.rs");
        assert!(source.contains("payload_sha256 = Digest32::of_bytes(body)"));
        assert!(!source.contains("expected_secret_sha256"));
    }

    #[test]
    fn invalid_test_ca_does_not_construct_client() {
        let token = BaoToken::new("hvs.test".into()).expect("token");
        assert!(BaoClient::new(
            "https://127.0.0.1:8200",
            TEST_CA.as_bytes(),
            token,
            Duration::from_secs(1),
        ).is_err());
    }
}
