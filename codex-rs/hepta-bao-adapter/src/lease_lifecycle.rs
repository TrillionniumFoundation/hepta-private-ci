use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

use crate::BaoClient;
use crate::BaoClientError;
use crate::consumer::TrustedConsumerError;
use crate::lease_store::BaoLeaseStore;
use crate::lease_store::LeaseStoreError;
use crate::lease_store::PrepareDisposition;

const MAX_LEASE_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_LEASE_TTL_SECONDS: u64 = 7 * 24 * 60 * 60;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoLeaseOperationKind {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoLeaseState {
    Active,
    Revoked,
    Missing,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseMetadata {
    pub lease_id: String,
    pub consumer_id: String,
    pub scope_sha256: [u8; 32],
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub generation: u64,
    pub state: BaoLeaseState,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoDynamicLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub mount: String,
    /// Provider-relative dynamic issue path under the enrolled mount, e.g.
    /// `creds/readonly`. V1 intentionally supports GET-only issuance.
    pub issue_path: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoRenewLeaseRequest {
    pub subject_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoRevokeLeaseRequest {
    pub subject_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseLookupRequest {
    pub subject_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseReceipt {
    pub request_sha256: [u8; 32],
    pub metadata: BaoLeaseMetadata,
    pub delivered_secret_bytes: usize,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoReconciliationOutcome {
    NotApplied,
    Applied,
    Rejected,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseReconciliationObservation {
    pub subject_id: String,
    pub operation_id: String,
    pub original_request_sha256: [u8; 32],
    pub outcome: BaoReconciliationOutcome,
    pub metadata: Option<BaoLeaseMetadata>,
}

/// Durable local metadata owner for provider lease operations. It stores no raw
/// secret bytes or secret fingerprints. Multiple processes may open the same
/// qualified POSIX directory; every mutation reloads state under one OS lock.
pub struct BaoLeaseRegistry {
    store: BaoLeaseStore,
}

impl fmt::Debug for BaoLeaseRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BaoLeaseRegistry([PRIVATE METADATA STORE])")
    }
}

impl BaoLeaseRegistry {
    pub fn open_state_dir(path: &Path) -> Result<Self, BaoClientError> {
        BaoLeaseStore::open(path)
            .map(|store| Self { store })
            .map_err(store_error)
    }

    pub fn lease(&self, lease_id: &str) -> Result<Option<BaoLeaseMetadata>, BaoClientError> {
        self.store.lease(lease_id).map_err(store_error)
    }
}

impl BaoClient {
    pub fn issue_binding(
        &self,
        request: &BaoDynamicLeaseRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_issue(request)?;
        let request_sha256 = typed_digest(&(
            "hepta.bao.lease.issue.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
        ))?;
        let scope_sha256 = typed_digest(&(
            "hepta.bao.lease.scope.v1",
            self.origin.as_str(),
            &request.namespace,
            &request.mount,
            &request.issue_path,
            &request.consumer_id,
        ))?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256,
            scope_sha256,
            // Dynamic output does not exist before issuance. The signed payload
            // digest therefore binds the exact effect request, not a guessed
            // future secret fingerprint.
            payload_sha256: request_sha256,
        })
    }

    pub fn renew_binding(
        &self,
        request: &BaoRenewLeaseRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_renew(request)?;
        lease_control_binding(self, "renew", &request.subject_id, &request.namespace, request)
    }

    pub fn revoke_binding(
        &self,
        request: &BaoRevokeLeaseRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_revoke(request)?;
        lease_control_binding(self, "revoke", &request.subject_id, &request.namespace, request)
    }

    pub fn lookup_binding(
        &self,
        request: &BaoLeaseLookupRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_lookup(request)?;
        lease_control_binding(self, "lookup", &request.subject_id, &request.namespace, request)
    }

    pub fn reconciliation_binding(
        &self,
        observation: &BaoLeaseReconciliationObservation,
    ) -> Result<FinalUseBinding, BaoClientError> {
        if !component(&observation.subject_id)
            || !component(&observation.operation_id)
            || observation.original_request_sha256 == [0; 32]
            || matches!(observation.outcome, BaoReconciliationOutcome::Applied)
                && observation.metadata.is_none()
            || !matches!(observation.outcome, BaoReconciliationOutcome::Applied)
                && observation.metadata.is_some()
        {
            return Err(BaoClientError::InvalidRequest);
        }
        if let Some(metadata) = &observation.metadata {
            validate_metadata(metadata)?;
        }
        let digest = typed_digest(&("hepta.bao.lease.reconcile.v1", observation))?;
        let scope = typed_digest(&(
            "hepta.bao.lease.reconcile.scope.v1",
            &observation.operation_id,
        ))?;
        Ok(FinalUseBinding {
            subject_id: observation.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: digest,
            scope_sha256: scope,
            payload_sha256: digest,
        })
    }

    /// Execute one provider-native dynamic-secret GET. The durable operation is
    /// moved to Dispatched before network I/O. Any transport/timeout/5xx or
    /// malformed success after that point becomes Indeterminate and is never
    /// automatically re-issued under the same operation id.
    pub async fn request_secret_lease(
        &self,
        leases: &BaoLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoDynamicLeaseRequest,
    ) -> Result<BaoLeaseReceipt, BaoClientError> {
        let binding = self.issue_binding(request)?;
        if !self.consumers.contains(&request.consumer_id) {
            return Err(BaoClientError::UnknownConsumer);
        }
        require_dispatch(
            leases
                .store
                .prepare(
                    &request.operation_id,
                    binding.request_sha256,
                    BaoLeaseOperationKind::Issue,
                    None,
                )
                .map_err(store_error)?,
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        leases
            .store
            .mark_dispatched(&request.operation_id, binding.request_sha256)
            .map_err(store_error)?;

        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in request.mount.split('/') {
                parts.push(part);
            }
            for part in request.issue_path.split('/') {
                parts.push(part);
            }
        }

        let mut network = self
            .client
            .get(url)
            .header("X-Vault-Token", self.token_header()?)
            .header("Accept", "application/json");
        if !request.namespace.is_empty() {
            network = network.header("X-Vault-Namespace", &request.namespace);
        }
        let mut response = match network.send().await {
            Ok(response) => response,
            Err(_) => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                leases
                    .store
                    .mark_rejected(&request.operation_id, binding.request_sha256)
                    .map_err(store_error)?;
                return Err(BaoClientError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => {
                leases
                    .store
                    .mark_rejected(&request.operation_id, binding.request_sha256)
                    .map_err(store_error)?;
                return Err(BaoClientError::NotFound);
            }
            _ => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        }
        let body = read_bounded_response(&mut response)
            .await
            .or_else(|_| lease_indeterminate(leases, &request.operation_id, binding.request_sha256))?;
        let decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        };
        if !lease_id(&decoded.lease_id)
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_TTL_SECONDS
            || decoded.data.is_empty()
        {
            return lease_indeterminate(leases, &request.operation_id, binding.request_sha256);
        }
        let expires_at_unix_ms = expiry_from_now(decoded.lease_duration)?;
        let metadata = BaoLeaseMetadata {
            lease_id: decoded.lease_id.clone(),
            consumer_id: request.consumer_id.clone(),
            scope_sha256: binding.scope_sha256,
            expires_at_unix_ms,
            renewable: decoded.renewable,
            generation: 1,
            state: BaoLeaseState::Active,
        };
        validate_metadata(&metadata)?;
        leases
            .store
            .complete(
                &request.operation_id,
                binding.request_sha256,
                metadata.clone(),
            )
            .map_err(store_error)?;

        let secret_payload = Zeroizing::new(
            serde_json::to_vec(&decoded.data).map_err(|_| BaoClientError::ConsumerIndeterminate)?,
        );
        let secret_bytes = secret_payload.len();
        authority
            .with_verified_use(verified, &binding, || {
                self.consumers
                    .consume(&request.consumer_id, secret_payload.as_slice())
            })
            .map_err(BaoClientError::Authority)?
            .map_err(|error| match error {
                TrustedConsumerError::UnknownConsumer => BaoClientError::UnknownConsumer,
                TrustedConsumerError::Indeterminate => BaoClientError::ConsumerIndeterminate,
            })?;
        Ok(BaoLeaseReceipt {
            request_sha256: binding.request_sha256,
            metadata,
            delivered_secret_bytes: secret_bytes,
        })
    }

    pub async fn renew_secret_lease(
        &self,
        leases: &BaoLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoRenewLeaseRequest,
    ) -> Result<BaoLeaseMetadata, BaoClientError> {
        let current = leases
            .store
            .lease(&request.lease_id)
            .map_err(store_error)?
            .ok_or(BaoClientError::NotFound)?;
        if current.state != BaoLeaseState::Active || !current.renewable {
            return Err(BaoClientError::InvalidRequest);
        }
        let binding = self.renew_binding(request)?;
        require_dispatch(
            leases
                .store
                .prepare(
                    &request.operation_id,
                    binding.request_sha256,
                    BaoLeaseOperationKind::Renew,
                    Some(&request.lease_id),
                )
                .map_err(store_error)?,
        )?;
        let _verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        leases
            .store
            .mark_dispatched(&request.operation_id, binding.request_sha256)
            .map_err(store_error)?;

        let body = serde_json::json!({
            "lease_id": request.lease_id,
            "increment": request.increment_seconds,
        });
        let mut response = match self
            .post_control("sys/leases/renew", &request.namespace, &body)
            .await
        {
            Ok(response) => response,
            Err(_) => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN | StatusCode::BAD_REQUEST => {
                leases
                    .store
                    .mark_rejected(&request.operation_id, binding.request_sha256)
                    .map_err(store_error)?;
                return Err(BaoClientError::ProviderDenied);
            }
            _ => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        }
        let response_body = read_bounded_response(&mut response)
            .await
            .or_else(|_| lease_indeterminate(leases, &request.operation_id, binding.request_sha256))?;
        let decoded: LeaseControlResponse = match serde_json::from_slice(&response_body) {
            Ok(decoded) => decoded,
            Err(_) => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        };
        if decoded.lease_id != request.lease_id
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_TTL_SECONDS
        {
            return lease_indeterminate(leases, &request.operation_id, binding.request_sha256);
        }
        let metadata = BaoLeaseMetadata {
            lease_id: request.lease_id.clone(),
            consumer_id: current.consumer_id,
            scope_sha256: current.scope_sha256,
            expires_at_unix_ms: expiry_from_now(decoded.lease_duration)?,
            renewable: decoded.renewable,
            generation: current
                .generation
                .checked_add(1)
                .ok_or(BaoClientError::InvalidResponse)?,
            state: BaoLeaseState::Active,
        };
        leases
            .store
            .complete(
                &request.operation_id,
                binding.request_sha256,
                metadata.clone(),
            )
            .map_err(store_error)?;
        Ok(metadata)
    }

    pub async fn revoke_secret_lease(
        &self,
        leases: &BaoLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoRevokeLeaseRequest,
    ) -> Result<BaoLeaseMetadata, BaoClientError> {
        let current = leases
            .store
            .lease(&request.lease_id)
            .map_err(store_error)?
            .ok_or(BaoClientError::NotFound)?;
        if current.state == BaoLeaseState::Revoked {
            return Err(BaoClientError::LeaseOperationAlreadyCompleted);
        }
        let binding = self.revoke_binding(request)?;
        require_dispatch(
            leases
                .store
                .prepare(
                    &request.operation_id,
                    binding.request_sha256,
                    BaoLeaseOperationKind::Revoke,
                    Some(&request.lease_id),
                )
                .map_err(store_error)?,
        )?;
        let _verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        leases
            .store
            .mark_dispatched(&request.operation_id, binding.request_sha256)
            .map_err(store_error)?;

        let body = serde_json::json!({"lease_id": request.lease_id});
        let response = match self
            .post_control("sys/leases/revoke", &request.namespace, &body)
            .await
        {
            Ok(response) => response,
            Err(_) => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        };
        match response.status() {
            StatusCode::NO_CONTENT | StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN | StatusCode::BAD_REQUEST => {
                leases
                    .store
                    .mark_rejected(&request.operation_id, binding.request_sha256)
                    .map_err(store_error)?;
                return Err(BaoClientError::ProviderDenied);
            }
            _ => return lease_indeterminate(leases, &request.operation_id, binding.request_sha256),
        }
        let metadata = BaoLeaseMetadata {
            lease_id: current.lease_id,
            consumer_id: current.consumer_id,
            scope_sha256: current.scope_sha256,
            expires_at_unix_ms: now_ms()?,
            renewable: false,
            generation: current
                .generation
                .checked_add(1)
                .ok_or(BaoClientError::InvalidResponse)?,
            state: BaoLeaseState::Revoked,
        };
        leases
            .store
            .complete(
                &request.operation_id,
                binding.request_sha256,
                metadata.clone(),
            )
            .map_err(store_error)?;
        Ok(metadata)
    }

    /// Read-only provider reconciliation for a known lease id. It never retries
    /// an indeterminate issue/renew/revoke and does not by itself assert which
    /// prior operation caused the observed state.
    pub async fn lookup_secret_lease(
        &self,
        leases: &BaoLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseLookupRequest,
    ) -> Result<BaoLeaseMetadata, BaoClientError> {
        let binding = self.lookup_binding(request)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        let body = serde_json::json!({"lease_id": request.lease_id});
        let mut response = self
            .post_control("sys/leases/lookup", &request.namespace, &body)
            .await?;
        if response.status() == StatusCode::NOT_FOUND {
            let previous = leases
                .store
                .lease(&request.lease_id)
                .map_err(store_error)?;
            let metadata = BaoLeaseMetadata {
                lease_id: request.lease_id.clone(),
                consumer_id: previous
                    .as_ref()
                    .map(|value| value.consumer_id.clone())
                    .unwrap_or_else(|| "unknown".to_owned()),
                scope_sha256: previous
                    .as_ref()
                    .map(|value| value.scope_sha256)
                    .unwrap_or(binding.scope_sha256),
                expires_at_unix_ms: now_ms()?,
                renewable: false,
                generation: previous
                    .as_ref()
                    .map_or(1, |value| value.generation.saturating_add(1)),
                state: BaoLeaseState::Missing,
            };
            authority
                .with_verified_use(verified, &binding, || {
                    leases.store.reconcile_lease(metadata.clone())
                })
                .map_err(BaoClientError::Authority)?
                .map_err(store_error)?;
            return Ok(metadata);
        }
        if response.status() == StatusCode::UNAUTHORIZED || response.status() == StatusCode::FORBIDDEN {
            return Err(BaoClientError::ProviderDenied);
        }
        if response.status() != StatusCode::OK {
            return Err(BaoClientError::ProviderUnavailable);
        }
        let response_body = read_bounded_response(&mut response).await?;
        let decoded: LeaseLookupResponse =
            serde_json::from_slice(&response_body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.data.id != request.lease_id
            || decoded.data.ttl == 0
            || decoded.data.ttl > MAX_LEASE_TTL_SECONDS
        {
            return Err(BaoClientError::InvalidResponse);
        }
        let previous = leases
            .store
            .lease(&request.lease_id)
            .map_err(store_error)?;
        let metadata = BaoLeaseMetadata {
            lease_id: request.lease_id.clone(),
            consumer_id: previous
                .as_ref()
                .map(|value| value.consumer_id.clone())
                .unwrap_or_else(|| "unknown".to_owned()),
            scope_sha256: previous
                .as_ref()
                .map(|value| value.scope_sha256)
                .unwrap_or(binding.scope_sha256),
            expires_at_unix_ms: expiry_from_now(decoded.data.ttl)?,
            renewable: decoded.data.renewable,
            generation: previous
                .as_ref()
                .map_or(1, |value| value.generation.saturating_add(1)),
            state: BaoLeaseState::Active,
        };
        authority
            .with_verified_use(verified, &binding, || {
                leases.store.reconcile_lease(metadata.clone())
            })
            .map_err(BaoClientError::Authority)?
            .map_err(store_error)?;
        Ok(metadata)
    }

    /// Resolve an indeterminate operation only from an explicit, signed
    /// reconciliation observation. `NotApplied` reopens the same operation id
    /// for a new independently signed dispatch; `Applied` records the observed
    /// lease metadata; `Rejected` terminally closes it. No provider effect is
    /// executed by this method.
    pub fn reconcile_lease_operation(
        &self,
        leases: &BaoLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        observation: &BaoLeaseReconciliationObservation,
    ) -> Result<(), BaoClientError> {
        let binding = self.reconciliation_binding(observation)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || {
                leases.store.resolve_indeterminate(observation)
            })
            .map_err(BaoClientError::Authority)?
            .map_err(store_error)
    }

    fn token_header(&self) -> Result<HeaderValue, BaoClientError> {
        let mut token =
            HeaderValue::from_str(&self.token.0).map_err(|_| BaoClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        Ok(token)
    }

    async fn post_control(
        &self,
        path: &str,
        namespace: &str,
        body: &serde_json::Value,
    ) -> Result<codex_http_client::HttpResponse, BaoClientError> {
        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in path.split('/') {
                parts.push(part);
            }
        }
        let mut request = self
            .client
            .post(url)
            .header("X-Vault-Token", self.token_header()?)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .json(body);
        if !namespace.is_empty() {
            request = request.header("X-Vault-Namespace", namespace);
        }
        request.send().await.map_err(|error| {
            if error.is_timeout() {
                BaoClientError::TimedOut
            } else {
                BaoClientError::TransportUnavailable
            }
        })
    }
}

fn require_dispatch(disposition: PrepareDisposition) -> Result<(), BaoClientError> {
    match disposition {
        PrepareDisposition::Dispatch => Ok(()),
        PrepareDisposition::Indeterminate => Err(BaoClientError::LeaseOperationIndeterminate),
        PrepareDisposition::AlreadyCompleted => Err(BaoClientError::LeaseOperationAlreadyCompleted),
        PrepareDisposition::Rejected => Err(BaoClientError::ProviderDenied),
    }
}

fn lease_indeterminate<T>(
    leases: &BaoLeaseRegistry,
    operation_id: &str,
    request_sha256: [u8; 32],
) -> Result<T, BaoClientError> {
    leases
        .store
        .mark_indeterminate(operation_id, request_sha256)
        .map_err(store_error)?;
    Err(BaoClientError::LeaseOperationIndeterminate)
}

async fn read_bounded_response(
    response: &mut codex_http_client::HttpResponse,
) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_LEASE_RESPONSE_BYTES as u64)
    {
        return Err(BaoClientError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(|error| {
        if error.is_timeout() {
            BaoClientError::TimedOut
        } else {
            BaoClientError::TransportUnavailable
        }
    })? {
        if chunk.len() > MAX_LEASE_RESPONSE_BYTES - body.len() {
            return Err(BaoClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn lease_control_binding<T: Serialize>(
    client: &BaoClient,
    operation: &str,
    subject_id: &str,
    namespace: &str,
    request: &T,
) -> Result<FinalUseBinding, BaoClientError> {
    let request_sha256 = typed_digest(&(
        "hepta.bao.lease.control.v1",
        operation,
        client.origin.as_str(),
        client.ca_sha256,
        request,
    ))?;
    let scope_sha256 = typed_digest(&(
        "hepta.bao.lease.control.scope.v1",
        client.origin.as_str(),
        namespace,
        operation,
        request,
    ))?;
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id: "provider:heptabao".to_owned(),
        request_sha256,
        scope_sha256,
        payload_sha256: request_sha256,
    })
}

fn typed_digest(value: &impl Serialize) -> Result<[u8; 32], BaoClientError> {
    let bytes = serde_json::to_vec(value).map_err(|_| BaoClientError::InvalidRequest)?;
    Ok(Digest32::of_bytes(&bytes).into_array())
}

fn validate_issue(request: &BaoDynamicLeaseRequest) -> Result<(), BaoClientError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || !component(&request.operation_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.mount)
        || !segmented(&request.issue_path)
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_renew(request: &BaoRenewLeaseRequest) -> Result<(), BaoClientError> {
    if !component(&request.subject_id)
        || !component(&request.operation_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !lease_id(&request.lease_id)
        || request.increment_seconds == 0
        || request.increment_seconds > MAX_LEASE_TTL_SECONDS
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_revoke(request: &BaoRevokeLeaseRequest) -> Result<(), BaoClientError> {
    if !component(&request.subject_id)
        || !component(&request.operation_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !lease_id(&request.lease_id)
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_lookup(request: &BaoLeaseLookupRequest) -> Result<(), BaoClientError> {
    if !component(&request.subject_id)
        || !component(&request.operation_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !lease_id(&request.lease_id)
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_metadata(metadata: &BaoLeaseMetadata) -> Result<(), BaoClientError> {
    if !lease_id(&metadata.lease_id)
        || !component(&metadata.consumer_id)
        || metadata.scope_sha256 == [0; 32]
        || metadata.expires_at_unix_ms == 0
        || metadata.generation == 0
    {
        return Err(BaoClientError::InvalidRequest);
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

fn lease_id(value: &str) -> bool {
    value.len() <= 2048 && !value.is_empty() && value.split('/').all(component)
}

fn now_ms() -> Result<u64, BaoClientError> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| BaoClientError::ProviderUnavailable)?
        .as_millis();
    u64::try_from(value).map_err(|_| BaoClientError::ProviderUnavailable)
}

fn expiry_from_now(ttl_seconds: u64) -> Result<u64, BaoClientError> {
    now_ms()?
        .checked_add(
            ttl_seconds
                .checked_mul(1000)
                .ok_or(BaoClientError::InvalidResponse)?,
        )
        .ok_or(BaoClientError::InvalidResponse)
}

fn store_error(error: LeaseStoreError) -> BaoClientError {
    match error {
        LeaseStoreError::Conflict => BaoClientError::LeaseOperationConflict,
        LeaseStoreError::InvalidState
        | LeaseStoreError::CapacityExceeded
        | LeaseStoreError::Unavailable
        | LeaseStoreError::UnsafeStateDirectory => BaoClientError::LeaseStateUnavailable,
    }
}

#[derive(Deserialize)]
struct DynamicLeaseResponse {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
    data: BTreeMap<String, Zeroizing<String>>,
}

#[derive(Deserialize)]
struct LeaseControlResponse {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
}

#[derive(Deserialize)]
struct LeaseLookupResponse {
    data: LeaseLookupData,
}

#[derive(Deserialize)]
struct LeaseLookupData {
    id: String,
    ttl: u64,
    renewable: bool,
}

#[cfg(all(test, unix))]
#[path = "lease_lifecycle_tests.rs"]
mod tests;
