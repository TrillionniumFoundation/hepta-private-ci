use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_http_client::HttpError;
use codex_http_client::HttpResponse;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use zeroize::Zeroizing;

use super::BaoClient;
use super::MAX_RESPONSE_BYTES;
use crate::lease_registry::SecretLeaseRegistry;
use crate::lease_types::DynamicSecretLeaseRequest;
use crate::lease_types::DynamicSecretValues;
use crate::lease_types::LeaseOperationKind;
use crate::lease_types::LeaseOperationState;
use crate::lease_types::LeaseReconcileRequest;
use crate::lease_types::LeaseRenewRequest;
use crate::lease_types::LeaseRevokeRequest;
use crate::lease_types::MAX_LEASE_TTL_SECONDS;
use crate::lease_types::RevocationObservation;
use crate::lease_types::SECRET_LEASE_SCHEMA_VERSION;
use crate::lease_types::SecretLeaseError;
use crate::lease_types::SecretLeaseMetadata;
use crate::lease_types::SecretLeaseState;
use crate::lease_types::UnknownIssueResolution;
use crate::lease_types::UnknownIssueResolutionRequest;
use crate::lease_types::normalized_secret_fields;
use crate::lease_types::valid_component;
use crate::lease_types::valid_lease_id;
use crate::lease_types::valid_namespace;
use crate::lease_types::valid_operation_id;
use crate::lease_types::valid_segmented;

impl BaoClient {
    pub fn dynamic_secret_lease_binding(
        &self,
        request: &DynamicSecretLeaseRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        let normalized = normalized_issue_request(request)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.issue.v1",
            self.origin.as_str(),
            self.ca_sha256,
            &normalized,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        let scope_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.scope.v1",
            self.origin.as_str(),
            &normalized.namespace,
            &normalized.mount,
            &normalized.path,
            &normalized.consumer_id,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.payload.v1",
            &normalized.mount,
            &normalized.path,
            &normalized.secret_fields,
            normalized.max_lease_duration_seconds,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        Ok(final_use_binding(
            normalized.subject_id,
            request_bytes,
            scope_bytes,
            payload_bytes,
        ))
    }

    pub fn lease_renew_binding(
        &self,
        request: &LeaseRenewRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_renew_request(request)?;
        operation_binding(
            self,
            "hepta.bao.lease.renew.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            &request.lease_id,
            &(request.increment_seconds,),
        )
    }

    pub fn lease_revoke_binding(
        &self,
        request: &LeaseRevokeRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_common_lease_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.namespace,
            &request.lease_id,
        )?;
        operation_binding(
            self,
            "hepta.bao.lease.revoke.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            &request.lease_id,
            &(true,),
        )
    }

    pub fn lease_reconcile_binding(
        &self,
        request: &LeaseReconcileRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_reconcile_request(request)?;
        operation_binding(
            self,
            "hepta.bao.lease.lookup.v1",
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            &request.lease_id,
            &(request.target_operation_id.as_str(),),
        )
    }

    pub fn unknown_issue_resolution_binding(
        &self,
        request: &UnknownIssueResolutionRequest,
    ) -> Result<FinalUseBinding, SecretLeaseError> {
        validate_unknown_resolution_request(request)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.resolve-unknown.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        let scope_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.resolve-scope.v1",
            self.origin.as_str(),
            &request.issue_operation_id,
            &request.consumer_id,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        let payload_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-secret.resolve-payload.v1",
            &request.issue_operation_id,
            &request.resolution_operation_id,
            &request.resolution,
        ))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
        Ok(final_use_binding(
            request.subject_id.clone(),
            request_bytes,
            scope_bytes,
            payload_bytes,
        ))
    }

    /// Issue one provider-native dynamic secret. The operation is durably
    /// fenced as uncertain before dispatch and is never retried automatically.
    pub async fn request_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &DynamicSecretLeaseRequest,
        consumer: impl FnOnce(&DynamicSecretValues) -> Result<(), ()>,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        let normalized = normalized_issue_request(request)?;
        let binding = self.dynamic_secret_lease_binding(&normalized)?;
        registry.preflight_operation(&normalized.operation_id, binding.request_sha256)?;
        let url = provider_url(self, &normalized.mount, &normalized.path)?;
        let network_request = authenticated_get(self, url, &normalized.namespace)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;

        registry.reserve_issue(normalized.clone(), &binding, now_ms()?)?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(_) => {
                registry.touch_unknown(&normalized.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        if response.status().is_client_error() {
            let status = response.status();
            registry.reject_issue(&normalized.operation_id, now_ms()?)?;
            return Err(client_status_error(status));
        }
        if response.status() != StatusCode::OK {
            registry.touch_unknown(&normalized.operation_id, now_ms()?)?;
            return Err(SecretLeaseError::OutcomeIndeterminate);
        }

        let body = match bounded_body(response).await {
            Ok(body) => body,
            Err(_) => {
                registry.touch_unknown(&normalized.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        let mut decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                registry.touch_unknown(&normalized.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        if !valid_lease_id(&decoded.lease_id)
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_TTL_SECONDS
        {
            registry.touch_unknown(&normalized.operation_id, now_ms()?)?;
            return Err(SecretLeaseError::OutcomeIndeterminate);
        }

        let observed_at = now_ms()?;
        let mut metadata = SecretLeaseMetadata {
            schema_version: SECRET_LEASE_SCHEMA_VERSION,
            lease_id: decoded.lease_id.clone(),
            subject_id: normalized.subject_id.clone(),
            consumer_id: normalized.consumer_id.clone(),
            issued_operation_id: normalized.operation_id.clone(),
            last_operation_id: normalized.operation_id.clone(),
            namespace: normalized.namespace.clone(),
            mount: normalized.mount.clone(),
            path: normalized.path.clone(),
            secret_fields: normalized.secret_fields.clone(),
            renewable: decoded.renewable,
            lease_duration_seconds: decoded.lease_duration,
            max_lease_duration_seconds: normalized.max_lease_duration_seconds,
            observed_at_unix_ms: observed_at,
            expires_at_unix_ms: expiry(observed_at, decoded.lease_duration)?,
            rotation_generation: 1,
            state: SecretLeaseState::RevokeRequired,
            request_sha256: binding.request_sha256,
            scope_sha256: binding.scope_sha256,
        };

        if decoded.lease_duration > normalized.max_lease_duration_seconds {
            registry.complete_issue(metadata, observed_at)?;
            return Err(SecretLeaseError::LeaseDurationExceeded);
        }

        let mut selected = BTreeMap::new();
        for field in &normalized.secret_fields {
            let Some(value) = decoded.data.remove(field) else {
                registry.complete_issue(metadata, observed_at)?;
                return Err(SecretLeaseError::InvalidResponse);
            };
            selected.insert(field.clone(), value);
        }
        let values = DynamicSecretValues::from_map(selected);

        match authority.with_verified_use(verified, &binding, || consumer(&values)) {
            Ok(Ok(())) => {
                metadata.state = SecretLeaseState::Active;
                registry
                    .complete_issue(metadata.clone(), now_ms()?)
                    .map_err(|_| SecretLeaseError::ConsumerIndeterminate)?;
                Ok(metadata)
            }
            Ok(Err(())) => {
                registry
                    .complete_issue(metadata, now_ms()?)
                    .map_err(|_| SecretLeaseError::ConsumerIndeterminate)?;
                Err(SecretLeaseError::ConsumerIndeterminate)
            }
            Err(error) => {
                registry.complete_issue(metadata, now_ms()?)?;
                Err(SecretLeaseError::Authority(error))
            }
        }
    }

    pub async fn renew_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &LeaseRenewRequest,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        validate_renew_request(request)?;
        let current = require_matching_lease(
            registry,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        if current.state != SecretLeaseState::Active {
            return Err(SecretLeaseError::LeaseNotActive);
        }
        if !current.renewable {
            return Err(SecretLeaseError::LeaseNotRenewable);
        }

        let binding = self.lease_renew_binding(request)?;
        registry.preflight_operation(&request.operation_id, binding.request_sha256)?;
        let _verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        registry.begin_renew(
            &request.operation_id,
            binding.request_sha256,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            now_ms()?,
        )?;

        let response = authenticated_post(
            self,
            system_url(self, &["sys", "leases", "renew"] )?,
            &request.namespace,
            &serde_json::json!({
                "lease_id": request.lease_id.as_str(),
                "increment": request.increment_seconds,
            }),
        )?
        .send()
        .await;
        let response = match response {
            Ok(response) => response,
            Err(_) => {
                registry.touch_unknown(&request.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        if response.status() == StatusCode::NOT_FOUND {
            return registry.complete_provider_absent_mutation(&request.operation_id, now_ms()?);
        }
        if response.status().is_client_error() {
            let status = response.status();
            registry.reject_lease_mutation(&request.operation_id, now_ms()?)?;
            return Err(client_status_error(status));
        }
        if response.status() != StatusCode::OK {
            registry.touch_unknown(&request.operation_id, now_ms()?)?;
            return Err(SecretLeaseError::OutcomeIndeterminate);
        }

        let body = match bounded_body(response).await {
            Ok(body) => body,
            Err(_) => {
                registry.touch_unknown(&request.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        let decoded: LeaseMutationResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                registry.touch_unknown(&request.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        if decoded.lease_id != request.lease_id
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_TTL_SECONDS
        {
            registry.touch_unknown(&request.operation_id, now_ms()?)?;
            return Err(SecretLeaseError::OutcomeIndeterminate);
        }
        let metadata = registry.complete_renew(
            &request.operation_id,
            decoded.lease_duration,
            decoded.renewable,
            now_ms()?,
        )?;
        if metadata.state == SecretLeaseState::RevokeRequired {
            Err(SecretLeaseError::LeaseDurationExceeded)
        } else {
            Ok(metadata)
        }
    }

    pub async fn revoke_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &LeaseRevokeRequest,
    ) -> Result<RevocationObservation, SecretLeaseError> {
        validate_common_lease_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.namespace,
            &request.lease_id,
        )?;
        let current = require_matching_lease(
            registry,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        if current.state.is_terminal() || current.state == SecretLeaseState::RevokeOutcomeUnknown {
            return Err(SecretLeaseError::LeaseNotActive);
        }

        let binding = self.lease_revoke_binding(request)?;
        registry.preflight_operation(&request.operation_id, binding.request_sha256)?;
        let _verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        registry.begin_revoke(
            &request.operation_id,
            binding.request_sha256,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            now_ms()?,
        )?;

        let response = authenticated_post(
            self,
            system_url(self, &["sys", "leases", "revoke"] )?,
            &request.namespace,
            &serde_json::json!({
                "lease_id": request.lease_id.as_str(),
                "sync": true,
            }),
        )?
        .send()
        .await;
        let response = match response {
            Ok(response) => response,
            Err(_) => {
                registry.touch_unknown(&request.operation_id, now_ms()?)?;
                return Err(SecretLeaseError::OutcomeIndeterminate);
            }
        };
        if response.status() == StatusCode::NOT_FOUND {
            let metadata =
                registry.complete_provider_absent_mutation(&request.operation_id, now_ms()?)?;
            return Ok(revocation_observation(&metadata));
        }
        if response.status().is_client_error() {
            let status = response.status();
            registry.reject_lease_mutation(&request.operation_id, now_ms()?)?;
            return Err(client_status_error(status));
        }
        if !response.status().is_success() {
            registry.touch_unknown(&request.operation_id, now_ms()?)?;
            return Err(SecretLeaseError::OutcomeIndeterminate);
        }
        let metadata = registry.complete_revoke(&request.operation_id, now_ms()?)?;
        Ok(revocation_observation(&metadata))
    }

    pub async fn reconcile_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &LeaseReconcileRequest,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        validate_reconcile_request(request)?;
        let current = require_matching_lease(
            registry,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        let expected_kind = match current.state {
            SecretLeaseState::RenewOutcomeUnknown => LeaseOperationKind::Renew,
            SecretLeaseState::RevokeOutcomeUnknown => LeaseOperationKind::Revoke,
            _ => return Err(SecretLeaseError::ReconciliationRequired),
        };
        let target = registry
            .operation(&request.target_operation_id)?
            .ok_or(SecretLeaseError::ReconciliationRequired)?;
        if target.kind != expected_kind
            || target.state != LeaseOperationState::OutcomeUnknown
            || target.lease_id.as_deref() != Some(request.lease_id.as_str())
        {
            return Err(SecretLeaseError::ReconciliationRequired);
        }

        let binding = self.lease_reconcile_binding(request)?;
        registry.preflight_operation(&request.operation_id, binding.request_sha256)?;
        let _verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        let response = authenticated_post(
            self,
            system_url(self, &["sys", "leases", "lookup"] )?,
            &request.namespace,
            &serde_json::json!({"lease_id": request.lease_id.as_str()}),
        )?
        .send()
        .await
        .map_err(transport_error)?;

        if response.status() == StatusCode::NOT_FOUND {
            return registry.reconcile_absent(
                &request.operation_id,
                &request.target_operation_id,
                binding.request_sha256,
                &request.lease_id,
                &request.subject_id,
                &request.consumer_id,
                now_ms()?,
            );
        }
        if response.status().is_client_error() {
            return Err(client_status_error(response.status()));
        }
        if response.status() != StatusCode::OK {
            return Err(SecretLeaseError::ProviderUnavailable);
        }
        let body = bounded_body(response).await?;
        let decoded: LeaseLookupResponse =
            serde_json::from_slice(&body).map_err(|_| SecretLeaseError::InvalidResponse)?;
        if decoded.data.id != request.lease_id
            || decoded.data.ttl == 0
            || decoded.data.ttl > MAX_LEASE_TTL_SECONDS
        {
            return Err(SecretLeaseError::InvalidResponse);
        }
        registry.reconcile_active(
            &request.operation_id,
            &request.target_operation_id,
            binding.request_sha256,
            &request.lease_id,
            &request.subject_id,
            &request.consumer_id,
            decoded.data.ttl,
            decoded.data.renewable,
            now_ms()?,
        )
    }

    pub fn resolve_unknown_secret_issue(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &UnknownIssueResolutionRequest,
    ) -> Result<Option<SecretLeaseMetadata>, SecretLeaseError> {
        validate_unknown_resolution_request(request)?;
        let binding = self.unknown_issue_resolution_binding(request)?;
        registry.validate_unknown_issue_resolution(request, binding.request_sha256)?;
        let verified = authority
            .claim(grant, &binding)
            .map_err(SecretLeaseError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(SecretLeaseError::Authority)?;
        registry.resolve_unknown_issue(request, binding.request_sha256, now_ms()?)
    }
}

fn final_use_binding(
    subject_id: String,
    request_bytes: Vec<u8>,
    scope_bytes: Vec<u8>,
    payload_bytes: Vec<u8>,
) -> FinalUseBinding {
    FinalUseBinding {
        subject_id,
        destination_id: "provider:heptabao".to_owned(),
        request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
        scope_sha256: Digest32::of_bytes(&scope_bytes).into_array(),
        payload_sha256: Digest32::of_bytes(&payload_bytes).into_array(),
    }
}

fn operation_binding<T: serde::Serialize>(
    client: &BaoClient,
    domain: &'static str,
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
    operation_id: &str,
    lease_id: &str,
    payload: &T,
) -> Result<FinalUseBinding, SecretLeaseError> {
    let request_bytes = serde_json::to_vec(&(
        domain,
        client.origin.as_str(),
        client.ca_sha256,
        subject_id,
        consumer_id,
        namespace,
        operation_id,
        lease_id,
        payload,
    ))
    .map_err(|_| SecretLeaseError::InvalidRequest)?;
    let scope_bytes = serde_json::to_vec(&(
        "hepta.bao.lease.scope.v1",
        client.origin.as_str(),
        namespace,
        lease_id,
        consumer_id,
    ))
    .map_err(|_| SecretLeaseError::InvalidRequest)?;
    let payload_bytes = serde_json::to_vec(&(domain, lease_id, payload))
        .map_err(|_| SecretLeaseError::InvalidRequest)?;
    Ok(final_use_binding(
        subject_id.to_owned(),
        request_bytes,
        scope_bytes,
        payload_bytes,
    ))
}

fn normalized_issue_request(
    request: &DynamicSecretLeaseRequest,
) -> Result<DynamicSecretLeaseRequest, SecretLeaseError> {
    if !valid_component(&request.subject_id)
        || !valid_component(&request.consumer_id)
        || !valid_operation_id(&request.operation_id)
        || !valid_namespace(&request.namespace)
        || !valid_segmented(&request.mount)
        || !valid_segmented(&request.path)
        || request.max_lease_duration_seconds == 0
        || request.max_lease_duration_seconds > MAX_LEASE_TTL_SECONDS
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    let Some(fields) = normalized_secret_fields(&request.secret_fields) else {
        return Err(SecretLeaseError::InvalidRequest);
    };
    let mut normalized = request.clone();
    normalized.secret_fields = fields;
    Ok(normalized)
}

fn validate_renew_request(request: &LeaseRenewRequest) -> Result<(), SecretLeaseError> {
    validate_common_lease_request(
        &request.subject_id,
        &request.consumer_id,
        &request.operation_id,
        &request.namespace,
        &request.lease_id,
    )?;
    if request.increment_seconds > MAX_LEASE_TTL_SECONDS {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_reconcile_request(request: &LeaseReconcileRequest) -> Result<(), SecretLeaseError> {
    validate_common_lease_request(
        &request.subject_id,
        &request.consumer_id,
        &request.operation_id,
        &request.namespace,
        &request.lease_id,
    )?;
    if !valid_operation_id(&request.target_operation_id)
        || request.target_operation_id == request.operation_id
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_common_lease_request(
    subject_id: &str,
    consumer_id: &str,
    operation_id: &str,
    namespace: &str,
    lease_id: &str,
) -> Result<(), SecretLeaseError> {
    if !valid_component(subject_id)
        || !valid_component(consumer_id)
        || !valid_operation_id(operation_id)
        || !valid_namespace(namespace)
        || !valid_lease_id(lease_id)
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_unknown_resolution_request(
    request: &UnknownIssueResolutionRequest,
) -> Result<(), SecretLeaseError> {
    if !valid_component(&request.subject_id)
        || !valid_component(&request.consumer_id)
        || !valid_operation_id(&request.issue_operation_id)
        || !valid_operation_id(&request.resolution_operation_id)
        || request.issue_operation_id == request.resolution_operation_id
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    if let UnknownIssueResolution::LeaseObserved {
        lease_id,
        lease_duration_seconds,
        ..
    } = &request.resolution
        && (!valid_lease_id(lease_id)
            || *lease_duration_seconds == 0
            || *lease_duration_seconds > MAX_LEASE_TTL_SECONDS)
    {
        return Err(SecretLeaseError::InvalidRequest);
    }
    Ok(())
}

fn require_matching_lease(
    registry: &SecretLeaseRegistry,
    lease_id: &str,
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
) -> Result<SecretLeaseMetadata, SecretLeaseError> {
    let lease = registry
        .lease(lease_id)?
        .ok_or(SecretLeaseError::LeaseNotFound)?;
    if lease.subject_id != subject_id
        || lease.consumer_id != consumer_id
        || lease.namespace != namespace
    {
        return Err(SecretLeaseError::LeaseIdentityMismatch);
    }
    Ok(lease)
}

fn provider_url(
    client: &BaoClient,
    mount: &str,
    path: &str,
) -> Result<url::Url, SecretLeaseError> {
    let mut url = client.origin.clone();
    {
        let mut segments = url
            .path_segments_mut()
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        segments.clear().push("v1");
        for part in mount.split('/') {
            segments.push(part);
        }
        for part in path.split('/') {
            segments.push(part);
        }
    }
    Ok(url)
}

fn system_url(client: &BaoClient, path: &[&str]) -> Result<url::Url, SecretLeaseError> {
    let mut url = client.origin.clone();
    {
        let mut segments = url
            .path_segments_mut()
            .map_err(|_| SecretLeaseError::InvalidRequest)?;
        segments.clear().push("v1");
        for part in path {
            segments.push(part);
        }
    }
    Ok(url)
}

fn token_header(client: &BaoClient) -> Result<HeaderValue, SecretLeaseError> {
    let mut token = HeaderValue::from_str(&client.token.0)
        .map_err(|_| SecretLeaseError::InvalidConfiguration)?;
    token.set_sensitive(true);
    Ok(token)
}

fn authenticated_get(
    client: &BaoClient,
    url: url::Url,
    namespace: &str,
) -> Result<codex_http_client::RequestBuilder, SecretLeaseError> {
    let mut request = client
        .client
        .get(url)
        .header("X-Vault-Token", token_header(client)?)
        .header("Accept", "application/json");
    if !namespace.is_empty() {
        request = request.header("X-Vault-Namespace", namespace);
    }
    Ok(request)
}

fn authenticated_post<T: serde::Serialize + ?Sized>(
    client: &BaoClient,
    url: url::Url,
    namespace: &str,
    body: &T,
) -> Result<codex_http_client::RequestBuilder, SecretLeaseError> {
    let mut request = client
        .client
        .post(url)
        .header("X-Vault-Token", token_header(client)?)
        .header("Accept", "application/json")
        .header("Content-Type", "application/json")
        .json(body);
    if !namespace.is_empty() {
        request = request.header("X-Vault-Namespace", namespace);
    }
    Ok(request)
}

async fn bounded_body(mut response: HttpResponse) -> Result<Zeroizing<Vec<u8>>, SecretLeaseError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(SecretLeaseError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
        if chunk.len() > MAX_RESPONSE_BYTES - body.len() {
            return Err(SecretLeaseError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn client_status_error(status: StatusCode) -> SecretLeaseError {
    match status {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => SecretLeaseError::ProviderDenied,
        StatusCode::NOT_FOUND => SecretLeaseError::NotFound,
        _ => SecretLeaseError::ProviderRejected,
    }
}

fn transport_error(error: HttpError) -> SecretLeaseError {
    if error.is_timeout() {
        SecretLeaseError::TimedOut
    } else {
        SecretLeaseError::TransportUnavailable
    }
}

fn now_ms() -> Result<u64, SecretLeaseError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SecretLeaseError::ClockUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| SecretLeaseError::ClockUnavailable)
}

fn expiry(now_ms: u64, ttl_seconds: u64) -> Result<u64, SecretLeaseError> {
    ttl_seconds
        .checked_mul(1000)
        .and_then(|delta| now_ms.checked_add(delta))
        .ok_or(SecretLeaseError::InvalidResponse)
}

fn revocation_observation(metadata: &SecretLeaseMetadata) -> RevocationObservation {
    RevocationObservation {
        lease_id: metadata.lease_id.clone(),
        state: metadata.state,
        observed_at_unix_ms: metadata.observed_at_unix_ms,
        provider_absent: metadata.state == SecretLeaseState::ProviderAbsent,
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

#[derive(Deserialize)]
struct LeaseLookupResponse {
    data: LeaseLookupData,
}

#[derive(Deserialize)]
struct LeaseLookupData {
    id: String,
    renewable: bool,
    ttl: u64,
}

#[cfg(all(test, unix))]
#[path = "lease_lifecycle_tests.rs"]
mod tests;
