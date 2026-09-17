use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseError;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

pub const SECRET_LEASE_SCHEMA_VERSION: u32 = 1;
pub const MAX_DYNAMIC_SECRET_FIELDS: usize = 32;
pub const MAX_PROVIDER_LEASE_ID_BYTES: usize = 4096;
pub const MAX_LEASE_OPERATION_ID_BYTES: usize = 128;
pub const MAX_LEASE_TTL_SECONDS: u64 = 31_536_000;
pub(crate) const MAX_LEASE_REGISTRY_BYTES: u64 = 8 * 1024 * 1024;
pub(crate) const MAX_LEASE_RECORDS: usize = 4096;
pub(crate) const MAX_LEASE_OPERATIONS: usize = 8192;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DynamicSecretLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub mount: String,
    /// Provider-native read path under `mount`, for example `creds/readonly`.
    pub path: String,
    /// Exact string-valued fields that may cross the final trusted-consumer boundary.
    pub secret_fields: Vec<String>,
    /// Local policy ceiling. Provider responses above this TTL are never delivered.
    pub max_lease_duration_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseRenewRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
    /// OpenBao semantics: requested remaining TTL from now; zero asks for provider default.
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseRevokeRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseReconcileRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub namespace: String,
    pub lease_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UnknownIssueResolution {
    /// Independent provider/audit inspection established that no lease was created.
    NoLeaseObserved,
    /// Independent provider/audit inspection found the external lease. Because its raw
    /// material was not durably delivered by this process, it is adopted only as
    /// `RevokeRequired` and can never become an active consumable lease locally.
    LeaseObserved {
        lease_id: String,
        lease_duration_seconds: u64,
        renewable: bool,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UnknownIssueResolutionRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub issue_operation_id: String,
    pub resolution_operation_id: String,
    pub resolution: UnknownIssueResolution,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseState {
    Active,
    RenewOutcomeUnknown,
    RevokeOutcomeUnknown,
    RevokeRequired,
    Revoked,
    ProviderAbsent,
}

impl SecretLeaseState {
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Revoked | Self::ProviderAbsent)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadata {
    pub schema_version: u32,
    pub lease_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub issued_operation_id: String,
    pub last_operation_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub secret_fields: Vec<String>,
    pub renewable: bool,
    pub lease_duration_seconds: u64,
    pub max_lease_duration_seconds: u64,
    pub observed_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub rotation_generation: u64,
    pub state: SecretLeaseState,
    pub request_sha256: [u8; 32],
    pub scope_sha256: [u8; 32],
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationKind {
    Issue,
    Renew,
    Revoke,
    Reconcile,
    ResolveUnknownIssue,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationState {
    OutcomeUnknown,
    Completed,
    Rejected,
    ResolvedNoLease,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseOperationObservation {
    pub operation_id: String,
    pub kind: LeaseOperationKind,
    pub state: LeaseOperationState,
    pub lease_id: Option<String>,
    pub request_sha256: [u8; 32],
    pub updated_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RevocationObservation {
    pub lease_id: String,
    pub state: SecretLeaseState,
    pub observed_at_unix_ms: u64,
    pub provider_absent: bool,
}

/// Raw dynamic values are deliberately non-cloneable and non-serializable. They exist only
/// while the trusted final consumer callback is executing. Debug never reveals field values.
pub struct DynamicSecretValues {
    values: BTreeMap<String, Zeroizing<String>>,
}

impl DynamicSecretValues {
    pub(crate) fn from_map(values: BTreeMap<String, Zeroizing<String>>) -> Self {
        Self { values }
    }

    pub fn field_count(&self) -> usize {
        self.values.len()
    }

    pub fn contains_field(&self, name: &str) -> bool {
        self.values.contains_key(name)
    }

    pub fn field_names(&self) -> impl Iterator<Item = &str> {
        self.values.keys().map(String::as_str)
    }

    pub fn with_field<T>(&self, name: &str, use_value: impl FnOnce(&[u8]) -> T) -> Option<T> {
        self.values
            .get(name)
            .map(|value| use_value(value.as_bytes()))
    }
}

impl fmt::Debug for DynamicSecretValues {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DynamicSecretValues")
            .field("fields", &self.values.keys().collect::<Vec<_>>())
            .field("values", &"[REDACTED]")
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseError {
    InvalidConfiguration,
    InvalidRequest,
    Authority(FinalUseError),
    ProviderDenied,
    ProviderRejected,
    ProviderUnavailable,
    NotFound,
    TransportUnavailable,
    TimedOut,
    ResponseTooLarge,
    InvalidResponse,
    ConsumerIndeterminate,
    OutcomeIndeterminate,
    ReconciliationRequired,
    OperationConflict,
    OperationAlreadyCompleted,
    OperationAlreadyTerminal,
    LeaseNotFound,
    LeaseNotRenewable,
    LeaseNotActive,
    LeaseIdentityMismatch,
    LeaseDurationExceeded,
    StateDirectoryUnsafe,
    StateLocked,
    StateUnavailable,
    StateCorrupt,
    CapacityExceeded,
    Storage,
    ClockUnavailable,
}

impl fmt::Display for SecretLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SecretLeaseError {}

pub(crate) fn valid_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

pub(crate) fn valid_segmented(value: &str) -> bool {
    value.len() <= 1024 && value.split('/').all(valid_component)
}

pub(crate) fn valid_namespace(value: &str) -> bool {
    value.is_empty() || valid_segmented(value)
}

pub(crate) fn valid_operation_id(value: &str) -> bool {
    value.len() <= MAX_LEASE_OPERATION_ID_BYTES && valid_component(value)
}

pub(crate) fn valid_lease_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_PROVIDER_LEASE_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_graphic() && !byte.is_ascii_control())
}

pub(crate) fn normalized_secret_fields(fields: &[String]) -> Option<Vec<String>> {
    if fields.is_empty() || fields.len() > MAX_DYNAMIC_SECRET_FIELDS {
        return None;
    }
    let mut normalized = fields.to_vec();
    if normalized.iter().any(|field| !valid_component(field)) {
        return None;
    }
    normalized.sort();
    normalized.dedup();
    if normalized.len() != fields.len() {
        return None;
    }
    Some(normalized)
}
