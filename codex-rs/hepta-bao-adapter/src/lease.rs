//! Durable dynamic-secret lease lifecycle for the enrolled HeptaBao provider.
//!
//! Raw provider secret fields exist only in zeroizing response buffers and the
//! synchronous enrolled-consumer callback. The durable journal contains lease
//! metadata and operation identities only.

use crate::BaoClient;
use crate::BaoClientError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_http_client::HttpError;
use codex_http_client::HttpResponse;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use serde::de::IgnoredAny;
use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use zeroize::Zeroizing;

#[path = "lease_store.rs"]
mod store;

use store::LeaseRegistry;
use store::StoreError;

const MAX_REQUEST_METADATA_BYTES: usize = 16 * 1024;
const MAX_DYNAMIC_FIELDS: usize = 64;
const MAX_DYNAMIC_FIELD_BYTES: usize = 256 * 1024;
const MAX_DYNAMIC_SECRET_BYTES: usize = 1024 * 1024;
const MAX_LEASE_ID_BYTES: usize = 2048;
const MAX_RENEW_INCREMENT_SECONDS: u64 = 7 * 24 * 60 * 60;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoDynamicMethod {
    Get,
    Post,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub method: BaoDynamicMethod,
    /// Bounded provider request parameters. Values are deliberately redacted
    /// from Debug because some engines accept sensitive bootstrap material.
    pub parameters: BTreeMap<String, String>,
}

impl fmt::Debug for SecretLeaseRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SecretLeaseRequest")
            .field("subject_id", &self.subject_id)
            .field("consumer_id", &self.consumer_id)
            .field("operation_id", &self.operation_id)
            .field("namespace", &self.namespace)
            .field("mount", &self.mount)
            .field("path", &self.path)
            .field("method", &self.method)
            .field("parameter_keys", &self.parameters.keys().collect::<Vec<_>>())
            .finish()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RenewSecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub lease_id: String,
    /// Zero asks the provider to apply its configured default increment.
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RevokeSecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReconcileSecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReconcileIndeterminateIssueRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub issue_operation_id: String,
    pub observed_provider_lease_id: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseState {
    IssuePending,
    Active,
    RenewPending,
    RevokePending,
    IndeterminateIssue,
    IndeterminateRenew,
    IndeterminateRevoke,
    /// The provider lease exists, but the original issue response (and thus
    /// its secret bytes) was lost. It is manageable/revocable, not consumable.
    Orphaned,
    Revoked,
    Expired,
    Rejected,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadata {
    pub operation_id: String,
    pub lease_id: Option<String>,
    pub provider_path: String,
    pub namespace: String,
    pub consumer_id: String,
    pub destination_id: String,
    pub scope_sha256: [u8; 32],
    pub expires_at_unix_ms: Option<u64>,
    pub renewable: bool,
    pub generation: u64,
    pub state: SecretLeaseState,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseReceipt {
    pub request_sha256: [u8; 32],
    pub metadata: SecretLeaseMetadata,
    pub field_count: usize,
    pub secret_bytes: usize,
    pub contains_raw_secret: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RevocationObservation {
    pub metadata: SecretLeaseMetadata,
    pub provider_already_missing: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ReconciliationObservation {
    pub metadata: SecretLeaseMetadata,
    pub provider_present: bool,
}

/// Borrowed dynamic-secret view. There is intentionally no owned conversion.
pub struct SecretLeaseView<'a> {
    fields: &'a BTreeMap<String, Zeroizing<String>>,
}

impl SecretLeaseView<'_> {
    pub fn get(&self, field: &str) -> Option<&str> {
        self.fields.get(field).map(|value| value.as_str())
    }

    pub fn field_names(&self) -> impl Iterator<Item = &str> {
        self.fields.keys().map(String::as_str)
    }

    pub fn field_count(&self) -> usize {
        self.fields.len()
    }
}

impl fmt::Debug for SecretLeaseView<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SecretLeaseView")
            .field("field_count", &self.fields.len())
            .field("values", &"[REDACTED]")
            .finish()
    }
}

/// Host-enrolled callback identity. The private fields prevent call sites from
/// substituting a differently named closure without explicitly re-enrolling it.
pub struct EnrolledSecretConsumer<F> {
    consumer_id: String,
    callback: F,
}

impl<F> fmt::Debug for EnrolledSecretConsumer<F> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EnrolledSecretConsumer")
            .field("consumer_id", &self.consumer_id)
            .field("callback", &"[TRUSTED HOST CALLBACK]")
            .finish()
    }
}

pub struct BaoLeaseManager {
    client: BaoClient,
    registry: LeaseRegistry,
}

impl fmt::Debug for BaoLeaseManager {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BaoLeaseManager")
            .field("destination_id", &self.client.destination_id())
            .field("state", &"[DURABLE METADATA JOURNAL]")
            .finish()
    }
}

impl BaoLeaseManager {
    pub fn open(client: BaoClient, state_directory: &Path) -> Result<Self, SecretLeaseError> {
        let registry = LeaseRegistry::open(state_directory, client.destination_id())
            .map_err(map_store_error)?;
        debug_assert_eq!(registry.destination_id(), client.destination_id());
        Ok(Self { client, registry })
    }

    pub fn client(&self) -> &BaoClient {
        &self.client
    }

    pub fn enroll_consumer<F>(
        &self,
        consumer_id: String,
        callback: F,
    ) -> Result<EnrolledSecretConsumer<F>, SecretLeaseError> {
        if !crate::https_consumer::component(&consumer_id) {
            return Err(SecretLeaseError::InvalidRequest);
        }
        Ok(EnrolledSecretConsumer {
            consumer_id,
            callback,
        })
    }

    pub fn issue_binding(
        &self,
        request: &SecretLeaseRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_issue_request(request)?;
        let payload = Zeroizing::new(
            serde_json::to_vec(&(
                "hepta.bao.dynamic.issue.payload.v1",
                request.method,
                &request.mount,
                &request.path,
                &request.parameters,
            ))
            .map_err(|_| SecretLeaseError::InvalidRequest)?,
        );
        self.operation_binding(
            "hepta.bao.dynamic.issue.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &format!("{}/{}", request.mount, request.path),
            &request.operation_id,
            Digest32::of_bytes(&payload).into_array(),
        )
    }

    pub fn renew_binding(
        &self,
        request: &RenewSecretLeaseRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.lease_id,
        )?;
        if request.increment_seconds > MAX_RENEW_INCREMENT_SECONDS {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let metadata = self.registry.metadata_by_lease(&request.lease_id).map_err(map_store_error)?;
        if metadata.consumer_id != request.consumer_id {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let payload = serde_json::to_vec(&(
            "hepta.bao.lease.renew.payload.v1",
            &request.lease_id,
            request.increment_seconds,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        self.operation_binding(
            "hepta.bao.lease.renew.v1",
            &request.subject_id,
            &request.consumer_id,
            &metadata.namespace,
            &metadata.provider_path,
            &request.operation_id,
            Digest32::of_bytes(&payload).into_array(),
        )
    }

    pub fn revoke_binding(
        &self,
        request: &RevokeSecretLeaseRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.lease_id,
        )?;
        let metadata = self.registry.metadata_by_lease(&request.lease_id).map_err(map_store_error)?;
        if metadata.consumer_id != request.consumer_id {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let payload = serde_json::to_vec(&("hepta.bao.lease.revoke.payload.v1", &request.lease_id))
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        self.operation_binding(
            "hepta.bao.lease.revoke.v1",
            &request.subject_id,
            &request.consumer_id,
            &metadata.namespace,
            &metadata.provider_path,
            &request.operation_id,
            Digest32::of_bytes(&payload).into_array(),
        )
    }

    pub fn reconcile_binding(
        &self,
        request: &ReconcileSecretLeaseRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.lease_id,
        )?;
        let metadata = self.registry.metadata_by_lease(&request.lease_id).map_err(map_store_error)?;
        if metadata.consumer_id != request.consumer_id {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let payload = serde_json::to_vec(&("hepta.bao.lease.lookup.payload.v1", &request.lease_id))
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        self.operation_binding(
            "hepta.bao.lease.lookup.v1",
            &request.subject_id,
            &request.consumer_id,
            &metadata.namespace,
            &metadata.provider_path,
            &request.operation_id,
            Digest32::of_bytes(&payload).into_array(),
        )
    }

    pub fn reconcile_issue_binding(
        &self,
        request: &ReconcileIndeterminateIssueRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.observed_provider_lease_id,
        )?;
        if !crate::https_consumer::component(&request.issue_operation_id) {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let metadata = self
            .registry
            .metadata_by_operation(&request.issue_operation_id)
            .map_err(map_store_error)?;
        if metadata.state != SecretLeaseState::IndeterminateIssue
            || metadata.consumer_id != request.consumer_id
        {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let payload = serde_json::to_vec(&(
            "hepta.bao.lease.issue-reconcile.payload.v1",
            &request.issue_operation_id,
            &request.observed_provider_lease_id,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        self.operation_binding(
            "hepta.bao.lease.issue-reconcile.v1",
            &request.subject_id,
            &request.consumer_id,
            &metadata.namespace,
            &metadata.provider_path,
            &request.operation_id,
            Digest32::of_bytes(&payload).into_array(),
        )
    }

    pub async fn request_secret_lease<F>(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &SecretLeaseRequest,
        consumer: EnrolledSecretConsumer<F>,
    ) -> Result<SecretLeaseReceipt, SecretLeaseError>
    where
        F: FnOnce(&SecretLeaseView<'_>) -> Result<(), ()>,
    {
        let binding = self.issue_binding(request)?;
        if consumer.consumer_id != request.consumer_id {
            return Err(SecretLeaseError::ConsumerIdentityMismatch);
        }
        let metadata = SecretLeaseMetadata {
            operation_id: request.operation_id.clone(),
            lease_id: None,
            provider_path: format!("{}/{}", request.mount, request.path),
            namespace: request.namespace.clone(),
            consumer_id: request.consumer_id.clone(),
            destination_id: self.client.destination_id().to_owned(),
            scope_sha256: binding.scope_sha256,
            expires_at_unix_ms: None,
            renewable: false,
            generation: 0,
            state: SecretLeaseState::IssuePending,
        };
        self.registry
            .begin_issue(metadata, binding.request_sha256)
            .map_err(map_store_error)?;

        let verified = match authority.claim(grant, &binding) {
            Ok(token) => token,
            Err(error) => {
                self.registry
                    .reject_issue(&request.operation_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::Authority(error));
            }
        };

        let url = self.dynamic_url(&request.mount, &request.path)?;
        let mut network_request = match request.method {
            BaoDynamicMethod::Get => self.client.client.get(url),
            BaoDynamicMethod::Post => self.client.client.post(url).json(&request.parameters),
        };
        network_request = self.with_auth_headers(network_request, &request.namespace)?;
        let mut response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                self.mark_issue_indeterminate(&request.operation_id)?;
                return Err(indeterminate_issue_error(
                    &request.operation_id,
                    map_transport_error(error),
                ));
            }
        };
        match response.status() {
            StatusCode::OK | StatusCode::CREATED => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                self.registry
                    .reject_issue(&request.operation_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => {
                self.registry
                    .reject_issue(&request.operation_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderNotFound);
            }
            status if status.is_client_error() => {
                self.registry
                    .reject_issue(&request.operation_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderRejected);
            }
            _ => {
                self.mark_issue_indeterminate(&request.operation_id)?;
                return Err(indeterminate_issue_error(
                    &request.operation_id,
                    SecretLeaseError::ProviderUnavailable,
                ));
            }
        }

        let body = match read_bounded_body(&mut response).await {
            Ok(body) => body,
            Err(error) => {
                self.mark_issue_indeterminate(&request.operation_id)?;
                return Err(indeterminate_issue_error(&request.operation_id, error));
            }
        };
        let decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                self.mark_issue_indeterminate(&request.operation_id)?;
                return Err(indeterminate_issue_error(
                    &request.operation_id,
                    SecretLeaseError::InvalidResponse,
                ));
            }
        };
        let lease_id = decoded.lease_id.to_string();
        if !valid_lease_id(&lease_id) || decoded.lease_duration == 0 {
            self.mark_issue_indeterminate(&request.operation_id)?;
            return Err(indeterminate_issue_error(
                &request.operation_id,
                SecretLeaseError::InvalidResponse,
            ));
        }
        let (field_count, secret_bytes) = validate_dynamic_fields(&decoded.data).map_err(|error| {
            let _ = self.mark_issue_indeterminate(&request.operation_id);
            error
        })?;
        let expires_at_unix_ms = expiry_from_seconds(decoded.lease_duration)?;
        let metadata = self
            .registry
            .commit_issue(
                &request.operation_id,
                lease_id.clone(),
                expires_at_unix_ms,
                decoded.renewable,
            )
            .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                operation_id: request.operation_id.clone(),
                lease_id: Some(lease_id),
            })?;

        let view = SecretLeaseView {
            fields: &decoded.data,
        };
        authority
            .with_verified_use(verified, &binding, || (consumer.callback)(&view))
            .map_err(SecretLeaseError::Authority)?
            .map_err(|()| SecretLeaseError::ConsumerIndeterminate)?;
        Ok(SecretLeaseReceipt {
            request_sha256: binding.request_sha256,
            metadata,
            field_count,
            secret_bytes,
            contains_raw_secret: false,
        })
    }

    pub async fn renew_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &RenewSecretLeaseRequest,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        let binding = self.renew_binding(request)?;
        let metadata = self
            .registry
            .begin_renew(&request.lease_id, &request.operation_id, binding.request_sha256)
            .map_err(map_store_error)?;
        if let Err(error) = authority.claim(grant, &binding) {
            self.registry
                .restore_after_definite_failure(&request.lease_id)
                .map_err(map_store_error)?;
            return Err(SecretLeaseError::Authority(error));
        }
        let body = RenewPayload {
            lease_id: &request.lease_id,
            increment: request.increment_seconds,
        };
        let url = self.system_url(&["leases", "renew"])?;
        let network_request = self.with_auth_headers(
            self.client.client.post(url).json(&body),
            &metadata.namespace,
        )?;
        let mut response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                self.mark_renew_indeterminate(&request.lease_id)?;
                return Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    map_transport_error(error),
                ));
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::NOT_FOUND => {
                self.registry
                    .commit_revoked(&request.lease_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderNotFound);
            }
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                self.registry
                    .restore_after_definite_failure(&request.lease_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderDenied);
            }
            status if status.is_client_error() => {
                self.registry
                    .restore_after_definite_failure(&request.lease_id)
                    .map_err(map_store_error)?;
                return Err(SecretLeaseError::ProviderRejected);
            }
            _ => {
                self.mark_renew_indeterminate(&request.lease_id)?;
                return Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    SecretLeaseError::ProviderUnavailable,
                ));
            }
        }
        let response_body = match read_bounded_body(&mut response).await {
            Ok(body) => body,
            Err(error) => {
                self.mark_renew_indeterminate(&request.lease_id)?;
                return Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    error,
                ));
            }
        };
        let decoded: LeaseMutationResponse = match serde_json::from_slice(&response_body) {
            Ok(decoded) => decoded,
            Err(_) => {
                self.mark_renew_indeterminate(&request.lease_id)?;
                return Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    SecretLeaseError::InvalidResponse,
                ));
            }
        };
        if decoded.lease_id.as_str() != request.lease_id || decoded.lease_duration == 0 {
            self.mark_renew_indeterminate(&request.lease_id)?;
            return Err(indeterminate_mutation_error(
                &request.operation_id,
                &request.lease_id,
                SecretLeaseError::InvalidResponse,
            ));
        }
        let expires = expiry_from_seconds(decoded.lease_duration)?;
        self.registry
            .commit_renew(&request.lease_id, expires, decoded.renewable)
            .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                operation_id: request.operation_id.clone(),
                lease_id: Some(request.lease_id.clone()),
            })
    }

    pub async fn revoke_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &RevokeSecretLeaseRequest,
    ) -> Result<RevocationObservation, SecretLeaseError> {
        let binding = self.revoke_binding(request)?;
        let metadata = self
            .registry
            .begin_revoke(&request.lease_id, &request.operation_id, binding.request_sha256)
            .map_err(map_store_error)?;
        if let Err(error) = authority.claim(grant, &binding) {
            self.registry
                .restore_after_definite_failure(&request.lease_id)
                .map_err(map_store_error)?;
            return Err(SecretLeaseError::Authority(error));
        }
        let body = RevokePayload {
            lease_id: &request.lease_id,
            sync: true,
        };
        let url = self.system_url(&["leases", "revoke"])?;
        let network_request = self.with_auth_headers(
            self.client.client.post(url).json(&body),
            &metadata.namespace,
        )?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                self.mark_revoke_indeterminate(&request.lease_id)?;
                return Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    map_transport_error(error),
                ));
            }
        };
        match response.status() {
            StatusCode::OK | StatusCode::NO_CONTENT => {
                let metadata = self
                    .registry
                    .commit_revoked(&request.lease_id)
                    .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                        operation_id: request.operation_id.clone(),
                        lease_id: Some(request.lease_id.clone()),
                    })?;
                Ok(RevocationObservation {
                    metadata,
                    provider_already_missing: false,
                })
            }
            StatusCode::NOT_FOUND => {
                let metadata = self
                    .registry
                    .commit_revoked(&request.lease_id)
                    .map_err(map_store_error)?;
                Ok(RevocationObservation {
                    metadata,
                    provider_already_missing: true,
                })
            }
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                self.registry
                    .restore_after_definite_failure(&request.lease_id)
                    .map_err(map_store_error)?;
                Err(SecretLeaseError::ProviderDenied)
            }
            status if status.is_client_error() => {
                self.registry
                    .restore_after_definite_failure(&request.lease_id)
                    .map_err(map_store_error)?;
                Err(SecretLeaseError::ProviderRejected)
            }
            _ => {
                self.mark_revoke_indeterminate(&request.lease_id)?;
                Err(indeterminate_mutation_error(
                    &request.operation_id,
                    &request.lease_id,
                    SecretLeaseError::ProviderUnavailable,
                ))
            }
        }
    }

    pub async fn reconcile_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &ReconcileSecretLeaseRequest,
    ) -> Result<ReconciliationObservation, SecretLeaseError> {
        let binding = self.reconcile_binding(request)?;
        let metadata = self.registry.metadata_by_lease(&request.lease_id).map_err(map_store_error)?;
        authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        match self.lookup_provider_lease(&metadata.namespace, &request.lease_id).await? {
            Some(observed) => {
                let metadata = self
                    .registry
                    .reconcile_present(
                        &request.lease_id,
                        expiry_from_seconds(observed.ttl)?,
                        observed.renewable,
                    )
                    .map_err(map_store_error)?;
                Ok(ReconciliationObservation {
                    metadata,
                    provider_present: true,
                })
            }
            None => {
                let metadata = self
                    .registry
                    .commit_revoked(&request.lease_id)
                    .map_err(map_store_error)?;
                Ok(ReconciliationObservation {
                    metadata,
                    provider_present: false,
                })
            }
        }
    }

    pub async fn reconcile_indeterminate_issue(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &ReconcileIndeterminateIssueRequest,
    ) -> Result<ReconciliationObservation, SecretLeaseError> {
        let binding = self.reconcile_issue_binding(request)?;
        let pending = self
            .registry
            .metadata_by_operation(&request.issue_operation_id)
            .map_err(map_store_error)?;
        authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        let Some(observed) = self
            .lookup_provider_lease(&pending.namespace, &request.observed_provider_lease_id)
            .await?
        else {
            // OpenBao has no generic idempotency/operation-key lookup for
            // arbitrary dynamic-secret issuance. Absence of one candidate ID
            // cannot prove no credential was created, so remain indeterminate.
            return Err(SecretLeaseError::IssueStillIndeterminate);
        };
        let metadata = self
            .registry
            .commit_orphaned_issue(
                &request.issue_operation_id,
                request.observed_provider_lease_id.clone(),
                expiry_from_seconds(observed.ttl)?,
                observed.renewable,
            )
            .map_err(map_store_error)?;
        Ok(ReconciliationObservation {
            metadata,
            provider_present: true,
        })
    }

    pub fn metadata_by_operation(
        &self,
        operation_id: &str,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.registry
            .metadata_by_operation(operation_id)
            .map_err(map_store_error)
    }

    pub fn metadata_by_lease(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.registry.metadata_by_lease(lease_id).map_err(map_store_error)
    }

    fn operation_binding(
        &self,
        domain: &str,
        subject_id: &str,
        consumer_id: &str,
        namespace: &str,
        provider_path: &str,
        operation_id: &str,
        payload_sha256: [u8; 32],
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        if !crate::https_consumer::component(subject_id)
            || !crate::https_consumer::component(consumer_id)
            || !crate::https_consumer::component(operation_id)
            || (!namespace.is_empty() && !crate::https_consumer::segmented(namespace))
            || !crate::https_consumer::segmented(provider_path)
            || payload_sha256 == [0; 32]
        {
            return Err(SecretLeaseError::InvalidRequest);
        }
        let request_bytes = serde_json::to_vec(&(
            domain,
            self.client.origin.as_str(),
            self.client.ca_sha256,
            self.client.destination_id(),
            subject_id,
            consumer_id,
            namespace,
            provider_path,
            operation_id,
            payload_sha256,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        let scope_bytes = serde_json::to_vec(&(
            "hepta.bao.lease.scope.v1",
            self.client.origin.as_str(),
            self.client.destination_id(),
            namespace,
            provider_path,
            consumer_id,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: subject_id.to_owned(),
            destination_id: self.client.destination_id().to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: Digest32::of_bytes(&scope_bytes).into_array(),
            payload_sha256,
        })
    }

    fn dynamic_url(&self, mount: &str, path: &str) -> Result<url::Url, SecretLeaseError> {
        let mut url = self.client.origin.clone();
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        parts.clear().push("v1");
        for part in mount.split('/') {
            parts.push(part);
        }
        for part in path.split('/') {
            parts.push(part);
        }
        drop(parts);
        Ok(url)
    }

    fn system_url(&self, path: &[&str]) -> Result<url::Url, SecretLeaseError> {
        let mut url = self.client.origin.clone();
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        parts.clear().push("v1").push("sys");
        for part in path {
            parts.push(part);
        }
        drop(parts);
        Ok(url)
    }

    fn with_auth_headers(
        &self,
        mut request: codex_http_client::RequestBuilder,
        namespace: &str,
    ) -> Result<codex_http_client::RequestBuilder, SecretLeaseError> {
        let mut token = HeaderValue::from_str(&self.client.token.0)
            .map_err(|_| SecretLeaseError::InvalidConfiguration)?;
        token.set_sensitive(true);
        request = request
            .header("X-Vault-Token", token)
            .header("Accept", "application/json");
        if !namespace.is_empty() {
            request = request.header("X-Vault-Namespace", namespace);
        }
        Ok(request)
    }

    async fn lookup_provider_lease(
        &self,
        namespace: &str,
        lease_id: &str,
    ) -> Result<Option<LookupLeaseData>, SecretLeaseError> {
        let url = self.system_url(&["leases", "lookup"])?;
        let payload = LookupPayload { lease_id };
        let request = self.with_auth_headers(self.client.client.post(url).json(&payload), namespace)?;
        let mut response = request.send().await.map_err(map_transport_error)?;
        match response.status() {
            StatusCode::OK => {}
            StatusCode::NOT_FOUND => return Ok(None),
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(SecretLeaseError::ProviderDenied);
            }
            status if status.is_client_error() => return Err(SecretLeaseError::ProviderRejected),
            _ => return Err(SecretLeaseError::ProviderUnavailable),
        }
        let body = read_bounded_body(&mut response).await?;
        let decoded: LookupLeaseResponse =
            serde_json::from_slice(&body).map_err(|_| SecretLeaseError::InvalidResponse)?;
        if decoded.data.id.as_str() != lease_id || decoded.data.ttl == 0 {
            return Err(SecretLeaseError::InvalidResponse);
        }
        Ok(Some(decoded.data))
    }

    fn mark_issue_indeterminate(&self, operation_id: &str) -> Result<(), SecretLeaseError> {
        self.registry
            .mark_issue_indeterminate(operation_id)
            .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                operation_id: operation_id.to_owned(),
                lease_id: None,
            })
    }

    fn mark_renew_indeterminate(&self, lease_id: &str) -> Result<(), SecretLeaseError> {
        self.registry
            .mark_renew_indeterminate(lease_id)
            .map(|_| ())
            .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                operation_id: "renew".to_owned(),
                lease_id: Some(lease_id.to_owned()),
            })
    }

    fn mark_revoke_indeterminate(&self, lease_id: &str) -> Result<(), SecretLeaseError> {
        self.registry
            .mark_revoke_indeterminate(lease_id)
            .map(|_| ())
            .map_err(|_| SecretLeaseError::StatePersistenceIndeterminate {
                operation_id: "revoke".to_owned(),
                lease_id: Some(lease_id.to_owned()),
            })
    }
}

#[derive(Deserialize)]
struct DynamicLeaseResponse {
    #[serde(default)]
    _request_id: Option<IgnoredAny>,
    lease_id: Zeroizing<String>,
    renewable: bool,
    lease_duration: u64,
    data: BTreeMap<String, Zeroizing<String>>,
    #[serde(default)]
    _auth: Option<IgnoredAny>,
    #[serde(default)]
    _wrap_info: Option<IgnoredAny>,
    #[serde(default)]
    _warnings: Option<IgnoredAny>,
}

#[derive(Deserialize)]
struct LeaseMutationResponse {
    lease_id: Zeroizing<String>,
    renewable: bool,
    lease_duration: u64,
}

#[derive(Deserialize)]
struct LookupLeaseResponse {
    data: LookupLeaseData,
}

#[derive(Deserialize)]
struct LookupLeaseData {
    id: Zeroizing<String>,
    renewable: bool,
    ttl: u64,
}

#[derive(Serialize)]
struct RenewPayload<'a> {
    lease_id: &'a str,
    increment: u64,
}

#[derive(Serialize)]
struct RevokePayload<'a> {
    lease_id: &'a str,
    sync: bool,
}

#[derive(Serialize)]
struct LookupPayload<'a> {
    lease_id: &'a str,
}

async fn read_bounded_body(response: &mut HttpResponse) -> Result<Zeroizing<Vec<u8>>, SecretLeaseError> {
    if response
        .content_length()
        .is_some_and(|length| length > crate::https_consumer::MAX_RESPONSE_BYTES as u64)
    {
        return Err(SecretLeaseError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(map_transport_error)? {
        if chunk.len() > crate::https_consumer::MAX_RESPONSE_BYTES - body.len() {
            return Err(SecretLeaseError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn validate_issue_request(request: &SecretLeaseRequest) -> Result<(), SecretLeaseError> {
    if !crate::https_consumer::component(&request.subject_id)
        || !crate::https_consumer::component(&request.consumer_id)
        || !crate::https_consumer::component(&request.operation_id)
        || (!request.namespace.is_empty() && !crate::https_consumer::segmented(&request.namespace))
        || !crate::https_consumer::segmented(&request.mount)
        || !crate::https_consumer::segmented(&request.path)
        || reserved_mount(&request.mount)
        || request.parameters.len() > MAX_DYNAMIC_FIELDS
        || matches!(request.method, BaoDynamicMethod::Get) && !request.parameters.is_empty()
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    let bytes = Zeroizing::new(
        serde_json::to_vec(&request.parameters).map_err(|_| SecretLeaseError::InvalidRequest)?,
    );
    if bytes.len() > MAX_REQUEST_METADATA_BYTES
        || request.parameters.iter().any(|(key, value)| {
            !crate::https_consumer::component(key) || value.len() > MAX_DYNAMIC_FIELD_BYTES
        })
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_mutation_request(
    subject_id: &str,
    consumer_id: &str,
    operation_id: &str,
    lease_id: &str,
) -> Result<(), SecretLeaseError> {
    if !crate::https_consumer::component(subject_id)
        || !crate::https_consumer::component(consumer_id)
        || !crate::https_consumer::component(operation_id)
        || !valid_lease_id(lease_id)
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn reserved_mount(mount: &str) -> bool {
    matches!(mount.split('/').next(), Some("sys" | "auth" | "identity" | "cubbyhole"))
}

fn valid_lease_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_LEASE_ID_BYTES
        && value.bytes().all(|byte| !byte.is_ascii_control())
}

fn validate_dynamic_fields(
    fields: &BTreeMap<String, Zeroizing<String>>,
) -> Result<(usize, usize), SecretLeaseError> {
    if fields.is_empty() || fields.len() > MAX_DYNAMIC_FIELDS {
        return Err(SecretLeaseError::InvalidResponse);
    }
    let mut total = 0_usize;
    for (key, value) in fields {
        if !crate::https_consumer::component(key) || value.len() > MAX_DYNAMIC_FIELD_BYTES {
            return Err(SecretLeaseError::InvalidResponse);
        }
        total = total
            .checked_add(value.len())
            .ok_or(SecretLeaseError::ResponseTooLarge)?;
        if total > MAX_DYNAMIC_SECRET_BYTES {
            return Err(SecretLeaseError::ResponseTooLarge);
        }
    }
    Ok((fields.len(), total))
}

fn expiry_from_seconds(seconds: u64) -> Result<u64, SecretLeaseError> {
    if seconds == 0 {
        return Err(SecretLeaseError::InvalidResponse);
    }
    let delta = seconds
        .checked_mul(1000)
        .ok_or(SecretLeaseError::InvalidResponse)?;
    now_ms()?
        .checked_add(delta)
        .ok_or(SecretLeaseError::InvalidResponse)
}

fn now_ms() -> Result<u64, SecretLeaseError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SecretLeaseError::StateUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| SecretLeaseError::StateUnavailable)
}

fn map_transport_error(error: HttpError) -> SecretLeaseError {
    if error.is_timeout() {
        SecretLeaseError::TimedOut
    } else {
        SecretLeaseError::TransportUnavailable
    }
}

fn map_store_error(error: StoreError) -> SecretLeaseError {
    match error {
        StoreError::Invalid => SecretLeaseError::InvalidState,
        StoreError::UnsafeDirectory => SecretLeaseError::UnsafeStateDirectory,
        StoreError::Locked => SecretLeaseError::StateLocked,
        StoreError::Unavailable => SecretLeaseError::StateUnavailable,
        StoreError::OperationConflict => SecretLeaseError::OperationConflict,
        StoreError::AlreadyCompleted => SecretLeaseError::OperationAlreadyCompleted,
        StoreError::ReconciliationRequired => SecretLeaseError::ReconciliationRequired,
        StoreError::LeaseNotFound => SecretLeaseError::LeaseNotFound,
        StoreError::LeaseNotActive => SecretLeaseError::LeaseNotActive,
        StoreError::LeaseNotRenewable => SecretLeaseError::LeaseNotRenewable,
    }
}

fn indeterminate_issue_error(operation_id: &str, source: SecretLeaseError) -> SecretLeaseError {
    SecretLeaseError::ProviderEffectIndeterminate {
        operation_id: operation_id.to_owned(),
        lease_id: None,
        cause: source.indeterminate_cause(),
    }
}

fn indeterminate_mutation_error(
    operation_id: &str,
    lease_id: &str,
    source: SecretLeaseError,
) -> SecretLeaseError {
    SecretLeaseError::ProviderEffectIndeterminate {
        operation_id: operation_id.to_owned(),
        lease_id: Some(lease_id.to_owned()),
        cause: source.indeterminate_cause(),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IndeterminateCause {
    Timeout,
    Transport,
    ProviderUnavailable,
    InvalidResponse,
    OversizedResponse,
    Other,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecretLeaseError {
    InvalidConfiguration,
    InvalidRequest,
    ConsumerIdentityMismatch,
    Authority(FinalUseError),
    ProviderDenied,
    ProviderRejected,
    ProviderUnavailable,
    ProviderNotFound,
    TransportUnavailable,
    TimedOut,
    ResponseTooLarge,
    InvalidResponse,
    InvalidState,
    UnsafeStateDirectory,
    StateLocked,
    StateUnavailable,
    OperationConflict,
    OperationAlreadyCompleted,
    ReconciliationRequired,
    LeaseNotFound,
    LeaseNotActive,
    LeaseNotRenewable,
    ConsumerIndeterminate,
    IssueStillIndeterminate,
    ProviderEffectIndeterminate {
        operation_id: String,
        lease_id: Option<String>,
        cause: IndeterminateCause,
    },
    StatePersistenceIndeterminate {
        operation_id: String,
        lease_id: Option<String>,
    },
}

impl SecretLeaseError {
    fn indeterminate_cause(&self) -> IndeterminateCause {
        match self {
            Self::TimedOut => IndeterminateCause::Timeout,
            Self::TransportUnavailable => IndeterminateCause::Transport,
            Self::ProviderUnavailable => IndeterminateCause::ProviderUnavailable,
            Self::InvalidResponse => IndeterminateCause::InvalidResponse,
            Self::ResponseTooLarge => IndeterminateCause::OversizedResponse,
            _ => IndeterminateCause::Other,
        }
    }
}

impl fmt::Display for SecretLeaseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for SecretLeaseError {}

impl From<BaoClientError> for SecretLeaseError {
    fn from(value: BaoClientError) -> Self {
        match value {
            BaoClientError::InvalidConfiguration => Self::InvalidConfiguration,
            BaoClientError::InvalidRequest => Self::InvalidRequest,
            BaoClientError::Authority(error) => Self::Authority(error),
            BaoClientError::ProviderDenied => Self::ProviderDenied,
            BaoClientError::ProviderUnavailable => Self::ProviderUnavailable,
            BaoClientError::NotFound => Self::ProviderNotFound,
            BaoClientError::TransportUnavailable => Self::TransportUnavailable,
            BaoClientError::TimedOut => Self::TimedOut,
            BaoClientError::ResponseTooLarge => Self::ResponseTooLarge,
            BaoClientError::InvalidResponse => Self::InvalidResponse,
            BaoClientError::VersionMismatch | BaoClientError::SecretDigestMismatch => {
                Self::InvalidResponse
            }
            BaoClientError::ConsumerIndeterminate => Self::ConsumerIndeterminate,
        }
    }
}

#[cfg(all(test, unix))]
#[path = "lease_tests.rs"]
mod tests;
