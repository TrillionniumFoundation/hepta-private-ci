//! Dynamic HeptaBao secret-lease lifecycle.
//!
//! These APIs deliberately keep provider lease identifiers opaque, never
//! return secret payloads, and classify transport ambiguity as indeterminate.
//! An indeterminate operation MUST NOT be blindly retried.  The caller must
//! reconcile it with a provider-owned observation or operator workflow.

use std::collections::BTreeMap;
use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use http::Method;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

use crate::BaoClient;
use crate::BaoClientError;

const MAX_DYNAMIC_SECRET_BYTES: usize = 1024 * 1024;
const MAX_INCREMENT_SECONDS: u64 = 7 * 24 * 60 * 60;

/// One dynamic provider role and caller-owned occurrence identity.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub mount: String,
    pub role: String,
}

/// Renewal request for one already-issued opaque lease.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseRenewRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub increment_seconds: u64,
}

/// Revocation request for one already-issued opaque lease.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseRevokeRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
}

/// Provider lease identifier retained only by the trusted host boundary.
pub struct SecretLeaseHandle(Zeroizing<String>);

impl SecretLeaseHandle {
    pub fn lease_id_sha256(&self) -> [u8; 32] {
        Digest32::of_bytes(self.0.as_bytes()).into_array()
    }
}

impl fmt::Debug for SecretLeaseHandle {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("SecretLeaseHandle([REDACTED])")
    }
}

/// Secret-free lease metadata safe for receipts and status surfaces.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseMetadata {
    pub lease_id_sha256: [u8; 32],
    pub operation_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub secret_bytes: usize,
}

/// Issuance returned a known lease but final secret delivery was fenced.
///
/// The host MUST retain the handle and reconcile/revoke the lease; it must not
/// drop this result and issue a replacement lease blindly.
#[derive(Debug)]
pub struct SecretLeaseDeliveryBlocked {
    pub handle: SecretLeaseHandle,
    pub metadata: SecretLeaseMetadata,
    pub authority_error: FinalUseError,
}

#[derive(Debug)]
pub enum SecretLeaseIssueOutcome {
    Delivered {
        handle: SecretLeaseHandle,
        metadata: SecretLeaseMetadata,
    },
    DeliveryBlocked(SecretLeaseDeliveryBlocked),
    Rejected,
    /// The request may have reached the provider but no lease identity is
    /// available locally.  Generic OpenBao dynamic-credential issuance does
    /// not provide an operation-id status lookup, so blind retry is forbidden.
    Indeterminate {
        operation_sha256: [u8; 32],
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseRenewal {
    pub lease_id_sha256: [u8; 32],
    pub operation_sha256: [u8; 32],
    pub observed_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseRevocation {
    pub lease_id_sha256: [u8; 32],
    pub operation_sha256: [u8; 32],
    pub observed_at_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecretLeaseMutationOutcome<T> {
    Applied(T),
    Rejected,
    /// Provider application is unknown. Never convert this to a retry without
    /// an authoritative provider observation.
    Indeterminate {
        operation_sha256: [u8; 32],
    },
}

impl BaoClient {
    /// Build the exact authority proposal for one dynamic lease issuance.
    pub fn secret_lease_binding(
        &self,
        request: &SecretLeaseRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_issue_request(request)?;
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.secret-lease.issue.v1",
            self.origin.as_str(),
            self.ca_sha256,
            request,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.secret-lease.scope.v1",
            self.origin.as_str(),
            &request.namespace,
            &request.mount,
            &request.role,
            &request.consumer_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let operation = operation_digest("issue", &request.operation_id, &request_bytes);
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            // Dynamic secret bytes are not knowable before dispatch.  The
            // signed payload digest therefore binds the exact issuance
            // operation rather than pretending to predict provider output.
            payload_sha256: operation,
        })
    }

    /// Issue one provider-native dynamic secret lease.
    ///
    /// The kernel claim is the dispatch-admission point.  The resulting secret
    /// is delivered only after a second live authority check.  If that final
    /// check fails, the known lease handle is returned in DeliveryBlocked so
    /// the host can revoke/reconcile it instead of orphaning a credential.
    pub async fn request_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &SecretLeaseRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<SecretLeaseIssueOutcome, BaoClientError> {
        let binding = self.secret_lease_binding(request)?;
        let operation_sha256 = binding.payload_sha256;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;

        let mut url = self.origin.clone();
        {
            let mut parts = url
                .path_segments_mut()
                .map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in request.mount.split('/') {
                parts.push(part);
            }
            parts.push("creds");
            for part in request.role.split('/') {
                parts.push(part);
            }
        }
        let mut network_request = self
            .client
            .get(url)
            .header("X-Vault-Token", self.sensitive_token_header()?)
            .header("Accept", "application/json");
        if !request.namespace.is_empty() {
            network_request =
                network_request.header("X-Vault-Namespace", &request.namespace);
        }

        let mut response = match network_request.send().await {
            Ok(response) => response,
            Err(error) if error.is_timeout() => {
                return Ok(SecretLeaseIssueOutcome::Indeterminate {
                    operation_sha256,
                });
            }
            Err(_) => {
                return Ok(SecretLeaseIssueOutcome::Indeterminate {
                    operation_sha256,
                });
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED
            | StatusCode::FORBIDDEN
            | StatusCode::BAD_REQUEST
            | StatusCode::NOT_FOUND => return Ok(SecretLeaseIssueOutcome::Rejected),
            _ if response.status().is_server_error() => {
                return Ok(SecretLeaseIssueOutcome::Indeterminate {
                    operation_sha256,
                });
            }
            _ => return Err(BaoClientError::InvalidResponse),
        }

        let body = read_bounded_body(&mut response).await?;
        let decoded: DynamicLeaseResponse =
            serde_json::from_slice(&body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.lease_id.is_empty() || decoded.lease_duration == 0 {
            return Err(BaoClientError::InvalidResponse);
        }
        let issued_at_unix_ms = now_unix_ms()?;
        let expires_at_unix_ms = issued_at_unix_ms
            .checked_add(
                decoded
                    .lease_duration
                    .checked_mul(1000)
                    .ok_or(BaoClientError::InvalidResponse)?,
            )
            .ok_or(BaoClientError::InvalidResponse)?;
        let secret = Zeroizing::new(
            serde_json::to_vec(&decoded.data).map_err(|_| BaoClientError::InvalidResponse)?,
        );
        let handle = SecretLeaseHandle(decoded.lease_id);
        let metadata = SecretLeaseMetadata {
            lease_id_sha256: handle.lease_id_sha256(),
            operation_sha256,
            secret_sha256: Digest32::of_bytes(&secret).into_array(),
            issued_at_unix_ms,
            expires_at_unix_ms,
            renewable: decoded.renewable,
            secret_bytes: secret.len(),
        };

        match authority.with_verified_use(verified, &binding, || consumer(&secret)) {
            Ok(Ok(())) => Ok(SecretLeaseIssueOutcome::Delivered { handle, metadata }),
            Ok(Err(())) => Err(BaoClientError::ConsumerIndeterminate),
            Err(authority_error) => Ok(SecretLeaseIssueOutcome::DeliveryBlocked(
                SecretLeaseDeliveryBlocked {
                    handle,
                    metadata,
                    authority_error,
                },
            )),
        }
    }

    pub fn secret_lease_renew_binding(
        &self,
        handle: &SecretLeaseHandle,
        request: &SecretLeaseRenewRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
        )?;
        if request.increment_seconds == 0
            || request.increment_seconds > MAX_INCREMENT_SECONDS
            || (!request.namespace.is_empty() && !segmented(&request.namespace))
        {
            return Err(BaoClientError::InvalidRequest);
        }
        mutation_binding(
            self,
            "renew",
            handle,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.namespace,
            Some(request.increment_seconds),
        )
    }

    pub async fn renew_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        handle: &SecretLeaseHandle,
        request: &SecretLeaseRenewRequest,
    ) -> Result<SecretLeaseMutationOutcome<SecretLeaseRenewal>, BaoClientError> {
        let binding = self.secret_lease_renew_binding(handle, request)?;
        let operation_sha256 = binding.payload_sha256;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(BaoClientError::Authority)?;

        let url = self.system_lease_url("renew")?;
        let payload = LeaseRenewPayload {
            lease_id: &handle.0,
            increment: request.increment_seconds,
        };
        let mut network_request = self
            .client
            .request(Method::PUT, url)
            .header("X-Vault-Token", self.sensitive_token_header()?)
            .header("Accept", "application/json")
            .json(&payload);
        if !request.namespace.is_empty() {
            network_request =
                network_request.header("X-Vault-Namespace", &request.namespace);
        }
        let mut response = match network_request.send().await {
            Ok(response) => response,
            Err(_) => {
                return Ok(SecretLeaseMutationOutcome::Indeterminate {
                    operation_sha256,
                });
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED
            | StatusCode::FORBIDDEN
            | StatusCode::BAD_REQUEST
            | StatusCode::NOT_FOUND => return Ok(SecretLeaseMutationOutcome::Rejected),
            _ if response.status().is_server_error() => {
                return Ok(SecretLeaseMutationOutcome::Indeterminate {
                    operation_sha256,
                });
            }
            _ => return Err(BaoClientError::InvalidResponse),
        }
        let body = read_bounded_body(&mut response).await?;
        let decoded: LeaseRenewResponse =
            serde_json::from_slice(&body).map_err(|_| BaoClientError::InvalidResponse)?;
        if decoded.lease_duration == 0 {
            return Err(BaoClientError::InvalidResponse);
        }
        let observed_at_unix_ms = now_unix_ms()?;
        let expires_at_unix_ms = observed_at_unix_ms
            .checked_add(
                decoded
                    .lease_duration
                    .checked_mul(1000)
                    .ok_or(BaoClientError::InvalidResponse)?,
            )
            .ok_or(BaoClientError::InvalidResponse)?;
        Ok(SecretLeaseMutationOutcome::Applied(SecretLeaseRenewal {
            lease_id_sha256: handle.lease_id_sha256(),
            operation_sha256,
            observed_at_unix_ms,
            expires_at_unix_ms,
            renewable: decoded.renewable,
        }))
    }

    pub fn secret_lease_revoke_binding(
        &self,
        handle: &SecretLeaseHandle,
        request: &SecretLeaseRevokeRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_mutation_request(
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
        )?;
        if !request.namespace.is_empty() && !segmented(&request.namespace) {
            return Err(BaoClientError::InvalidRequest);
        }
        mutation_binding(
            self,
            "revoke",
            handle,
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.namespace,
            None,
        )
    }

    pub async fn revoke_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        handle: &SecretLeaseHandle,
        request: &SecretLeaseRevokeRequest,
    ) -> Result<SecretLeaseMutationOutcome<SecretLeaseRevocation>, BaoClientError> {
        let binding = self.secret_lease_revoke_binding(handle, request)?;
        let operation_sha256 = binding.payload_sha256;
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        authority
            .with_verified_use(verified, &binding, || ())
            .map_err(BaoClientError::Authority)?;

        let url = self.system_lease_url("revoke")?;
        let payload = LeaseRevokePayload {
            lease_id: &handle.0,
        };
        let mut network_request = self
            .client
            .request(Method::PUT, url)
            .header("X-Vault-Token", self.sensitive_token_header()?)
            .header("Accept", "application/json")
            .json(&payload);
        if !request.namespace.is_empty() {
            network_request =
                network_request.header("X-Vault-Namespace", &request.namespace);
        }
        let response = match network_request.send().await
        {
            Ok(response) => response,
            Err(_) => {
                return Ok(SecretLeaseMutationOutcome::Indeterminate {
                    operation_sha256,
                });
            }
        };
        match response.status() {
            StatusCode::NO_CONTENT | StatusCode::OK => {
                Ok(SecretLeaseMutationOutcome::Applied(SecretLeaseRevocation {
                    lease_id_sha256: handle.lease_id_sha256(),
                    operation_sha256,
                    observed_at_unix_ms: now_unix_ms()?,
                }))
            }
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN | StatusCode::BAD_REQUEST => {
                Ok(SecretLeaseMutationOutcome::Rejected)
            }
            StatusCode::NOT_FOUND => {
                // A known lease that is already absent is observationally
                // revoked for the host lifecycle; do not create a retry loop.
                Ok(SecretLeaseMutationOutcome::Applied(SecretLeaseRevocation {
                    lease_id_sha256: handle.lease_id_sha256(),
                    operation_sha256,
                    observed_at_unix_ms: now_unix_ms()?,
                }))
            }
            status if status.is_server_error() => {
                Ok(SecretLeaseMutationOutcome::Indeterminate {
                    operation_sha256,
                })
            }
            _ => Err(BaoClientError::InvalidResponse),
        }
    }

    fn sensitive_token_header(&self) -> Result<HeaderValue, BaoClientError> {
        let mut token = HeaderValue::from_str(&self.token.0)
            .map_err(|_| BaoClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        Ok(token)
    }

    fn system_lease_url(&self, operation: &str) -> Result<url::Url, BaoClientError> {
        let mut url = self.origin.clone();
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoClientError::InvalidRequest)?;
        parts.clear().push("v1").push("sys").push("leases").push(operation);
        drop(parts);
        Ok(url)
    }
}

fn mutation_binding(
    client: &BaoClient,
    operation: &str,
    handle: &SecretLeaseHandle,
    subject_id: &str,
    consumer_id: &str,
    operation_id: &str,
    namespace: &str,
    increment_seconds: Option<u64>,
) -> Result<FinalUseBinding, BaoClientError> {
    let request_bytes = serde_json::to_vec(&(
        "hepta.bao.secret-lease.mutation.v1",
        operation,
        client.origin.as_str(),
        client.ca_sha256,
        handle.lease_id_sha256(),
        operation_id,
        namespace,
        increment_seconds,
    ))
    .map_err(|_| BaoClientError::InvalidRequest)?;
    let scope = serde_json::to_vec(&(
        "hepta.bao.secret-lease.mutation-scope.v1",
        client.origin.as_str(),
        handle.lease_id_sha256(),
        namespace,
        consumer_id,
    ))
    .map_err(|_| BaoClientError::InvalidRequest)?;
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id: "provider:heptabao".to_owned(),
        request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
        scope_sha256: Digest32::of_bytes(&scope).into_array(),
        payload_sha256: operation_digest(operation, operation_id, &request_bytes),
    })
}

fn operation_digest(operation: &str, operation_id: &str, request_bytes: &[u8]) -> [u8; 32] {
    let mut bytes = b"hepta.bao.secret-lease.operation.v1\0".to_vec();
    bytes.extend_from_slice(operation.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(operation_id.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(request_bytes);
    Digest32::of_bytes(&bytes).into_array()
}

fn validate_issue_request(request: &SecretLeaseRequest) -> Result<(), BaoClientError> {
    validate_mutation_request(
        &request.subject_id,
        &request.consumer_id,
        &request.operation_id,
    )?;
    if (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.mount)
        || !segmented(&request.role)
    {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn validate_mutation_request(
    subject_id: &str,
    consumer_id: &str,
    operation_id: &str,
) -> Result<(), BaoClientError> {
    if !component(subject_id) || !component(consumer_id) || !component(operation_id) {
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
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
}

fn segmented(value: &str) -> bool {
    value.len() <= 1024 && value.split('/').all(component)
}

async fn read_bounded_body(
    response: &mut codex_http_client::HttpResponse,
) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_DYNAMIC_SECRET_BYTES as u64)
    {
        return Err(BaoClientError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| if error.is_timeout() {
            BaoClientError::TimedOut
        } else {
            BaoClientError::TransportUnavailable
        })?
    {
        if chunk.len() > MAX_DYNAMIC_SECRET_BYTES - body.len() {
            return Err(BaoClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn now_unix_ms() -> Result<u64, BaoClientError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| BaoClientError::InvalidResponse)?
        .as_millis();
    u64::try_from(millis).map_err(|_| BaoClientError::InvalidResponse)
}

#[derive(Deserialize)]
struct DynamicLeaseResponse {
    lease_id: Zeroizing<String>,
    renewable: bool,
    lease_duration: u64,
    data: BTreeMap<String, Zeroizing<String>>,
}

#[derive(Serialize)]
struct LeaseRenewPayload<'a> {
    lease_id: &'a str,
    increment: u64,
}

#[derive(Deserialize)]
struct LeaseRenewResponse {
    renewable: bool,
    lease_duration: u64,
}

#[derive(Serialize)]
struct LeaseRevokePayload<'a> {
    lease_id: &'a str,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opaque_handle_debug_and_metadata_do_not_expose_lease_id() {
        let handle = SecretLeaseHandle(Zeroizing::new(
            "database/creds/read-only/sensitive-provider-id".to_owned(),
        ));
        assert_eq!(format!("{handle:?}"), "SecretLeaseHandle([REDACTED])");
        assert_ne!(handle.lease_id_sha256(), [0; 32]);
    }

    #[test]
    fn mutation_operation_digest_changes_with_occurrence_identity() {
        let first = operation_digest("renew", "operation-one", b"same-request");
        let second = operation_digest("renew", "operation-two", b"same-request");
        assert_ne!(first, second);
    }

    #[test]
    fn issue_request_rejects_unbounded_or_path_escape_components() {
        let request = SecretLeaseRequest {
            subject_id: "agent-one".into(),
            consumer_id: "provider".into(),
            operation_id: "op-1".into(),
            namespace: String::new(),
            mount: "database".into(),
            role: "../admin".into(),
        };
        assert_eq!(
            validate_issue_request(&request),
            Err(BaoClientError::InvalidRequest)
        );
    }
}
