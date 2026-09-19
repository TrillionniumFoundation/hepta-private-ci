//! Provider-native SecretLease issue/renew/revoke client.
//!
//! Every effect has a durable local operation identity before dispatch.
//! Once dispatch is attempted, timeout/transport/ambiguous provider outcomes
//! are persisted as Unknown and are never converted into a blind retry.

use std::collections::BTreeMap;
use std::fmt;

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
use zeroize::Zeroizing;

use crate::BaoClient;
use crate::LeaseMetadata;
use crate::LeaseOperationKind;
use crate::LeaseOperationState;
use crate::LeaseRegistry;
use crate::LeaseRegistryError;
use crate::LeaseState;
use crate::OperationAdmission;

const MAX_LEASE_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_DYNAMIC_FIELDS: usize = 64;
const MAX_DYNAMIC_FIELD_BYTES: usize = 64 * 1024;
const MAX_LEASE_SECONDS: u64 = 31 * 24 * 60 * 60;
const OPERATION_HEADER: &str = "X-Hepta-Operation-Id";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseIssueRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub operation_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRenewRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub operation_id: String,
    pub lease_id: String,
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRevokeRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub operation_id: String,
    pub lease_id: String,
}

#[derive(Eq, PartialEq)]
pub struct DynamicSecretFields {
    fields: BTreeMap<String, Zeroizing<String>>,
}

impl DynamicSecretFields {
    pub fn get(&self, name: &str) -> Option<&str> {
        self.fields.get(name).map(|value| value.as_str())
    }

    pub fn len(&self) -> usize {
        self.fields.len()
    }

    pub fn is_empty(&self) -> bool {
        self.fields.is_empty()
    }
}

impl fmt::Debug for DynamicSecretFields {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DynamicSecretFields")
            .field("field_count", &self.fields.len())
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseIssueReceipt {
    pub operation_id: String,
    /// Provider lease identity. This is recovery metadata, not a secret value,
    /// but callers must keep it out of general logs and model-visible context.
    pub lease_id: String,
    pub request_sha256: [u8; 32],
    pub scope_sha256: [u8; 32],
    pub renewable: bool,
    pub expires_at_ms: u64,
    pub secret_field_count: usize,
}

/// Issuance can succeed at the provider even when final secret delivery is
/// fenced or indeterminate. Preserve the known provider lease identity so the
/// trusted host can revoke/reconcile it instead of minting a replacement.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecretLeaseIssueOutcome {
    Delivered(SecretLeaseIssueReceipt),
    DeliveryBlocked {
        receipt: SecretLeaseIssueReceipt,
        authority_error: FinalUseError,
    },
    ConsumerIndeterminate {
        receipt: SecretLeaseIssueReceipt,
    },
    RegistryBlocked {
        receipt: SecretLeaseIssueReceipt,
        registry_error: LeaseRegistryError,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseMutationReceipt {
    pub operation_id: String,
    pub lease_id: String,
    pub request_sha256: [u8; 32],
    pub response_sha256: Option<[u8; 32]>,
    pub state: LeaseState,
    pub expires_at_ms: Option<u64>,
}

impl BaoClient {
    pub async fn request_secret_lease(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseIssueRequest,
        now_ms: u64,
        consumer: impl FnOnce(&DynamicSecretFields) -> Result<(), ()>,
    ) -> Result<SecretLeaseIssueOutcome, SecretLeaseClientError> {
        validate_issue(request)?;
        let binding = self.issue_binding(request)?;
        match registry
            .begin_operation(
                &request.operation_id,
                LeaseOperationKind::Issue,
                None,
                binding.request_sha256,
                now_ms,
            )
            .await?
        {
            OperationAdmission::New => {}
            OperationAdmission::Existing(record) => {
                return Err(existing_operation_error(record.state));
            }
        }

        let url = provider_url(&self.origin, &request.mount, &request.path)?;
        let mut token = provider_token_header(&self.token.0)?;
        token.set_sensitive(true);
        let mut network_request = self
            .client
            .get(url)
            .header("X-Vault-Token", token)
            .header(OPERATION_HEADER, &request.operation_id)
            .header("Accept", "application/json");
        if !request.namespace.is_empty() {
            network_request = network_request.header("X-Vault-Namespace", &request.namespace);
        }

        registry
            .mark_in_flight(&request.operation_id, now_ms)
            .await?;
        let verified = match authority.claim(grant, &binding) {
            Ok(value) => value,
            Err(error) => {
                registry
                    .reject_operation(&request.operation_id, now_ms)
                    .await?;
                return Err(SecretLeaseClientError::Authority(error));
            }
        };
        let response = match network_request.send().await {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(ambiguous_transport(error));
            }
        };
        let status = response.status();
        if matches!(
            status,
            StatusCode::BAD_REQUEST
                | StatusCode::UNAUTHORIZED
                | StatusCode::FORBIDDEN
                | StatusCode::NOT_FOUND
        ) {
            registry
                .reject_operation(&request.operation_id, now_ms)
                .await?;
            return Err(provider_rejection(status));
        }
        if status != StatusCode::OK {
            registry.mark_unknown(&request.operation_id, now_ms).await?;
            return Err(SecretLeaseClientError::NeedsReconciliation);
        }

        let body = match bounded_body(response).await {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(error);
            }
        };
        let decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(value) => value,
            Err(_) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(SecretLeaseClientError::InvalidResponse);
            }
        };
        if validate_dynamic_response(&decoded).is_err() {
            registry.mark_unknown(&request.operation_id, now_ms).await?;
            return Err(SecretLeaseClientError::InvalidResponse);
        }
        let expires_at_ms = match expiry_from_duration(now_ms, decoded.lease_duration) {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(error);
            }
        };
        let fields = DynamicSecretFields {
            fields: decoded.data,
        };
        let metadata = LeaseMetadata {
            lease_id: decoded.lease_id.clone(),
            provider_path: format!("{}/{}", request.mount, request.path),
            consumer_id: request.consumer_id.clone(),
            scope_sha256: binding.scope_sha256,
            renewable: decoded.renewable,
            expires_at_ms,
            state: LeaseState::Active,
            revision: 1,
        };
        let receipt = SecretLeaseIssueReceipt {
            operation_id: request.operation_id.clone(),
            lease_id: metadata.lease_id.clone(),
            request_sha256: binding.request_sha256,
            scope_sha256: binding.scope_sha256,
            renewable: metadata.renewable,
            expires_at_ms,
            secret_field_count: fields.len(),
        };
        if let Err(registry_error) = registry
            .commit_issue(&request.operation_id, &metadata, now_ms)
            .await
        {
            // The provider already returned a concrete lease identity. Never
            // erase that fact behind a generic store error: the host needs the
            // identity to revoke/reconcile the credential.
            return Ok(SecretLeaseIssueOutcome::RegistryBlocked {
                receipt,
                registry_error,
            });
        }

        match authority.with_verified_use(verified, &binding, || consumer(&fields)) {
            Ok(Ok(())) => Ok(SecretLeaseIssueOutcome::Delivered(receipt)),
            Ok(Err(())) => {
                let _ = registry.mark_lease_unknown(&metadata.lease_id, now_ms).await;
                Ok(SecretLeaseIssueOutcome::ConsumerIndeterminate { receipt })
            }
            Err(authority_error) => {
                let _ = registry.mark_lease_unknown(&metadata.lease_id, now_ms).await;
                Ok(SecretLeaseIssueOutcome::DeliveryBlocked {
                    receipt,
                    authority_error,
                })
            }
        }
    }

    pub async fn renew_secret_lease(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRenewRequest,
        now_ms: u64,
    ) -> Result<SecretLeaseMutationReceipt, SecretLeaseClientError> {
        validate_renew(request)?;
        let binding = self.renew_binding(request)?;
        match registry
            .begin_lease_transition(
                &request.operation_id,
                LeaseOperationKind::Renew,
                &request.lease_id,
                binding.request_sha256,
                now_ms,
            )
            .await?
        {
            OperationAdmission::New => {}
            OperationAdmission::Existing(record) => {
                if record.state == LeaseOperationState::Applied {
                    let lease = registry
                        .get_lease(&request.lease_id, now_ms)
                        .await?
                        .ok_or(SecretLeaseClientError::LeaseNotFound)?;
                    return Ok(SecretLeaseMutationReceipt {
                        operation_id: request.operation_id.clone(),
                        lease_id: request.lease_id.clone(),
                        request_sha256: binding.request_sha256,
                        response_sha256: None,
                        state: lease.state,
                        expires_at_ms: Some(lease.expires_at_ms),
                    });
                }
                return Err(existing_operation_error(record.state));
            }
        }

        let body = serde_json::to_string(&RenewBody {
            lease_id: &request.lease_id,
            increment: request.increment_seconds,
        })
        .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
        let mut token = provider_token_header(&self.token.0)?;
        token.set_sensitive(true);
        let url = provider_url(&self.origin, "sys/leases", "renew")?;
        let mut network_request = self
            .client
            .post(url)
            .header("X-Vault-Token", token)
            .header(OPERATION_HEADER, &request.operation_id)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .body(body);
        if !request.namespace.is_empty() {
            network_request = network_request.header("X-Vault-Namespace", &request.namespace);
        }

        registry
            .mark_in_flight(&request.operation_id, now_ms)
            .await?;
        let _verified = match authority.claim(grant, &binding) {
            Ok(value) => value,
            Err(error) => {
                registry
                    .reject_operation(&request.operation_id, now_ms)
                    .await?;
                return Err(SecretLeaseClientError::Authority(error));
            }
        };
        let response = match network_request.send().await {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(ambiguous_transport(error));
            }
        };
        let status = response.status();
        if matches!(
            status,
            StatusCode::BAD_REQUEST | StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ) {
            registry
                .reject_operation(&request.operation_id, now_ms)
                .await?;
            return Err(provider_rejection(status));
        }
        if status != StatusCode::OK {
            registry.mark_unknown(&request.operation_id, now_ms).await?;
            return Err(SecretLeaseClientError::NeedsReconciliation);
        }
        let response_body = match bounded_body(response).await {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(error);
            }
        };
        let decoded: LeaseMutationResponse = match serde_json::from_slice(&response_body) {
            Ok(value) => value,
            Err(_) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(SecretLeaseClientError::InvalidResponse);
            }
        };
        if decoded.lease_id != request.lease_id || decoded.lease_duration > MAX_LEASE_SECONDS {
            registry.mark_unknown(&request.operation_id, now_ms).await?;
            return Err(SecretLeaseClientError::InvalidResponse);
        }
        let expires_at_ms = match expiry_from_duration(now_ms, decoded.lease_duration) {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(error);
            }
        };
        registry
            .commit_renew(
                &request.operation_id,
                &request.lease_id,
                expires_at_ms,
                decoded.renewable,
                now_ms,
            )
            .await?;
        Ok(SecretLeaseMutationReceipt {
            operation_id: request.operation_id.clone(),
            lease_id: request.lease_id.clone(),
            request_sha256: binding.request_sha256,
            response_sha256: Some(Digest32::of_bytes(&response_body).into_array()),
            state: LeaseState::Active,
            expires_at_ms: Some(expires_at_ms),
        })
    }

    pub async fn revoke_secret_lease(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRevokeRequest,
        now_ms: u64,
    ) -> Result<SecretLeaseMutationReceipt, SecretLeaseClientError> {
        validate_revoke(request)?;
        let binding = self.revoke_binding(request)?;
        match registry
            .begin_lease_transition(
                &request.operation_id,
                LeaseOperationKind::Revoke,
                &request.lease_id,
                binding.request_sha256,
                now_ms,
            )
            .await?
        {
            OperationAdmission::New => {}
            OperationAdmission::Existing(record) => {
                if record.state == LeaseOperationState::Applied {
                    return Ok(SecretLeaseMutationReceipt {
                        operation_id: request.operation_id.clone(),
                        lease_id: request.lease_id.clone(),
                        request_sha256: binding.request_sha256,
                        response_sha256: None,
                        state: LeaseState::Revoked,
                        expires_at_ms: None,
                    });
                }
                return Err(existing_operation_error(record.state));
            }
        }

        let body = serde_json::to_string(&RevokeBody {
            lease_id: &request.lease_id,
            // OpenBao's synchronous revoke contract makes a successful
            // response evidence that provider revocation completed, rather
            // than only that asynchronous revocation was queued.
            sync: true,
        })
        .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
        let mut token = provider_token_header(&self.token.0)?;
        token.set_sensitive(true);
        let url = provider_url(&self.origin, "sys/leases", "revoke")?;
        let mut network_request = self
            .client
            .post(url)
            .header("X-Vault-Token", token)
            .header(OPERATION_HEADER, &request.operation_id)
            .header("Content-Type", "application/json")
            .body(body);
        if !request.namespace.is_empty() {
            network_request = network_request.header("X-Vault-Namespace", &request.namespace);
        }

        registry
            .mark_in_flight(&request.operation_id, now_ms)
            .await?;
        let _verified = match authority.claim(grant, &binding) {
            Ok(value) => value,
            Err(error) => {
                registry
                    .reject_operation(&request.operation_id, now_ms)
                    .await?;
                return Err(SecretLeaseClientError::Authority(error));
            }
        };
        let response = match network_request.send().await {
            Ok(value) => value,
            Err(error) => {
                registry.mark_unknown(&request.operation_id, now_ms).await?;
                return Err(ambiguous_transport(error));
            }
        };
        let status = response.status();
        if matches!(
            status,
            StatusCode::BAD_REQUEST | StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ) {
            registry
                .reject_operation(&request.operation_id, now_ms)
                .await?;
            return Err(provider_rejection(status));
        }
        if !matches!(status, StatusCode::OK | StatusCode::NO_CONTENT) {
            registry.mark_unknown(&request.operation_id, now_ms).await?;
            return Err(SecretLeaseClientError::NeedsReconciliation);
        }
        // Provider terminal status is authoritative for revoke. A malformed or
        // unreadable success body must not turn a confirmed revoke back into an
        // unknown effect.
        let response_sha256 = None;
        registry
            .commit_revoke(&request.operation_id, &request.lease_id, now_ms)
            .await?;
        Ok(SecretLeaseMutationReceipt {
            operation_id: request.operation_id.clone(),
            lease_id: request.lease_id.clone(),
            request_sha256: binding.request_sha256,
            response_sha256,
            state: LeaseState::Revoked,
            expires_at_ms: None,
        })
    }

    /// Reconcile a lost issuance acknowledgement from a host-authenticated
    /// terminal observation. This authorizes the observer; it does not pretend
    /// that arbitrary caller metadata is provider-authenticated evidence.
    pub async fn reconcile_issue_observation(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        observer_subject_id: &str,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease: &LeaseMetadata,
        now_ms: u64,
    ) -> Result<(), SecretLeaseClientError> {
        let operation = registry
            .get_operation(operation_id)
            .await?
            .ok_or(SecretLeaseClientError::OperationNotFound)?;
        if operation.kind != LeaseOperationKind::Issue
            || operation.semantic_sha256 != semantic_sha256
            || operation.state != LeaseOperationState::Unknown
        {
            return Err(SecretLeaseClientError::ReconciliationMismatch);
        }
        let binding = self.reconciliation_binding(
            "issue",
            observer_subject_id,
            operation_id,
            semantic_sha256,
            &lease.lease_id,
            lease.expires_at_ms,
            lease.renewable,
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(SecretLeaseClientError::Authority)?;
        registry.commit_issue(operation_id, lease, now_ms).await?;
        Ok(())
    }

    /// Reconcile an unknown renewal only from a host-authenticated terminal
    /// observation. No provider mutation is replayed.
    pub async fn reconcile_renew_observation(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        observer_subject_id: &str,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease_id: &str,
        expires_at_ms: u64,
        renewable: bool,
        now_ms: u64,
    ) -> Result<(), SecretLeaseClientError> {
        let operation = registry
            .get_operation(operation_id)
            .await?
            .ok_or(SecretLeaseClientError::OperationNotFound)?;
        if operation.kind != LeaseOperationKind::Renew
            || operation.lease_id.as_deref() != Some(lease_id)
            || operation.semantic_sha256 != semantic_sha256
            || operation.state != LeaseOperationState::Unknown
        {
            return Err(SecretLeaseClientError::ReconciliationMismatch);
        }
        let binding = self.reconciliation_binding(
            "renew",
            observer_subject_id,
            operation_id,
            semantic_sha256,
            lease_id,
            expires_at_ms,
            renewable,
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(SecretLeaseClientError::Authority)?;
        registry
            .commit_renew(operation_id, lease_id, expires_at_ms, renewable, now_ms)
            .await?;
        Ok(())
    }

    /// Reconcile an unknown revoke only from a host-authenticated terminal
    /// observation. The observation must establish provider-side absence or
    /// equivalent terminal revocation; this method never replays revoke.
    pub async fn reconcile_revoke_observation(
        &self,
        registry: &LeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        observer_subject_id: &str,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease_id: &str,
        now_ms: u64,
    ) -> Result<(), SecretLeaseClientError> {
        let operation = registry
            .get_operation(operation_id)
            .await?
            .ok_or(SecretLeaseClientError::OperationNotFound)?;
        if operation.kind != LeaseOperationKind::Revoke
            || operation.lease_id.as_deref() != Some(lease_id)
            || operation.semantic_sha256 != semantic_sha256
            || operation.state != LeaseOperationState::Unknown
        {
            return Err(SecretLeaseClientError::ReconciliationMismatch);
        }
        let binding = self.reconciliation_binding(
            "revoke",
            observer_subject_id,
            operation_id,
            semantic_sha256,
            lease_id,
            0,
            false,
        )?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(SecretLeaseClientError::Authority)?;
        registry.commit_revoke(operation_id, lease_id, now_ms).await?;
        Ok(())
    }

    /// Exact proposal that an independent reconciliation authority reviews
    /// before a trusted observer can resolve an Unknown provider effect.
    pub fn reconciliation_binding(
        &self,
        kind: &str,
        observer_subject_id: &str,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease_id: &str,
        expires_at_ms: u64,
        renewable: bool,
    ) -> Result<FinalUseBinding, SecretLeaseClientError> {
        if !matches!(kind, "issue" | "renew" | "revoke")
            || !component(observer_subject_id)
            || !component(operation_id)
            || lease_id.is_empty()
            || lease_id.len() > 512
            || semantic_sha256 == [0; 32]
        {
            return Err(SecretLeaseClientError::InvalidRequest);
        }
        let request = serde_json::to_vec(&(
            "hepta.bao.lease.reconciliation.v1",
            kind,
            self.origin.as_str(),
            self.ca_sha256,
            operation_id,
            semantic_sha256,
            lease_id,
            expires_at_ms,
            renewable,
        ))
        .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.lease.reconciliation-scope.v1",
            self.origin.as_str(),
            observer_subject_id,
            kind,
        ))
        .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: observer_subject_id.to_owned(),
            destination_id: "provider:heptabao:reconciliation".to_owned(),
            request_sha256: Digest32::of_bytes(&request).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: Digest32::of_bytes(&request).into_array(),
        })
    }

    fn issue_binding(
        &self,
        request: &BaoLeaseIssueRequest,
    ) -> Result<FinalUseBinding, SecretLeaseClientError> {
        operation_binding(
            self,
            "hepta.bao.lease.issue.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.mount,
            &request.path,
            &request.operation_id,
            None,
        )
    }

    fn renew_binding(
        &self,
        request: &BaoLeaseRenewRequest,
    ) -> Result<FinalUseBinding, SecretLeaseClientError> {
        operation_binding(
            self,
            "hepta.bao.lease.renew.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "sys/leases",
            "renew",
            &request.operation_id,
            Some((&request.lease_id, request.increment_seconds)),
        )
    }

    fn revoke_binding(
        &self,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<FinalUseBinding, SecretLeaseClientError> {
        operation_binding(
            self,
            "hepta.bao.lease.revoke.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "sys/leases",
            "revoke",
            &request.operation_id,
            Some((&request.lease_id, 0)),
        )
    }
}

fn operation_binding(
    client: &BaoClient,
    schema: &str,
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
    mount: &str,
    path: &str,
    operation_id: &str,
    lease: Option<(&str, u64)>,
) -> Result<FinalUseBinding, SecretLeaseClientError> {
    let request = serde_json::to_vec(&(
        schema,
        client.origin.as_str(),
        client.ca_sha256,
        subject_id,
        consumer_id,
        namespace,
        mount,
        path,
        operation_id,
        lease,
    ))
    .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
    let scope = serde_json::to_vec(&(
        "hepta.bao.lease.scope.v1",
        client.origin.as_str(),
        namespace,
        mount,
        consumer_id,
    ))
    .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
    let payload = serde_json::to_vec(&(
        "hepta.bao.lease.effect.v1",
        operation_id,
        mount,
        path,
        lease,
    ))
    .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id: "provider:heptabao".to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: Digest32::of_bytes(&scope).into_array(),
        payload_sha256: Digest32::of_bytes(&payload).into_array(),
    })
}

fn provider_url(
    origin: &url::Url,
    mount: &str,
    path: &str,
) -> Result<url::Url, SecretLeaseClientError> {
    if !segmented(mount) || !segmented(path) {
        return Err(SecretLeaseClientError::InvalidRequest);
    }
    let mut url = origin.clone();
    let mut parts = url
        .path_segments_mut()
        .map_err(|_| SecretLeaseClientError::InvalidRequest)?;
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

fn validate_issue(request: &BaoLeaseIssueRequest) -> Result<(), SecretLeaseClientError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.mount)
        || !segmented(&request.path)
        || !component(&request.operation_id)
    {
        return Err(SecretLeaseClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_renew(request: &BaoLeaseRenewRequest) -> Result<(), SecretLeaseClientError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !component(&request.operation_id)
        || request.lease_id.is_empty()
        || request.lease_id.len() > 512
        || request.increment_seconds == 0
        || request.increment_seconds > MAX_LEASE_SECONDS
    {
        return Err(SecretLeaseClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_revoke(request: &BaoLeaseRevokeRequest) -> Result<(), SecretLeaseClientError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !component(&request.operation_id)
        || request.lease_id.is_empty()
        || request.lease_id.len() > 512
    {
        return Err(SecretLeaseClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_dynamic_response(
    response: &DynamicLeaseResponse,
) -> Result<(), SecretLeaseClientError> {
    if response.lease_id.is_empty()
        || response.lease_id.len() > 512
        || response.lease_duration == 0
        || response.lease_duration > MAX_LEASE_SECONDS
        || response.data.is_empty()
        || response.data.len() > MAX_DYNAMIC_FIELDS
        || response.data.iter().any(|(key, value)| {
            !component(key) || value.is_empty() || value.len() > MAX_DYNAMIC_FIELD_BYTES
        })
    {
        return Err(SecretLeaseClientError::InvalidResponse);
    }
    Ok(())
}

async fn bounded_body(
    mut response: HttpResponse,
) -> Result<Zeroizing<Vec<u8>>, SecretLeaseClientError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_LEASE_RESPONSE_BYTES as u64)
    {
        return Err(SecretLeaseClientError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| SecretLeaseClientError::NeedsReconciliation)?
    {
        if chunk.len() > MAX_LEASE_RESPONSE_BYTES - body.len() {
            return Err(SecretLeaseClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn provider_token_header(value: &str) -> Result<HeaderValue, SecretLeaseClientError> {
    HeaderValue::from_str(value).map_err(|_| SecretLeaseClientError::InvalidConfiguration)
}

fn expiry_from_duration(now_ms: u64, seconds: u64) -> Result<u64, SecretLeaseClientError> {
    if seconds == 0 || seconds > MAX_LEASE_SECONDS {
        return Err(SecretLeaseClientError::InvalidResponse);
    }
    now_ms
        .checked_add(
            seconds
                .checked_mul(1000)
                .ok_or(SecretLeaseClientError::InvalidResponse)?,
        )
        .ok_or(SecretLeaseClientError::InvalidResponse)
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
    !value.is_empty() && value.len() <= 1024 && value.split('/').all(component)
}

fn existing_operation_error(state: LeaseOperationState) -> SecretLeaseClientError {
    match state {
        LeaseOperationState::Applied => SecretLeaseClientError::OperationAlreadyApplied,
        LeaseOperationState::Rejected => SecretLeaseClientError::OperationRejected,
        LeaseOperationState::Prepared
        | LeaseOperationState::InFlight
        | LeaseOperationState::Unknown => SecretLeaseClientError::NeedsReconciliation,
    }
}

fn ambiguous_transport(error: HttpError) -> SecretLeaseClientError {
    if error.is_timeout() {
        SecretLeaseClientError::TimedOutUnknown
    } else {
        SecretLeaseClientError::TransportUnknown
    }
}

fn provider_rejection(status: StatusCode) -> SecretLeaseClientError {
    match status {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => SecretLeaseClientError::ProviderDenied,
        StatusCode::NOT_FOUND => SecretLeaseClientError::ProviderNotFound,
        _ => SecretLeaseClientError::ProviderRejected,
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
struct LeaseMutationResponse {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseClientError {
    InvalidConfiguration,
    InvalidRequest,
    InvalidResponse,
    ResponseTooLarge,
    Authority(FinalUseError),
    Registry(LeaseRegistryError),
    ProviderDenied,
    ProviderRejected,
    ProviderNotFound,
    LeaseNotFound,
    OperationNotFound,
    OperationAlreadyApplied,
    OperationRejected,
    ReconciliationMismatch,
    NeedsReconciliation,
    TimedOutUnknown,
    TransportUnknown,
}

impl From<LeaseRegistryError> for SecretLeaseClientError {
    fn from(value: LeaseRegistryError) -> Self {
        Self::Registry(value)
    }
}

impl fmt::Display for SecretLeaseClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for SecretLeaseClientError {}
