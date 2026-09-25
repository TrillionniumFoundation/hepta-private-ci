//! Durable metadata-only SecretLease lifecycle owner.
//!
//! This module deliberately stores no secret value. Provider effects are
//! represented as observations so a timeout/crash can remain Unknown until a
//! trusted reconciler observes the original operation.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

const SCHEMA_VERSION: u32 = 1;
const MAX_RECORDS: usize = 65_536;
const MAX_METADATA_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationKindV1 {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationStateV1 {
    Prepared,
    Unknown,
    Applied,
    Denied,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseStateV1 {
    Active,
    RenewUnknown,
    RevokeUnknown,
    Revoked,
    Expired,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadataV1 {
    pub lease_id: String,
    pub secret_reference_id: String,
    pub consumer_id: String,
    pub scope_sha256: [u8; 32],
    pub provider_metadata_sha256: [u8; 32],
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub generation: u64,
    pub state: SecretLeaseStateV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseOperationV1 {
    pub operation_id: String,
    pub kind: LeaseOperationKindV1,
    pub semantic_sha256: [u8; 32],
    pub lease_id: Option<String>,
    pub state: LeaseOperationStateV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum ProviderLeaseObservationV1 {
    IssueApplied {
        lease: SecretLeaseMetadataV1,
    },
    RenewApplied {
        lease_id: String,
        observed_at_unix_ms: u64,
        expires_at_unix_ms: u64,
        renewable: bool,
        provider_metadata_sha256: [u8; 32],
    },
    RevokeApplied {
        lease_id: String,
        observed_at_unix_ms: u64,
        provider_metadata_sha256: [u8; 32],
    },
    Denied,
    NotApplied,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredRegistryV1 {
    schema_version: u32,
    operations: BTreeMap<String, LeaseOperationV1>,
    leases: BTreeMap<String, SecretLeaseMetadataV1>,
}

pub struct DurableLeaseRegistryV1 {
    path: PathBuf,
    state: StoredRegistryV1,
}

impl std::fmt::Debug for DurableLeaseRegistryV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DurableLeaseRegistryV1")
            .field("path", &self.path)
            .field("operation_count", &self.state.operations.len())
            .field("lease_count", &self.state.leases.len())
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseRegistryErrorV1 {
    InvalidInput,
    CapacityExceeded,
    OperationConflict,
    OperationNotFound,
    LeaseNotFound,
    InvalidTransition,
    ObservationMismatch,
    CorruptState,
    Unavailable,
}

impl std::fmt::Display for LeaseRegistryErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for LeaseRegistryErrorV1 {}

impl DurableLeaseRegistryV1 {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, LeaseRegistryErrorV1> {
        let path = path.into();
        let state = if path.exists() {
            let mut bytes = Vec::new();
            File::open(&path)
                .and_then(|file| file.take(8 * 1024 * 1024 + 1).read_to_end(&mut bytes))
                .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
            if bytes.len() > 8 * 1024 * 1024 {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            let state: StoredRegistryV1 =
                serde_json::from_slice(&bytes).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
            validate_state(&state)?;
            state
        } else {
            StoredRegistryV1 {
                schema_version: SCHEMA_VERSION,
                operations: BTreeMap::new(),
                leases: BTreeMap::new(),
            }
        };
        Ok(Self { path, state })
    }

    pub fn lease(&self, lease_id: &str) -> Option<&SecretLeaseMetadataV1> {
        self.state.leases.get(lease_id)
    }

    pub fn operation(&self, operation_id: &str) -> Option<&LeaseOperationV1> {
        self.state.operations.get(operation_id)
    }

    pub fn prepare_issue(
        &mut self,
        operation_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.prepare(
            operation_id,
            LeaseOperationKindV1::Issue,
            semantic_sha256,
            None,
        )
    }

    pub fn prepare_renew(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.require_active(&lease_id)?;
        self.prepare(
            operation_id,
            LeaseOperationKindV1::Renew,
            semantic_sha256,
            Some(lease_id),
        )
    }

    pub fn prepare_revoke(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        let lease = self
            .state
            .leases
            .get(&lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if matches!(
            lease.state,
            SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        self.prepare(
            operation_id,
            LeaseOperationKindV1::Revoke,
            semantic_sha256,
            Some(lease_id),
        )
    }

    pub fn mark_unknown(
        &mut self,
        operation_id: &str,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        let mut next = self.state.clone();
        let operation = next
            .operations
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if !matches!(
            operation.state,
            LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        operation.state = LeaseOperationStateV1::Unknown;
        if let Some(lease_id) = operation.lease_id.as_ref()
            && let Some(lease) = next.leases.get_mut(lease_id)
        {
            if matches!(
                lease.state,
                SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
            ) || (operation.kind == LeaseOperationKindV1::Renew
                && lease.state == SecretLeaseStateV1::RevokeUnknown)
            {
                return Err(LeaseRegistryErrorV1::InvalidTransition);
            }
            lease.state = match operation.kind {
                LeaseOperationKindV1::Renew => SecretLeaseStateV1::RenewUnknown,
                LeaseOperationKindV1::Revoke => SecretLeaseStateV1::RevokeUnknown,
                LeaseOperationKindV1::Issue => lease.state,
            };
        }
        self.commit(next)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub fn reconcile(
        &mut self,
        operation_id: &str,
        observation: ProviderLeaseObservationV1,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        let current = self
            .state
            .operations
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if !matches!(
            current.state,
            LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }

        let mut next = self.state.clone();
        match (&current.kind, observation) {
            (LeaseOperationKindV1::Issue, ProviderLeaseObservationV1::IssueApplied { lease }) => {
                validate_lease_metadata(&lease)?;
                // New issuance is active-only; persisted lifecycle states are not.
                if lease.state != SecretLeaseStateV1::Active {
                    return Err(LeaseRegistryErrorV1::InvalidInput);
                }
                if next.leases.contains_key(&lease.lease_id) {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                next.leases.insert(lease.lease_id.clone(), lease);
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.state = LeaseOperationStateV1::Applied;
            }
            (
                LeaseOperationKindV1::Renew,
                ProviderLeaseObservationV1::RenewApplied {
                    lease_id,
                    observed_at_unix_ms,
                    expires_at_unix_ms,
                    renewable,
                    provider_metadata_sha256,
                },
            ) => {
                if current.lease_id.as_deref() != Some(lease_id.as_str())
                    || provider_metadata_sha256 == [0; 32]
                    || expires_at_unix_ms <= observed_at_unix_ms
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                if !matches!(
                    lease.state,
                    SecretLeaseStateV1::Active | SecretLeaseStateV1::RenewUnknown
                ) {
                    return Err(LeaseRegistryErrorV1::InvalidTransition);
                }
                lease.expires_at_unix_ms = expires_at_unix_ms;
                lease.renewable = renewable;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.state = SecretLeaseStateV1::Active;
                next.operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
                    .state = LeaseOperationStateV1::Applied;
            }
            (
                LeaseOperationKindV1::Revoke,
                ProviderLeaseObservationV1::RevokeApplied {
                    lease_id,
                    observed_at_unix_ms: _,
                    provider_metadata_sha256,
                },
            ) => {
                if current.lease_id.as_deref() != Some(lease_id.as_str())
                    || provider_metadata_sha256 == [0; 32]
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.state = SecretLeaseStateV1::Revoked;
                next.operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
                    .state = LeaseOperationStateV1::Applied;
            }
            (_, ProviderLeaseObservationV1::Unknown) => {
                return self.mark_unknown(operation_id);
            }
            (_, ProviderLeaseObservationV1::Denied) => {
                next.operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
                    .state = LeaseOperationStateV1::Denied;
                restore_unknown_lease_state(&mut next, &current)?;
            }
            (_, ProviderLeaseObservationV1::NotApplied) => {
                next.operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
                    .state = LeaseOperationStateV1::Denied;
                restore_unknown_lease_state(&mut next, &current)?;
            }
            _ => return Err(LeaseRegistryErrorV1::ObservationMismatch),
        }
        self.commit(next)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub fn expire_at(&mut self, now_unix_ms: u64) -> Result<usize, LeaseRegistryErrorV1> {
        let mut next = self.state.clone();
        let mut changed = 0usize;
        for lease in next.leases.values_mut() {
            if lease.state == SecretLeaseStateV1::Active && now_unix_ms >= lease.expires_at_unix_ms
            {
                lease.state = SecretLeaseStateV1::Expired;
                changed += 1;
            }
        }
        if changed != 0 {
            self.commit(next)?;
        }
        Ok(changed)
    }

    fn prepare(
        &mut self,
        operation_id: String,
        kind: LeaseOperationKindV1,
        semantic_sha256: [u8; 32],
        lease_id: Option<String>,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        if !identifier(&operation_id)
            || semantic_sha256 == [0; 32]
            || lease_id.as_deref().is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        if let Some(existing) = self.state.operations.get(&operation_id) {
            if existing.kind == kind
                && existing.semantic_sha256 == semantic_sha256
                && existing.lease_id == lease_id
            {
                return Ok(existing.clone());
            }
            return Err(LeaseRegistryErrorV1::OperationConflict);
        }
        if self.state.operations.len() >= MAX_RECORDS {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        let operation = LeaseOperationV1 {
            operation_id: operation_id.clone(),
            kind,
            semantic_sha256,
            lease_id,
            state: LeaseOperationStateV1::Prepared,
        };
        let mut next = self.state.clone();
        next.operations.insert(operation_id, operation.clone());
        self.commit(next)?;
        Ok(operation)
    }

    fn require_active(&self, lease_id: &str) -> Result<(), LeaseRegistryErrorV1> {
        let lease = self
            .state
            .leases
            .get(lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if lease.state != SecretLeaseStateV1::Active || !lease.renewable {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        Ok(())
    }

    fn commit(&mut self, next: StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
        validate_state(&next)?;
        persist(&self.path, &next)?;
        self.state = next;
        Ok(())
    }
}

fn restore_unknown_lease_state(
    state: &mut StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    let Some(lease_id) = operation.lease_id.as_ref() else {
        return Ok(());
    };
    let lease = state
        .leases
        .get_mut(lease_id)
        .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
    if matches!(
        lease.state,
        SecretLeaseStateV1::RenewUnknown | SecretLeaseStateV1::RevokeUnknown
    ) {
        if !matches!(
            (operation.kind, lease.state),
            (
                LeaseOperationKindV1::Renew,
                SecretLeaseStateV1::RenewUnknown
            ) | (
                LeaseOperationKindV1::Revoke,
                SecretLeaseStateV1::RevokeUnknown
            )
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        lease.state = SecretLeaseStateV1::Active;
    }
    Ok(())
}

fn validate_state(state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    if state.schema_version != SCHEMA_VERSION
        || state.operations.len() > MAX_RECORDS
        || state.leases.len() > MAX_RECORDS
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    for (id, operation) in &state.operations {
        if id != &operation.operation_id
            || !identifier(id)
            || operation.semantic_sha256 == [0; 32]
            || operation
                .lease_id
                .as_deref()
                .is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    for (id, lease) in &state.leases {
        if id != &lease.lease_id {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        validate_lease_metadata(lease).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
    }
    Ok(())
}

fn validate_lease_metadata(lease: &SecretLeaseMetadataV1) -> Result<(), LeaseRegistryErrorV1> {
    if !identifier(&lease.lease_id)
        || !identifier(&lease.secret_reference_id)
        || !identifier(&lease.consumer_id)
        || lease.scope_sha256 == [0; 32]
        || lease.provider_metadata_sha256 == [0; 32]
        || lease.generation == 0
        || lease.expires_at_unix_ms <= lease.issued_at_unix_ms
    {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    let encoded = serde_json::to_vec(lease).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    if encoded.len() > MAX_METADATA_BYTES {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}

fn persist(path: &Path, state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    let parent = path.parent().ok_or(LeaseRegistryErrorV1::Unavailable)?;
    std::fs::create_dir_all(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    let bytes = serde_json::to_vec(state).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(LeaseRegistryErrorV1::Unavailable)?;
    let next = parent.join(format!("{file_name}.next"));
    let mut file = File::create(&next).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    std::fs::rename(&next, path).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| LeaseRegistryErrorV1::Unavailable)
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

#[cfg(test)]
#[path = "lease_lifecycle_tests.rs"]
mod tests;
