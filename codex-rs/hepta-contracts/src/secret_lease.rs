//! Durable secret-lease lifecycle contract.
//!
//! This module contains metadata only. Raw secret material and provider tokens
//! are never fields of a lease record. The store boundary is deliberately CAS
//! based so a single-process SQLite owner and a future strongly-consistent
//! distributed owner can share the same transition rules.

use std::fmt;
use std::future::Future;
use std::pin::Pin;

use serde::Deserialize;
use serde::Serialize;

use crate::Sha256Digest;

pub const SECRET_LEASE_CONTRACT_SCHEMA_VERSION: u32 = 1;
pub const MAX_SECRET_LEASE_KEY_BYTES: usize = 256;
pub const MAX_SECRET_LEASE_PROVIDER_PATH_BYTES: usize = 2048;
pub const MAX_SECRET_LEASE_ERROR_CODE_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseOperation {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseState {
    Requesting,
    Active,
    Renewing,
    RevokePending,
    Revoked,
    Expired,
    Unknown,
    Rejected,
}

/// Secret-free durable owner record for one logical provider lease.
///
/// `provider_lease_id` is authority metadata rather than secret material, but
/// it is still redacted from `Debug` because it is a privileged revocation and
/// renewal handle.
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseRecord {
    pub schema_version: u32,
    pub lease_key: String,
    pub provider_id: String,
    pub provider_path: String,
    pub request_sha256: Sha256Digest,
    pub provider_lease_id: Option<String>,
    pub state: SecretLeaseState,
    pub renewable: bool,
    pub generation: u64,
    pub issued_at_ms: Option<u64>,
    pub expires_at_ms: Option<u64>,
    pub revision: u64,
    pub pending_operation: Option<SecretLeaseOperation>,
    pub pending_operation_id: Option<String>,
    pub pending_request_sha256: Option<Sha256Digest>,
    pub last_error_code: Option<String>,
}

impl fmt::Debug for SecretLeaseRecord {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SecretLeaseRecord")
            .field("schema_version", &self.schema_version)
            .field("lease_key", &self.lease_key)
            .field("provider_id", &self.provider_id)
            .field("provider_path", &self.provider_path)
            .field("request_sha256", &self.request_sha256)
            .field(
                "provider_lease_id",
                &self.provider_lease_id.as_ref().map(|_| "[REDACTED]"),
            )
            .field("state", &self.state)
            .field("renewable", &self.renewable)
            .field("generation", &self.generation)
            .field("issued_at_ms", &self.issued_at_ms)
            .field("expires_at_ms", &self.expires_at_ms)
            .field("revision", &self.revision)
            .field("pending_operation", &self.pending_operation)
            .field("pending_operation_id", &self.pending_operation_id)
            .field("pending_request_sha256", &self.pending_request_sha256)
            .field("last_error_code", &self.last_error_code)
            .finish()
    }
}

impl SecretLeaseRecord {
    pub fn requesting(
        lease_key: String,
        provider_id: String,
        provider_path: String,
        request_sha256: Sha256Digest,
        operation_id: String,
        operation_sha256: Sha256Digest,
    ) -> Result<Self, SecretLeaseBindingError> {
        let record = Self {
            schema_version: SECRET_LEASE_CONTRACT_SCHEMA_VERSION,
            lease_key,
            provider_id,
            provider_path,
            request_sha256,
            provider_lease_id: None,
            state: SecretLeaseState::Requesting,
            renewable: false,
            generation: 0,
            issued_at_ms: None,
            expires_at_ms: None,
            revision: 1,
            pending_operation: Some(SecretLeaseOperation::Issue),
            pending_operation_id: Some(operation_id),
            pending_request_sha256: Some(operation_sha256),
            last_error_code: None,
        };
        record.validate()?;
        Ok(record)
    }

    pub fn validate(&self) -> Result<(), SecretLeaseBindingError> {
        if self.schema_version != SECRET_LEASE_CONTRACT_SCHEMA_VERSION {
            return Err(SecretLeaseBindingError::SchemaVersion);
        }
        if !identifier(&self.lease_key, MAX_SECRET_LEASE_KEY_BYTES) {
            return Err(SecretLeaseBindingError::InvalidLeaseKey);
        }
        if !identifier(&self.provider_id, MAX_SECRET_LEASE_KEY_BYTES) {
            return Err(SecretLeaseBindingError::InvalidProvider);
        }
        if !provider_path(&self.provider_path) {
            return Err(SecretLeaseBindingError::InvalidProviderPath);
        }
        if self.revision == 0 {
            return Err(SecretLeaseBindingError::InvalidRevision);
        }
        if self
            .provider_lease_id
            .as_deref()
            .is_some_and(|value| !provider_lease_id(value))
        {
            return Err(SecretLeaseBindingError::InvalidProviderLeaseId);
        }
        if self
            .last_error_code
            .as_deref()
            .is_some_and(|value| !error_code(value))
        {
            return Err(SecretLeaseBindingError::InvalidErrorCode);
        }

        let pending_count = usize::from(self.pending_operation.is_some())
            + usize::from(self.pending_operation_id.is_some())
            + usize::from(self.pending_request_sha256.is_some());
        if pending_count != 0 && pending_count != 3 {
            return Err(SecretLeaseBindingError::IncompletePendingOperation);
        }
        if self
            .pending_operation_id
            .as_deref()
            .is_some_and(|value| !identifier(value, MAX_SECRET_LEASE_KEY_BYTES))
        {
            return Err(SecretLeaseBindingError::InvalidOperationId);
        }
        if let (Some(issued), Some(expires)) = (self.issued_at_ms, self.expires_at_ms)
            && expires <= issued
        {
            return Err(SecretLeaseBindingError::InvalidExpiry);
        }

        use SecretLeaseOperation as Operation;
        use SecretLeaseState as State;
        let valid = match self.state {
            State::Requesting => {
                self.provider_lease_id.is_none()
                    && self.generation == 0
                    && self.issued_at_ms.is_none()
                    && self.expires_at_ms.is_none()
                    && self.pending_operation == Some(Operation::Issue)
            }
            State::Active => {
                self.provider_lease_id.is_some()
                    && self.generation > 0
                    && self.issued_at_ms.is_some()
                    && self.expires_at_ms.is_some()
                    && self.pending_operation.is_none()
                    && self.pending_operation_id.is_none()
                    && self.pending_request_sha256.is_none()
            }
            State::Renewing => {
                self.provider_lease_id.is_some()
                    && self.generation > 0
                    && self.issued_at_ms.is_some()
                    && self.expires_at_ms.is_some()
                    && self.pending_operation == Some(Operation::Renew)
            }
            State::RevokePending => {
                self.provider_lease_id.is_some()
                    && self.generation > 0
                    && self.pending_operation == Some(Operation::Revoke)
            }
            State::Revoked | State::Expired => {
                self.provider_lease_id.is_some()
                    && self.generation > 0
                    && self.pending_operation.is_none()
                    && self.pending_operation_id.is_none()
                    && self.pending_request_sha256.is_none()
                    && !self.renewable
            }
            State::Unknown => self.pending_operation.is_some(),
            State::Rejected => {
                self.provider_lease_id.is_none()
                    && self.generation == 0
                    && self.pending_operation.is_none()
                    && self.pending_operation_id.is_none()
                    && self.pending_request_sha256.is_none()
                    && !self.renewable
            }
        };
        if valid {
            Ok(())
        } else {
            Err(SecretLeaseBindingError::InvalidStateShape)
        }
    }

    /// Validate an atomic CAS transition from a previously durable record.
    pub fn validate_transition_from(
        &self,
        previous: &Self,
    ) -> Result<(), SecretLeaseBindingError> {
        previous.validate()?;
        self.validate()?;
        if self.lease_key != previous.lease_key
            || self.provider_id != previous.provider_id
            || self.provider_path != previous.provider_path
            || self.request_sha256 != previous.request_sha256
        {
            return Err(SecretLeaseBindingError::IdentityDrift);
        }
        if self.revision != previous.revision.saturating_add(1) {
            return Err(SecretLeaseBindingError::InvalidRevision);
        }
        if previous.provider_lease_id.is_some()
            && self.provider_lease_id != previous.provider_lease_id
        {
            return Err(SecretLeaseBindingError::ProviderLeaseIdDrift);
        }

        use SecretLeaseOperation as Operation;
        use SecretLeaseState as State;
        let legal = match (previous.state, self.state) {
            (State::Requesting, State::Active) => {
                self.generation == 1 && self.provider_lease_id.is_some()
            }
            (State::Requesting, State::Unknown) => {
                self.generation == 0
                    && self.pending_operation == Some(Operation::Issue)
                    && self.provider_lease_id.is_none()
            }
            (State::Requesting, State::Rejected) => self.generation == 0,
            (State::Active, State::Renewing) => {
                self.generation == previous.generation
                    && self.pending_operation == Some(Operation::Renew)
            }
            (State::Active, State::RevokePending) => {
                self.generation == previous.generation
                    && self.pending_operation == Some(Operation::Revoke)
            }
            (State::Active, State::Expired) => self.generation == previous.generation,
            (State::Renewing, State::Active) => self.generation == previous.generation + 1,
            (State::Renewing, State::Unknown) => {
                self.generation == previous.generation
                    && self.pending_operation == Some(Operation::Renew)
            }
            (State::Renewing, State::Expired) => self.generation == previous.generation,
            (State::RevokePending, State::Revoked) => self.generation == previous.generation,
            (State::RevokePending, State::Unknown) => {
                self.generation == previous.generation
                    && self.pending_operation == Some(Operation::Revoke)
            }
            (State::Unknown, State::Active) => match previous.pending_operation {
                Some(Operation::Issue) => {
                    self.generation == 1 && self.provider_lease_id.is_some()
                }
                Some(Operation::Renew) => self.generation == previous.generation + 1,
                Some(Operation::Revoke) | None => false,
            },
            (State::Unknown, State::Revoked) => {
                previous.pending_operation == Some(Operation::Revoke)
                    && self.generation == previous.generation
            }
            (State::Unknown, State::Expired) => {
                previous.pending_operation != Some(Operation::Issue)
                    && self.generation == previous.generation
            }
            (State::Unknown, State::Rejected) => {
                previous.pending_operation == Some(Operation::Issue) && self.generation == 0
            }
            _ => false,
        };
        if legal {
            Ok(())
        } else {
            Err(SecretLeaseBindingError::InvalidTransition)
        }
    }

    pub const fn is_terminal(&self) -> bool {
        matches!(
            self.state,
            SecretLeaseState::Revoked | SecretLeaseState::Expired | SecretLeaseState::Rejected
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseBindingError {
    SchemaVersion,
    InvalidLeaseKey,
    InvalidProvider,
    InvalidProviderPath,
    InvalidProviderLeaseId,
    InvalidOperationId,
    InvalidErrorCode,
    InvalidRevision,
    InvalidExpiry,
    IncompletePendingOperation,
    InvalidStateShape,
    IdentityDrift,
    ProviderLeaseIdDrift,
    InvalidTransition,
}

impl fmt::Display for SecretLeaseBindingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for SecretLeaseBindingError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecretLeaseStoreError {
    InvalidRecord(SecretLeaseBindingError),
    AlreadyExists,
    NotFound,
    StaleRevision,
    Conflict,
    Unavailable,
    Corrupt,
}

impl fmt::Display for SecretLeaseStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for SecretLeaseStoreError {}

pub type SecretLeaseFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, SecretLeaseStoreError>> + Send + 'a>>;

/// Strong-CAS metadata owner required by the lease adapter.
///
/// Implementations must make `create` exact-idempotent and
/// `compare_and_swap` linearizable for one `lease_key`. A local SQLite
/// implementation is provided by `codex-hepta-evidence`; active-active
/// multi-host deployments require an equivalent strongly-consistent backend.
pub trait SecretLeaseStore: Send + Sync {
    fn load<'a>(&'a self, lease_key: &'a str)
        -> SecretLeaseFuture<'a, Option<SecretLeaseRecord>>;

    fn create<'a>(&'a self, record: &'a SecretLeaseRecord) -> SecretLeaseFuture<'a, ()>;

    fn compare_and_swap<'a>(
        &'a self,
        expected_revision: u64,
        next: &'a SecretLeaseRecord,
    ) -> SecretLeaseFuture<'a, ()>;
}

fn identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn provider_path(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_SECRET_LEASE_PROVIDER_PATH_BYTES
        && !value.starts_with('/')
        && !value.ends_with('/')
        && value
            .split('/')
            .all(|segment| identifier(segment, MAX_SECRET_LEASE_KEY_BYTES) && segment != "." && segment != "..")
}

fn provider_lease_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_SECRET_LEASE_PROVIDER_PATH_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !matches!(byte, b'?' | b'#'))
}

fn error_code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_SECRET_LEASE_ERROR_CODE_BYTES
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Sha256Digest {
        Sha256Digest::for_bytes(value)
    }

    fn requesting() -> SecretLeaseRecord {
        SecretLeaseRecord::requesting(
            "lease:one".into(),
            "provider:heptabao".into(),
            "database/creds/reader".into(),
            digest(b"logical"),
            "operation:issue:1".into(),
            digest(b"issue"),
        )
        .unwrap()
    }

    #[test]
    fn requesting_to_active_then_renewing_is_valid() {
        let request = requesting();
        let active = SecretLeaseRecord {
            schema_version: 1,
            lease_key: request.lease_key.clone(),
            provider_id: request.provider_id.clone(),
            provider_path: request.provider_path.clone(),
            request_sha256: request.request_sha256.clone(),
            provider_lease_id: Some("database/creds/reader/abc".into()),
            state: SecretLeaseState::Active,
            renewable: true,
            generation: 1,
            issued_at_ms: Some(100),
            expires_at_ms: Some(1_100),
            revision: 2,
            pending_operation: None,
            pending_operation_id: None,
            pending_request_sha256: None,
            last_error_code: None,
        };
        active.validate_transition_from(&request).unwrap();

        let renewing = SecretLeaseRecord {
            state: SecretLeaseState::Renewing,
            revision: 3,
            pending_operation: Some(SecretLeaseOperation::Renew),
            pending_operation_id: Some("operation:renew:1".into()),
            pending_request_sha256: Some(digest(b"renew")),
            ..active.clone()
        };
        renewing.validate_transition_from(&active).unwrap();
    }

    #[test]
    fn unknown_issue_cannot_be_blindly_retried_as_requesting() {
        let request = requesting();
        let unknown = SecretLeaseRecord {
            state: SecretLeaseState::Unknown,
            revision: 2,
            last_error_code: Some("transport_unknown".into()),
            ..request.clone()
        };
        unknown.validate_transition_from(&request).unwrap();
        let retry = SecretLeaseRecord {
            revision: 3,
            ..request
        };
        assert_eq!(
            retry.validate_transition_from(&unknown),
            Err(SecretLeaseBindingError::InvalidTransition)
        );
    }

    #[test]
    fn provider_lease_identity_is_immutable_once_observed() {
        let request = requesting();
        let active = SecretLeaseRecord {
            provider_lease_id: Some("database/creds/reader/abc".into()),
            state: SecretLeaseState::Active,
            renewable: true,
            generation: 1,
            issued_at_ms: Some(100),
            expires_at_ms: Some(1_100),
            revision: 2,
            pending_operation: None,
            pending_operation_id: None,
            pending_request_sha256: None,
            ..request.clone()
        };
        active.validate_transition_from(&request).unwrap();
        let drift = SecretLeaseRecord {
            provider_lease_id: Some("database/creds/reader/other".into()),
            state: SecretLeaseState::Renewing,
            revision: 3,
            pending_operation: Some(SecretLeaseOperation::Renew),
            pending_operation_id: Some("operation:renew:1".into()),
            pending_request_sha256: Some(digest(b"renew")),
            ..active.clone()
        };
        assert_eq!(
            drift.validate_transition_from(&active),
            Err(SecretLeaseBindingError::ProviderLeaseIdDrift)
        );
    }
}
