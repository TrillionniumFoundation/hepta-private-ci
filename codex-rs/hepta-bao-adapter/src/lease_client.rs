//! Provider-native dynamic secret lease lifecycle for OpenBao/HeptaBao.
//!
//! Raw provider credential data is borrowed from a zeroizing response buffer
//! and may enter only the final registered consumer callback. Durable state
//! contains lease metadata, operation state and a keyed fingerprint, never the
//! raw credential payload.

use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::deliver_final_use;
use codex_hepta_types::Digest32;
use codex_http_client::HttpError;
use codex_http_client::HttpResponse;
use hmac::Hmac;
use hmac::Mac;
use http::Method;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use serde_json::value::RawValue;
use sha2::Sha256;
use zeroize::Zeroizing;

use crate::BaoClient;
use crate::lease_store::SECRET_LEASE_SCHEMA_VERSION_V1;
use crate::lease_store::SecretLeaseMetadataV1;
use crate::lease_store::SecretLeaseOperationAdmissionV1;
use crate::lease_store::SecretLeaseOperationKindV1;
use crate::lease_store::SecretLeaseOperationStateV1;
use crate::lease_store::SecretLeaseStateV1;
use crate::lease_store::SecretLeaseStore;
use crate::lease_store::SecretLeaseStoreError;
use crate::lease_store::now_millis;
use crate::lease_store::validate_operation_id;
use crate::lease_store::validate_provider_lease_id;

const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_PROVIDER_LEASE_SECONDS: u64 = 31 * 24 * 60 * 60;
const MAX_RENEW_INCREMENT_SECONDS: u64 = 7 * 24 * 60 * 60;

type HmacSha256 = Hmac<Sha256>;

/// Host-provisioned key used only to create non-reversible receipt
/// fingerprints. It is not an OpenBao token and grants no provider authority.
pub struct BaoReceiptKey {
    key_id: String,
    key: Zeroizing<[u8; 32]>,
}

impl BaoReceiptKey {
    pub fn new(key_id: String, key: [u8; 32]) -> Result<Self, BaoLeaseError> {
        if !component(&key_id) || key == [0; 32] {
            return Err(BaoLeaseError::InvalidRequest);
        }
        Ok(Self {
            key_id,
            key: Zeroizing::new(key),
        })
    }

    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    fn fingerprint(&self, domain: &[u8], bytes: &[u8]) -> [u8; 32] {
        let mut mac = HmacSha256::new_from_slice(self.key.as_ref())
            .expect("HMAC accepts a 32-byte SHA-256 key");
        mac.update(domain);
        mac.update(&(bytes.len() as u64).to_be_bytes());
        mac.update(bytes);
        mac.finalize().into_bytes().into()
    }
}

impl fmt::Debug for BaoReceiptKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoReceiptKey")
            .field("key_id", &self.key_id)
            .field("key", &"[REDACTED]")
            .finish()
    }
}

/// One provider-native dynamic secret request. OpenBao dynamic secrets are
/// issued by reading the enrolled mount/path and return a provider lease id.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretLeaseRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretLeaseRenewRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub lease_id: String,
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretLeaseRevokeRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretLeaseReconcileRequest {
    /// The original indeterminate renew/revoke operation id.
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub lease_id: String,
}

impl BaoClient {
    pub fn secret_lease_binding(
        &self,
        request: &BaoSecretLeaseRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_issue_request(request)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.issue.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        let scope_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.scope.v1",
            self.origin.as_str(),
            &request.namespace,
            &request.mount,
            &request.path,
            &request.consumer_id,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.output-channel.v1",
            &request.operation_id,
            &request.consumer_id,
            &request.mount,
            &request.path,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: Digest32::of_bytes(&scope_bytes).into_array(),
            payload_sha256: Digest32::of_bytes(&payload_bytes).into_array(),
        })
    }

    pub fn secret_lease_renew_binding(
        &self,
        request: &BaoSecretLeaseRenewRequest,
        lease: &SecretLeaseMetadataV1,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_renew_request(request)?;
        validate_lease_request_binding(&request.consumer_id, &request.lease_id, lease)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.renew.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
            lease.scope_sha256,
            lease.rotation_generation,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.renew-payload.v1",
            &request.lease_id,
            request.increment_seconds,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: lease.scope_sha256,
            payload_sha256: Digest32::of_bytes(&payload_bytes).into_array(),
        })
    }

    pub fn secret_lease_revoke_binding(
        &self,
        request: &BaoSecretLeaseRevokeRequest,
        lease: &SecretLeaseMetadataV1,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_revoke_request(request)?;
        validate_lease_request_binding(&request.consumer_id, &request.lease_id, lease)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.revoke.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
            lease.scope_sha256,
            lease.rotation_generation,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.revoke-payload.v1",
            &request.lease_id,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: lease.scope_sha256,
            payload_sha256: Digest32::of_bytes(&payload_bytes).into_array(),
        })
    }

    pub fn secret_lease_reconcile_binding(
        &self,
        request: &BaoSecretLeaseReconcileRequest,
        lease: &SecretLeaseMetadataV1,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_reconcile_request(request)?;
        validate_lease_request_binding(&request.consumer_id, &request.lease_id, lease)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.reconcile.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
            lease.scope_sha256,
            lease.rotation_generation,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.lookup-payload.v1",
            &request.lease_id,
        ))
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: lease.scope_sha256,
            payload_sha256: Digest32::of_bytes(&payload_bytes).into_array(),
        })
    }

    /// Issue a provider-native dynamic secret lease. The operation intent is
    /// durable before dispatch. A transport/protocol ambiguity is persisted and
    /// never retried automatically. Provider data is delivered only after the
    /// lease metadata has committed.
    pub async fn request_secret_lease(
        &self,
        store: &SecretLeaseStore,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoSecretLeaseRequest,
        receipt_key: &BaoReceiptKey,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
        let binding = self.secret_lease_binding(request)?;
        let started_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
        ensure_new_dispatch(
            store
                .prepare_operation(
                    &request.operation_id,
                    SecretLeaseOperationKindV1::Issue,
                    None,
                    binding.request_sha256,
                    started_at_ms,
                )
                .await
                .map_err(BaoLeaseError::Store)?,
        )?;

        let verified = match claim_final_use(authority, grant, &binding) {
            Ok(token) => token,
            Err(error) => {
                store
                    .mark_not_applied(&request.operation_id, None, now_millis().map_err(BaoLeaseError::Store)?)
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(BaoLeaseError::Authority(error));
            }
        };
        if !store
            .claim_dispatch(
                &request.operation_id,
                now_millis().map_err(BaoLeaseError::Store)?,
            )
            .await
            .map_err(BaoLeaseError::Store)?
        {
            return Err(BaoLeaseError::OperationIndeterminate);
        }

        let url = self.dynamic_secret_url(&request.mount, &request.path)?;
        let response = match self
            .authenticated_request(Method::GET, url, &request.namespace)?
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                store
                    .mark_issue_indeterminate(
                        &request.operation_id,
                        None,
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(transport_error(error));
            }
        };
        let status = response.status();
        if status != StatusCode::OK {
            if definitely_not_applied(status) {
                store
                    .mark_not_applied(
                        &request.operation_id,
                        Some(metadata_observation_digest(status.as_u16(), b"")),
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(status_error(status));
            }
            store
                .mark_issue_indeterminate(
                    &request.operation_id,
                    Some(metadata_observation_digest(status.as_u16(), b"")),
                    now_millis().map_err(BaoLeaseError::Store)?,
                )
                .await
                .map_err(BaoLeaseError::Store)?;
            return Err(BaoLeaseError::OperationIndeterminate);
        }

        let body = match bounded_body(response).await {
            Ok(body) => body,
            Err(error) => {
                store
                    .mark_issue_indeterminate(
                        &request.operation_id,
                        None,
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(error);
            }
        };
        let decoded: DynamicLeaseResponse<'_> = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                store
                    .mark_issue_indeterminate(
                        &request.operation_id,
                        None,
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(BaoLeaseError::InvalidResponse);
            }
        };
        validate_provider_lease_id(&decoded.lease_id).map_err(BaoLeaseError::Store)?;
        let observed_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
        let expires_at_ms = expiry_from_seconds(observed_at_ms, decoded.lease_duration)?;
        let secret_bytes = decoded.data.get().as_bytes();
        let secret_fingerprint = receipt_key.fingerprint(
            b"hepta.bao.dynamic-secret-fingerprint.v1\0",
            secret_bytes,
        );
        let metadata = SecretLeaseMetadataV1 {
            schema_version: SECRET_LEASE_SCHEMA_VERSION_V1,
            lease_id: decoded.lease_id.clone(),
            provider_mount: request.mount.clone(),
            namespace: request.namespace.clone(),
            consumer_id: request.consumer_id.clone(),
            scope_sha256: binding.scope_sha256,
            request_sha256: binding.request_sha256,
            fingerprint_key_id: receipt_key.key_id().to_owned(),
            secret_fingerprint,
            renewable: decoded.renewable,
            issued_at_ms: observed_at_ms,
            expires_at_ms,
            rotation_generation: 1,
            state: SecretLeaseStateV1::Active,
            revision: 1,
        };
        let observation = dynamic_metadata_digest(
            &metadata.lease_id,
            metadata.renewable,
            decoded.lease_duration,
        );
        let stored = match store
            .commit_issue(
                &request.operation_id,
                &metadata,
                observation,
                observed_at_ms,
            )
            .await
        {
            Ok(stored) => stored,
            Err(error) => {
                let _ = store
                    .mark_issue_indeterminate(
                        &request.operation_id,
                        Some(observation),
                        observed_at_ms,
                    )
                    .await;
                return Err(BaoLeaseError::Store(error));
            }
        };

        deliver_final_use(authority, verified, &binding, || consumer(secret_bytes))
            .map_err(BaoLeaseError::Authority)?
            .map_err(|()| BaoLeaseError::ConsumerIndeterminate)?;
        Ok(stored)
    }

    pub async fn renew_secret_lease(
        &self,
        store: &SecretLeaseStore,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoSecretLeaseRenewRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
        validate_renew_request(request)?;
        let now_ms = now_millis().map_err(BaoLeaseError::Store)?;
        let lease = active_lease(store, &request.lease_id, &request.consumer_id, now_ms).await?;
        if !lease.renewable {
            return Err(BaoLeaseError::LeaseNotRenewable);
        }
        let binding = self.secret_lease_renew_binding(request, &lease)?;
        ensure_new_dispatch(
            store
                .prepare_operation(
                    &request.operation_id,
                    SecretLeaseOperationKindV1::Renew,
                    Some(&request.lease_id),
                    binding.request_sha256,
                    now_ms,
                )
                .await
                .map_err(BaoLeaseError::Store)?,
        )?;
        if let Err(error) = claim_final_use(authority, grant, &binding) {
            store
                .mark_not_applied(
                    &request.operation_id,
                    None,
                    now_millis().map_err(BaoLeaseError::Store)?,
                )
                .await
                .map_err(BaoLeaseError::Store)?;
            return Err(BaoLeaseError::Authority(error));
        }
        if !store
            .claim_dispatch(
                &request.operation_id,
                now_millis().map_err(BaoLeaseError::Store)?,
            )
            .await
            .map_err(BaoLeaseError::Store)?
        {
            return Err(BaoLeaseError::OperationIndeterminate);
        }
        let payload = RenewPayload {
            lease_id: &request.lease_id,
            increment: request.increment_seconds,
        };
        let response = match self
            .authenticated_request(Method::POST, self.sys_lease_url("renew")?, &lease.namespace)?
            .json(&payload)
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                mark_renew_indeterminate(store, request, None).await?;
                return Err(transport_error(error));
            }
        };
        let status = response.status();
        if status != StatusCode::OK {
            if definitely_not_applied(status) {
                store
                    .mark_not_applied(
                        &request.operation_id,
                        Some(metadata_observation_digest(status.as_u16(), b"")),
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(status_error(status));
            }
            mark_renew_indeterminate(
                store,
                request,
                Some(metadata_observation_digest(status.as_u16(), b"")),
            )
            .await?;
            return Err(BaoLeaseError::OperationIndeterminate);
        }
        let body = bounded_body(response).await.map_err(|error| {
            // The provider may have renewed the lease before a truncated or
            // malformed response reached us. The caller will persist ambiguity
            // below after this error is observed.
            error
        });
        let body = match body {
            Ok(body) => body,
            Err(error) => {
                mark_renew_indeterminate(store, request, None).await?;
                return Err(error);
            }
        };
        let decoded: RenewResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                mark_renew_indeterminate(store, request, None).await?;
                return Err(BaoLeaseError::InvalidResponse);
            }
        };
        if decoded.lease_id != request.lease_id {
            mark_renew_indeterminate(store, request, None).await?;
            return Err(BaoLeaseError::InvalidResponse);
        }
        let observed_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
        let expires_at_ms = expiry_from_seconds(observed_at_ms, decoded.lease_duration)?;
        let observation =
            dynamic_metadata_digest(&decoded.lease_id, decoded.renewable, decoded.lease_duration);
        store
            .commit_renew(
                &request.operation_id,
                &request.lease_id,
                decoded.renewable,
                expires_at_ms,
                observation,
                observed_at_ms,
            )
            .await
            .map_err(BaoLeaseError::Store)
    }

    pub async fn revoke_secret_lease(
        &self,
        store: &SecretLeaseStore,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoSecretLeaseRevokeRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
        validate_revoke_request(request)?;
        let now_ms = now_millis().map_err(BaoLeaseError::Store)?;
        let lease = revocable_lease(store, &request.lease_id, &request.consumer_id, now_ms).await?;
        let binding = self.secret_lease_revoke_binding(request, &lease)?;
        ensure_new_dispatch(
            store
                .prepare_operation(
                    &request.operation_id,
                    SecretLeaseOperationKindV1::Revoke,
                    Some(&request.lease_id),
                    binding.request_sha256,
                    now_ms,
                )
                .await
                .map_err(BaoLeaseError::Store)?,
        )?;
        if let Err(error) = claim_final_use(authority, grant, &binding) {
            store
                .mark_not_applied(
                    &request.operation_id,
                    None,
                    now_millis().map_err(BaoLeaseError::Store)?,
                )
                .await
                .map_err(BaoLeaseError::Store)?;
            return Err(BaoLeaseError::Authority(error));
        }
        if !store
            .claim_dispatch(
                &request.operation_id,
                now_millis().map_err(BaoLeaseError::Store)?,
            )
            .await
            .map_err(BaoLeaseError::Store)?
        {
            return Err(BaoLeaseError::OperationIndeterminate);
        }

        let payload = RevokePayload {
            lease_id: &request.lease_id,
            sync: true,
        };
        let response = match self
            .authenticated_request(Method::POST, self.sys_lease_url("revoke")?, &lease.namespace)?
            .json(&payload)
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                mark_revoke_indeterminate(store, request, None).await?;
                return Err(transport_error(error));
            }
        };
        let status = response.status();
        if status != StatusCode::OK && status != StatusCode::NO_CONTENT {
            if matches!(
                status,
                StatusCode::BAD_REQUEST | StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
            ) {
                store
                    .mark_not_applied(
                        &request.operation_id,
                        Some(metadata_observation_digest(status.as_u16(), b"")),
                        now_millis().map_err(BaoLeaseError::Store)?,
                    )
                    .await
                    .map_err(BaoLeaseError::Store)?;
                return Err(status_error(status));
            }
            mark_revoke_indeterminate(
                store,
                request,
                Some(metadata_observation_digest(status.as_u16(), b"")),
            )
            .await?;
            return Err(BaoLeaseError::OperationIndeterminate);
        }
        let observed_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
        let observation = metadata_observation_digest(status.as_u16(), request.lease_id.as_bytes());
        store
            .commit_revoke(
                &request.operation_id,
                &request.lease_id,
                observation,
                observed_at_ms,
            )
            .await
            .map_err(BaoLeaseError::Store)
    }

    /// Reconcile an indeterminate renew/revoke using OpenBao lease lookup. The
    /// read itself is separately final-use authorized. An issuance timeout with
    /// no received lease id cannot use this path and requires an independently
    /// trusted audit/provider observation through SecretLeaseStore.
    pub async fn reconcile_secret_lease(
        &self,
        store: &SecretLeaseStore,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoSecretLeaseReconcileRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
        validate_reconcile_request(request)?;
        let lease = store
            .lease(&request.lease_id)
            .await
            .map_err(BaoLeaseError::Store)?
            .ok_or(BaoLeaseError::LeaseUnavailable)?;
        validate_lease_request_binding(&request.consumer_id, &request.lease_id, &lease)?;
        let operation = store
            .operation(&request.operation_id)
            .await
            .map_err(BaoLeaseError::Store)?
            .ok_or(BaoLeaseError::OperationIndeterminate)?;
        if operation.lease_id.as_deref() != Some(request.lease_id.as_str())
            || operation.state != SecretLeaseOperationStateV1::Indeterminate
            || !matches!(
                operation.kind,
                SecretLeaseOperationKindV1::Renew | SecretLeaseOperationKindV1::Revoke
            )
        {
            return Err(BaoLeaseError::OperationIndeterminate);
        }
        let binding = self.secret_lease_reconcile_binding(request, &lease)?;
        let verified =
            claim_final_use(authority, grant, &binding).map_err(BaoLeaseError::Authority)?;
        let payload = LookupPayload {
            lease_id: &request.lease_id,
        };
        let response = self
            .authenticated_request(Method::POST, self.sys_lease_url("lookup")?, &lease.namespace)?
            .json(&payload)
            .send()
            .await
            .map_err(transport_error)?;
        let status = response.status();
        if status == StatusCode::NOT_FOUND {
            let observed_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
            let observation =
                metadata_observation_digest(status.as_u16(), request.lease_id.as_bytes());
            let reconciled = store
                .reconcile_known_absent(
                    &request.operation_id,
                    &request.lease_id,
                    observation,
                    observed_at_ms,
                )
                .await
                .map_err(BaoLeaseError::Store)?;
            deliver_final_use(authority, verified, &binding, || ())
                .map_err(BaoLeaseError::Authority)?;
            return Ok(reconciled);
        }
        if status != StatusCode::OK {
            return Err(status_error(status));
        }
        let body = bounded_body(response).await?;
        let decoded: LookupResponse =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseError::InvalidResponse)?;
        let observed_at_ms = now_millis().map_err(BaoLeaseError::Store)?;
        if decoded.data.ttl == 0 {
            let observation =
                metadata_observation_digest(status.as_u16(), request.lease_id.as_bytes());
            let reconciled = store
                .reconcile_known_absent(
                    &request.operation_id,
                    &request.lease_id,
                    observation,
                    observed_at_ms,
                )
                .await
                .map_err(BaoLeaseError::Store)?;
            deliver_final_use(authority, verified, &binding, || ())
                .map_err(BaoLeaseError::Authority)?;
            return Ok(reconciled);
        }
        let expires_at_ms = expiry_from_seconds(observed_at_ms, decoded.data.ttl)?;
        let observation =
            dynamic_metadata_digest(&request.lease_id, decoded.data.renewable, decoded.data.ttl);
        let reconciled = store
            .reconcile_known_active(
                &request.operation_id,
                &request.lease_id,
                decoded.data.renewable,
                expires_at_ms,
                observation,
                observed_at_ms,
            )
            .await
            .map_err(BaoLeaseError::Store)?;
        deliver_final_use(authority, verified, &binding, || ())
            .map_err(BaoLeaseError::Authority)?;
        Ok(reconciled)
    }

    fn dynamic_secret_url(
        &self,
        mount: &str,
        path: &str,
    ) -> Result<url::Url, BaoLeaseError> {
        if !segmented(mount) || !segmented(path) {
            return Err(BaoLeaseError::InvalidRequest);
        }
        let mut url = self.origin.clone();
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoLeaseError::InvalidRequest)?;
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

    fn sys_lease_url(&self, operation: &str) -> Result<url::Url, BaoLeaseError> {
        if !matches!(operation, "renew" | "revoke" | "lookup") {
            return Err(BaoLeaseError::InvalidRequest);
        }
        let mut url = self.origin.clone();
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoLeaseError::InvalidRequest)?;
        parts
            .clear()
            .push("v1")
            .push("sys")
            .push("leases")
            .push(operation);
        drop(parts);
        Ok(url)
    }

    fn authenticated_request(
        &self,
        method: Method,
        url: url::Url,
        namespace: &str,
    ) -> Result<codex_http_client::RequestBuilder, BaoLeaseError> {
        if !namespace.is_empty() && !segmented(namespace) {
            return Err(BaoLeaseError::InvalidRequest);
        }
        let mut token =
            HeaderValue::from_str(&self.token.0).map_err(|_| BaoLeaseError::InvalidConfiguration)?;
        token.set_sensitive(true);
        let mut request = self
            .client
            .request(method, url)
            .header("X-Vault-Token", token)
            .header("Accept", "application/json");
        if !namespace.is_empty() {
            request = request.header("X-Vault-Namespace", namespace);
        }
        Ok(request)
    }
}

async fn active_lease(
    store: &SecretLeaseStore,
    lease_id: &str,
    consumer_id: &str,
    now_ms: u64,
) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
    let lease = store
        .lease(lease_id)
        .await
        .map_err(BaoLeaseError::Store)?
        .ok_or(BaoLeaseError::LeaseUnavailable)?;
    if lease.consumer_id != consumer_id
        || !lease.is_usable_at(now_ms)
    {
        return Err(BaoLeaseError::LeaseUnavailable);
    }
    Ok(lease)
}

async fn revocable_lease(
    store: &SecretLeaseStore,
    lease_id: &str,
    consumer_id: &str,
    now_ms: u64,
) -> Result<SecretLeaseMetadataV1, BaoLeaseError> {
    let lease = store
        .lease(lease_id)
        .await
        .map_err(BaoLeaseError::Store)?
        .ok_or(BaoLeaseError::LeaseUnavailable)?;
    if lease.consumer_id != consumer_id
        || now_ms >= lease.expires_at_ms
        || matches!(
            lease.state,
            SecretLeaseStateV1::Revoked
                | SecretLeaseStateV1::Expired
                | SecretLeaseStateV1::RevokeIndeterminate
        )
    {
        return Err(BaoLeaseError::LeaseUnavailable);
    }
    Ok(lease)
}

async fn mark_renew_indeterminate(
    store: &SecretLeaseStore,
    request: &BaoSecretLeaseRenewRequest,
    observed_sha256: Option<[u8; 32]>,
) -> Result<(), BaoLeaseError> {
    store
        .mark_lease_indeterminate(
            &request.operation_id,
            &request.lease_id,
            SecretLeaseStateV1::RenewIndeterminate,
            observed_sha256,
            now_millis().map_err(BaoLeaseError::Store)?,
        )
        .await
        .map_err(BaoLeaseError::Store)
}

async fn mark_revoke_indeterminate(
    store: &SecretLeaseStore,
    request: &BaoSecretLeaseRevokeRequest,
    observed_sha256: Option<[u8; 32]>,
) -> Result<(), BaoLeaseError> {
    store
        .mark_lease_indeterminate(
            &request.operation_id,
            &request.lease_id,
            SecretLeaseStateV1::RevokeIndeterminate,
            observed_sha256,
            now_millis().map_err(BaoLeaseError::Store)?,
        )
        .await
        .map_err(BaoLeaseError::Store)
}

fn ensure_new_dispatch(
    admission: SecretLeaseOperationAdmissionV1,
) -> Result<(), BaoLeaseError> {
    match admission {
        SecretLeaseOperationAdmissionV1::Prepared
        | SecretLeaseOperationAdmissionV1::AlreadyPrepared => Ok(()),
        SecretLeaseOperationAdmissionV1::AlreadyApplied => {
            Err(BaoLeaseError::OperationAlreadyApplied)
        }
        SecretLeaseOperationAdmissionV1::NotApplied => {
            Err(BaoLeaseError::OperationNotApplied)
        }
        SecretLeaseOperationAdmissionV1::Dispatching
        | SecretLeaseOperationAdmissionV1::Indeterminate => {
            Err(BaoLeaseError::OperationIndeterminate)
        }
    }
}

fn validate_issue_request(request: &BaoSecretLeaseRequest) -> Result<(), BaoLeaseError> {
    validate_operation_id(&request.operation_id).map_err(BaoLeaseError::Store)?;
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.mount)
        || !segmented(&request.path)
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_renew_request(request: &BaoSecretLeaseRenewRequest) -> Result<(), BaoLeaseError> {
    validate_operation_id(&request.operation_id).map_err(BaoLeaseError::Store)?;
    validate_provider_lease_id(&request.lease_id).map_err(BaoLeaseError::Store)?;
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || request.increment_seconds == 0
        || request.increment_seconds > MAX_RENEW_INCREMENT_SECONDS
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_revoke_request(request: &BaoSecretLeaseRevokeRequest) -> Result<(), BaoLeaseError> {
    validate_operation_id(&request.operation_id).map_err(BaoLeaseError::Store)?;
    validate_provider_lease_id(&request.lease_id).map_err(BaoLeaseError::Store)?;
    if !component(&request.subject_id) || !component(&request.consumer_id) {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_reconcile_request(
    request: &BaoSecretLeaseReconcileRequest,
) -> Result<(), BaoLeaseError> {
    validate_operation_id(&request.operation_id).map_err(BaoLeaseError::Store)?;
    validate_provider_lease_id(&request.lease_id).map_err(BaoLeaseError::Store)?;
    if !component(&request.subject_id) || !component(&request.consumer_id) {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_lease_request_binding(
    consumer_id: &str,
    lease_id: &str,
    lease: &SecretLeaseMetadataV1,
) -> Result<(), BaoLeaseError> {
    if lease.consumer_id != consumer_id || lease.lease_id != lease_id {
        return Err(BaoLeaseError::LeaseUnavailable);
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
    value.len() <= 1_024 && value.split('/').all(component)
}

fn expiry_from_seconds(now_ms: u64, seconds: u64) -> Result<u64, BaoLeaseError> {
    if seconds == 0 || seconds > MAX_PROVIDER_LEASE_SECONDS {
        return Err(BaoLeaseError::InvalidResponse);
    }
    now_ms
        .checked_add(
            seconds
                .checked_mul(1_000)
                .ok_or(BaoLeaseError::InvalidResponse)?,
        )
        .ok_or(BaoLeaseError::InvalidResponse)
}

async fn bounded_body(mut response: HttpResponse) -> Result<Zeroizing<Vec<u8>>, BaoLeaseError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(BaoLeaseError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
        if chunk.len() > MAX_RESPONSE_BYTES - body.len() {
            return Err(BaoLeaseError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn transport_error(error: HttpError) -> BaoLeaseError {
    if error.is_timeout() {
        BaoLeaseError::TimedOut
    } else {
        BaoLeaseError::TransportUnavailable
    }
}

fn definitely_not_applied(status: StatusCode) -> bool {
    matches!(
        status,
        StatusCode::BAD_REQUEST
            | StatusCode::UNAUTHORIZED
            | StatusCode::FORBIDDEN
            | StatusCode::NOT_FOUND
    )
}

fn status_error(status: StatusCode) -> BaoLeaseError {
    match status {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => BaoLeaseError::ProviderDenied,
        StatusCode::NOT_FOUND => BaoLeaseError::NotFound,
        _ if status.is_client_error() => BaoLeaseError::InvalidRequest,
        _ => BaoLeaseError::ProviderUnavailable,
    }
}

fn metadata_observation_digest(status: u16, bytes: &[u8]) -> [u8; 32] {
    let mut material = Vec::with_capacity(64 + bytes.len());
    material.extend_from_slice(b"hepta.bao.lease-observation.v1\0");
    material.extend_from_slice(&status.to_be_bytes());
    material.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    material.extend_from_slice(bytes);
    Digest32::of_bytes(&material).into_array()
}

fn dynamic_metadata_digest(lease_id: &str, renewable: bool, ttl_seconds: u64) -> [u8; 32] {
    let mut material = Vec::new();
    material.extend_from_slice(b"hepta.bao.dynamic-lease-metadata.v1\0");
    material.extend_from_slice(&(lease_id.len() as u64).to_be_bytes());
    material.extend_from_slice(lease_id.as_bytes());
    material.push(u8::from(renewable));
    material.extend_from_slice(&ttl_seconds.to_be_bytes());
    Digest32::of_bytes(&material).into_array()
}

#[derive(Deserialize)]
struct DynamicLeaseResponse<'a> {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
    #[serde(borrow)]
    data: &'a RawValue,
}

#[derive(Deserialize)]
struct RenewResponse {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
}

#[derive(Deserialize)]
struct LookupResponse {
    data: LookupData,
}

#[derive(Deserialize)]
struct LookupData {
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoLeaseError {
    InvalidConfiguration,
    InvalidRequest,
    Authority(FinalUseError),
    Store(SecretLeaseStoreError),
    ProviderDenied,
    ProviderUnavailable,
    NotFound,
    TransportUnavailable,
    TimedOut,
    ResponseTooLarge,
    InvalidResponse,
    LeaseUnavailable,
    LeaseNotRenewable,
    OperationAlreadyApplied,
    OperationNotApplied,
    OperationIndeterminate,
    ConsumerIndeterminate,
}

impl fmt::Display for BaoLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for BaoLeaseError {}

#[cfg(all(test, unix))]
#[path = "lease_client_tests.rs"]
mod tests;
