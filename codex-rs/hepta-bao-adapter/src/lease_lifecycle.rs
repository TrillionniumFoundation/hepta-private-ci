//! Durable metadata-only SecretLease lifecycle owner.
//!
//! This module deliberately stores no secret value. Provider effects are
//! represented as observations so a timeout or crash remains `Unknown` until a
//! trusted reconciler observes the original operation. The Unix storage profile
//! is single-writer: an advisory lock fences parallel owners, replacement is
//! synchronized before success, and a post-replacement durability failure
//! fences the open writer until it is reopened.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use serde::Deserialize;
use serde::Serialize;

const LEGACY_SCHEMA_VERSION: u32 = 1;
const SCHEMA_VERSION: u32 = 2;
const MAX_RECORDS: usize = 65_536;
const MAX_METADATA_BYTES: usize = 16 * 1024;
const MAX_STORE_BYTES: usize = 8 * 1024 * 1024;
const CONTROL_RESERVE_BYTES: usize = 64 * 1024;

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_generation: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_at_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resulting_generation: Option<u64>,
    #[serde(default, skip_serializing_if = "is_false")]
    pub legacy_binding_incomplete: bool,
    pub state: LeaseOperationStateV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseOperationResultV1 {
    pub operation: LeaseOperationV1,
    pub lease: Option<SecretLeaseMetadataV1>,
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
    #[serde(default)]
    revision: u64,
    operations: BTreeMap<String, LeaseOperationV1>,
    leases: BTreeMap<String, SecretLeaseMetadataV1>,
}

trait LeaseRegistryPersistenceV1: Send + Sync {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
    fn sync_parent(&self, parent: &Path) -> io::Result<()>;
}

#[derive(Debug)]
struct FsLeaseRegistryPersistenceV1;

impl LeaseRegistryPersistenceV1 for FsLeaseRegistryPersistenceV1 {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
        file.write_all(bytes)?;
        file.sync_all()
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        fs::rename(from, to)
    }

    fn sync_parent(&self, parent: &Path) -> io::Result<()> {
        File::open(parent)?.sync_all()
    }
}

pub struct DurableLeaseRegistryV1 {
    path: PathBuf,
    lock: File,
    state: StoredRegistryV1,
    persistence: Arc<dyn LeaseRegistryPersistenceV1>,
    fenced: bool,
}

impl std::fmt::Debug for DurableLeaseRegistryV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DurableLeaseRegistryV1")
            .field("path", &self.path)
            .field("schema_version", &self.state.schema_version)
            .field("revision", &self.state.revision)
            .field("operation_count", &self.state.operations.len())
            .field("lease_count", &self.state.leases.len())
            .field("fenced", &self.fenced)
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
    WriterBusy,
    CommitIndeterminate,
    Fenced,
    UnsupportedPlatform,
    Unavailable,
}

impl std::fmt::Display for LeaseRegistryErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LeaseRegistryErrorV1 {}

impl DurableLeaseRegistryV1 {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, LeaseRegistryErrorV1> {
        Self::open_with_persistence(path, Arc::new(FsLeaseRegistryPersistenceV1))
    }

    fn open_with_persistence(
        path: impl Into<PathBuf>,
        persistence: Arc<dyn LeaseRegistryPersistenceV1>,
    ) -> Result<Self, LeaseRegistryErrorV1> {
        if !cfg!(unix) {
            return Err(LeaseRegistryErrorV1::UnsupportedPlatform);
        }

        let path = path.into();
        let parent = parent_directory(&path);
        prepare_parent(parent)?;
        reject_existing_symlink(&path)?;

        let lock_path = sibling_with_suffix(&path, ".lock");
        reject_existing_symlink(&lock_path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        if !lock
            .metadata()
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?
            .is_file()
        {
            return Err(LeaseRegistryErrorV1::Unavailable);
        }
        match File::try_lock(&lock) {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(LeaseRegistryErrorV1::WriterBusy),
            Err(TryLockError::Error(_)) => return Err(LeaseRegistryErrorV1::Unavailable),
        }

        let temp_path = sibling_with_suffix(&path, ".next");
        reject_existing_symlink(&temp_path)?;
        remove_if_present(&temp_path)?;

        let state = match File::open(&path) {
            Ok(file) => {
                if !file
                    .metadata()
                    .map_err(|_| LeaseRegistryErrorV1::Unavailable)?
                    .is_file()
                {
                    return Err(LeaseRegistryErrorV1::Unavailable);
                }
                let mut bytes = Vec::new();
                file.take((MAX_STORE_BYTES + 1) as u64)
                    .read_to_end(&mut bytes)
                    .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
                if bytes.len() > MAX_STORE_BYTES {
                    return Err(LeaseRegistryErrorV1::CorruptState);
                }
                let decoded: StoredRegistryV1 = serde_json::from_slice(&bytes)
                    .map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
                let migrated = migrate_state(decoded)?;
                validate_state(&migrated)?;
                migrated
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let initial = StoredRegistryV1 {
                    schema_version: SCHEMA_VERSION,
                    revision: 1,
                    operations: BTreeMap::new(),
                    leases: BTreeMap::new(),
                };
                validate_state(&initial)?;
                let bytes = encode_state(&initial, 0)?;
                match persist_bytes(&path, &bytes, persistence.as_ref()) {
                    Ok(()) => initial,
                    Err(PersistFailure::NotApplied) => {
                        return Err(LeaseRegistryErrorV1::Unavailable);
                    }
                    Err(PersistFailure::Indeterminate) => {
                        return Err(LeaseRegistryErrorV1::CommitIndeterminate);
                    }
                }
            }
            Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
        };

        Ok(Self {
            path,
            lock,
            state,
            persistence,
            fenced: false,
        })
    }

    #[must_use]
    pub const fn is_fenced(&self) -> bool {
        self.fenced
    }

    pub fn lease(&self, lease_id: &str) -> Option<&SecretLeaseMetadataV1> {
        self.state.leases.get(lease_id)
    }

    pub fn operation(&self, operation_id: &str) -> Option<&LeaseOperationV1> {
        self.state.operations.get(operation_id)
    }

    pub fn operation_result(
        &self,
        operation_id: &str,
    ) -> Result<LeaseOperationResultV1, LeaseRegistryErrorV1> {
        let operation = self
            .state
            .operations
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        let lease = operation
            .lease_id
            .as_deref()
            .map(|lease_id| {
                self.state
                    .leases
                    .get(lease_id)
                    .cloned()
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)
            })
            .transpose()?;
        Ok(LeaseOperationResultV1 { operation, lease })
    }

    pub fn prepare_issue(
        &mut self,
        operation_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.validate_operation_identity(&operation_id, semantic_sha256, None)?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Issue,
            semantic_sha256,
            None,
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;

        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Issue,
            semantic_sha256,
            None,
            None,
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        let pending_issues = next
            .operations
            .values()
            .filter(|candidate| {
                candidate.kind == LeaseOperationKindV1::Issue
                    && matches!(
                        candidate.state,
                        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
                    )
            })
            .count();
        let issue_reserve = pending_issues
            .checked_mul(MAX_METADATA_BYTES)
            .and_then(|value| value.checked_add(CONTROL_RESERVE_BYTES))
            .ok_or(LeaseRegistryErrorV1::CapacityExceeded)?;
        self.commit(next, issue_reserve)?;
        Ok(operation)
    }

    pub fn prepare_renew(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.validate_operation_identity(&operation_id, semantic_sha256, Some(&lease_id))?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Renew,
            semantic_sha256,
            Some(&lease_id),
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;
        let lease = self
            .state
            .leases
            .get(&lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if lease.state != SecretLeaseStateV1::Active || !lease.renewable {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        if has_pending_mutation(&self.state, &lease_id, None) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Renew,
            semantic_sha256,
            Some(lease_id),
            Some(lease.generation),
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        self.commit(next, CONTROL_RESERVE_BYTES)?;
        Ok(operation)
    }

    pub fn prepare_revoke(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.validate_operation_identity(&operation_id, semantic_sha256, Some(&lease_id))?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Revoke,
            semantic_sha256,
            Some(&lease_id),
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;
        let lease = self
            .state
            .leases
            .get(&lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if matches!(
            lease.state,
            SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
        ) || has_pending_kind(
            &self.state,
            &lease_id,
            LeaseOperationKindV1::Revoke,
            None,
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Revoke,
            semantic_sha256,
            Some(lease_id),
            Some(lease.generation),
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        self.commit(next, 0)?;
        Ok(operation)
    }

    pub fn mark_unknown(
        &mut self,
        operation_id: &str,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
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
        if let Some(lease_id) = current.lease_id.as_deref() {
            let lease = next
                .leases
                .get_mut(lease_id)
                .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
            if current
                .expected_generation
                .is_some_and(|expected| expected != lease.generation)
                && !matches!(
                    lease.state,
                    SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                )
            {
                return Err(LeaseRegistryErrorV1::ObservationMismatch);
            }
            match current.kind {
                LeaseOperationKindV1::Issue => {}
                LeaseOperationKindV1::Renew => {
                    if lease.state == SecretLeaseStateV1::Active {
                        lease.state = SecretLeaseStateV1::RenewUnknown;
                    }
                }
                LeaseOperationKindV1::Revoke => {
                    if !matches!(
                        lease.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    ) {
                        lease.state = SecretLeaseStateV1::RevokeUnknown;
                    }
                }
            }
        }
        let operation = next
            .operations
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        operation.state = LeaseOperationStateV1::Unknown;
        self.commit(next, 0)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub fn reconcile(
        &mut self,
        operation_id: &str,
        observation: ProviderLeaseObservationV1,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
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
        if observation == ProviderLeaseObservationV1::Unknown {
            return self.mark_unknown(operation_id);
        }

        let mut next = self.state.clone();
        match (&current.kind, observation) {
            (LeaseOperationKindV1::Issue, ProviderLeaseObservationV1::IssueApplied { lease }) => {
                validate_new_active_lease(&lease)?;
                if next.leases.contains_key(&lease.lease_id) {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let lease_id = lease.lease_id.clone();
                let issued_at_unix_ms = lease.issued_at_unix_ms;
                let generation = lease.generation;
                next.leases.insert(lease_id.clone(), lease);
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.lease_id = Some(lease_id);
                operation.observed_at_unix_ms = Some(issued_at_unix_ms);
                operation.resulting_generation = Some(generation);
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
                    || has_pending_kind(
                        &next,
                        &lease_id,
                        LeaseOperationKindV1::Revoke,
                        Some(operation_id),
                    )
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let latest_observed = latest_observed_at(&next, &lease_id, Some(operation_id));
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                if current.expected_generation != Some(lease.generation)
                    || !matches!(
                        lease.state,
                        SecretLeaseStateV1::Active | SecretLeaseStateV1::RenewUnknown
                    )
                    || observed_at_unix_ms < lease.issued_at_unix_ms
                    || latest_observed.is_some_and(|latest| observed_at_unix_ms <= latest)
                    || expires_at_unix_ms <= lease.expires_at_unix_ms
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let resulting_generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.expires_at_unix_ms = expires_at_unix_ms;
                lease.renewable = renewable;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.generation = resulting_generation;
                lease.state = SecretLeaseStateV1::Active;
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.observed_at_unix_ms = Some(observed_at_unix_ms);
                operation.resulting_generation = Some(resulting_generation);
                operation.state = LeaseOperationStateV1::Applied;
            }
            (
                LeaseOperationKindV1::Revoke,
                ProviderLeaseObservationV1::RevokeApplied {
                    lease_id,
                    observed_at_unix_ms,
                    provider_metadata_sha256,
                },
            ) => {
                if current.lease_id.as_deref() != Some(lease_id.as_str())
                    || provider_metadata_sha256 == [0; 32]
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let latest_observed = latest_observed_at(&next, &lease_id, Some(operation_id));
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                if current.expected_generation != Some(lease.generation)
                    || matches!(
                        lease.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    )
                    || observed_at_unix_ms < lease.issued_at_unix_ms
                    || latest_observed.is_some_and(|latest| observed_at_unix_ms <= latest)
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let resulting_generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.renewable = false;
                lease.generation = resulting_generation;
                lease.state = SecretLeaseStateV1::Revoked;
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.observed_at_unix_ms = Some(observed_at_unix_ms);
                operation.resulting_generation = Some(resulting_generation);
                operation.state = LeaseOperationStateV1::Applied;
            }
            (_, ProviderLeaseObservationV1::Denied | ProviderLeaseObservationV1::NotApplied) => {
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.state = LeaseOperationStateV1::Denied;
                restore_after_negative_observation(&mut next, &current)?;
            }
            _ => return Err(LeaseRegistryErrorV1::ObservationMismatch),
        }
        self.commit(next, 0)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub fn expire_at(&mut self, now_unix_ms: u64) -> Result<usize, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let mut next = self.state.clone();
        let mut changed = 0usize;
        for lease in next.leases.values_mut() {
            if !matches!(
                lease.state,
                SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
            ) && now_unix_ms >= lease.expires_at_unix_ms
            {
                lease.generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.renewable = false;
                lease.state = SecretLeaseStateV1::Expired;
                changed += 1;
            }
        }
        if changed != 0 {
            self.commit(next, 0)?;
        }
        Ok(changed)
    }

    fn validate_operation_identity(
        &self,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease_id: Option<&str>,
    ) -> Result<(), LeaseRegistryErrorV1> {
        if !identifier(operation_id)
            || semantic_sha256 == [0; 32]
            || lease_id.is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        Ok(())
    }

    fn matching_existing(
        &self,
        operation_id: &str,
        kind: LeaseOperationKindV1,
        semantic_sha256: [u8; 32],
        lease_id: Option<&str>,
    ) -> Result<Option<LeaseOperationV1>, LeaseRegistryErrorV1> {
        let Some(existing) = self.state.operations.get(operation_id) else {
            return Ok(None);
        };
        if existing.kind == kind
            && existing.semantic_sha256 == semantic_sha256
            && existing.lease_id.as_deref() == lease_id
        {
            Ok(Some(existing.clone()))
        } else {
            Err(LeaseRegistryErrorV1::OperationConflict)
        }
    }

    fn ensure_writable(&self) -> Result<(), LeaseRegistryErrorV1> {
        if self.fenced {
            Err(LeaseRegistryErrorV1::Fenced)
        } else {
            Ok(())
        }
    }

    fn commit(
        &mut self,
        mut next: StoredRegistryV1,
        required_reserve: usize,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        next.schema_version = SCHEMA_VERSION;
        next.revision = self
            .state
            .revision
            .checked_add(1)
            .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
        validate_state(&next)?;
        let bytes = encode_state(&next, required_reserve)?;
        match persist_bytes(&self.path, &bytes, self.persistence.as_ref()) {
            Ok(()) => {
                self.state = next;
                Ok(())
            }
            Err(PersistFailure::NotApplied) => Err(LeaseRegistryErrorV1::Unavailable),
            Err(PersistFailure::Indeterminate) => {
                self.state = next;
                self.fenced = true;
                Err(LeaseRegistryErrorV1::CommitIndeterminate)
            }
        }
    }
}

impl Drop for DurableLeaseRegistryV1 {
    fn drop(&mut self) {
        let _ = File::unlock(&self.lock);
    }
}

fn new_operation(
    operation_id: String,
    kind: LeaseOperationKindV1,
    semantic_sha256: [u8; 32],
    lease_id: Option<String>,
    expected_generation: Option<u64>,
) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id,
        kind,
        semantic_sha256,
        lease_id,
        expected_generation,
        observed_at_unix_ms: None,
        resulting_generation: None,
        legacy_binding_incomplete: false,
        state: LeaseOperationStateV1::Prepared,
    }
}

fn restore_after_negative_observation(
    state: &mut StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    let Some(lease_id) = operation.lease_id.as_deref() else {
        return Ok(());
    };
    let has_unknown_renew = has_pending_kind(
        state,
        lease_id,
        LeaseOperationKindV1::Renew,
        Some(&operation.operation_id),
    );
    let has_unknown_revoke = has_pending_kind(
        state,
        lease_id,
        LeaseOperationKindV1::Revoke,
        Some(&operation.operation_id),
    );
    let lease = state
        .leases
        .get_mut(lease_id)
        .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
    if matches!(
        lease.state,
        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
    ) {
        return Ok(());
    }
    match operation.kind {
        LeaseOperationKindV1::Issue => {}
        LeaseOperationKindV1::Renew => {
            if lease.state == SecretLeaseStateV1::RenewUnknown && !has_unknown_revoke {
                lease.state = SecretLeaseStateV1::Active;
            }
        }
        LeaseOperationKindV1::Revoke => {
            if lease.state == SecretLeaseStateV1::RevokeUnknown {
                lease.state = if has_unknown_renew {
                    SecretLeaseStateV1::RenewUnknown
                } else {
                    SecretLeaseStateV1::Active
                };
            }
        }
    }
    Ok(())
}

fn latest_observed_at(
    state: &StoredRegistryV1,
    lease_id: &str,
    excluded_operation_id: Option<&str>,
) -> Option<u64> {
    state
        .operations
        .values()
        .filter(|operation| {
            excluded_operation_id != Some(operation.operation_id.as_str())
                && operation.lease_id.as_deref() == Some(lease_id)
                && operation.state == LeaseOperationStateV1::Applied
        })
        .filter_map(|operation| operation.observed_at_unix_ms)
        .max()
}

fn has_pending_mutation(
    state: &StoredRegistryV1,
    lease_id: &str,
    excluded_operation_id: Option<&str>,
) -> bool {
    state.operations.values().any(|operation| {
        excluded_operation_id != Some(operation.operation_id.as_str())
            && operation.lease_id.as_deref() == Some(lease_id)
            && matches!(
                operation.kind,
                LeaseOperationKindV1::Renew | LeaseOperationKindV1::Revoke
            )
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
    })
}

fn has_pending_kind(
    state: &StoredRegistryV1,
    lease_id: &str,
    kind: LeaseOperationKindV1,
    excluded_operation_id: Option<&str>,
) -> bool {
    state.operations.values().any(|operation| {
        excluded_operation_id != Some(operation.operation_id.as_str())
            && operation.lease_id.as_deref() == Some(lease_id)
            && operation.kind == kind
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
    })
}

fn ensure_operation_capacity(state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    if state.operations.len() >= MAX_RECORDS {
        Err(LeaseRegistryErrorV1::CapacityExceeded)
    } else {
        Ok(())
    }
}

fn migrate_state(mut state: StoredRegistryV1) -> Result<StoredRegistryV1, LeaseRegistryErrorV1> {
    match state.schema_version {
        SCHEMA_VERSION => {
            if state.revision == 0 {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            return Ok(state);
        }
        LEGACY_SCHEMA_VERSION => {}
        _ => return Err(LeaseRegistryErrorV1::CorruptState),
    }

    state.schema_version = SCHEMA_VERSION;
    state.revision = state.revision.max(1);

    let unbound_issues: Vec<String> = state
        .operations
        .values()
        .filter(|operation| {
            operation.kind == LeaseOperationKindV1::Issue
                && operation.state == LeaseOperationStateV1::Applied
                && operation.lease_id.is_none()
        })
        .map(|operation| operation.operation_id.clone())
        .collect();
    let referenced_leases: BTreeSet<String> = state
        .operations
        .values()
        .filter(|operation| operation.kind == LeaseOperationKindV1::Issue)
        .filter_map(|operation| operation.lease_id.clone())
        .collect();
    let unbound_leases: Vec<String> = state
        .leases
        .keys()
        .filter(|lease_id| !referenced_leases.contains(*lease_id))
        .cloned()
        .collect();
    if unbound_issues.len() == 1 && unbound_leases.len() == 1 {
        let operation_id = &unbound_issues[0];
        let lease_id = &unbound_leases[0];
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        let operation = state
            .operations
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        operation.lease_id = Some(lease_id.clone());
        operation.observed_at_unix_ms = Some(lease.issued_at_unix_ms);
        if lease.generation == 1 {
            operation.resulting_generation = Some(1);
        } else {
            operation.legacy_binding_incomplete = true;
        }
    }

    for operation in state.operations.values_mut() {
        match operation.kind {
            LeaseOperationKindV1::Issue => {
                if operation.state == LeaseOperationStateV1::Applied {
                    if let Some(lease_id) = operation.lease_id.as_deref() {
                        if let Some(lease) = state.leases.get(lease_id) {
                            operation
                                .observed_at_unix_ms
                                .get_or_insert(lease.issued_at_unix_ms);
                            if lease.generation == 1 {
                                operation.resulting_generation.get_or_insert(1);
                            } else if operation.resulting_generation.is_none() {
                                operation.legacy_binding_incomplete = true;
                            }
                        } else {
                            operation.legacy_binding_incomplete = true;
                        }
                    } else {
                        operation.legacy_binding_incomplete = true;
                    }
                }
            }
            LeaseOperationKindV1::Renew | LeaseOperationKindV1::Revoke => {
                let Some(lease_id) = operation.lease_id.as_deref() else {
                    operation.legacy_binding_incomplete = true;
                    continue;
                };
                let Some(lease) = state.leases.get(lease_id) else {
                    operation.legacy_binding_incomplete = true;
                    continue;
                };
                if operation.expected_generation.is_none()
                    && matches!(
                        operation.state,
                        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
                    )
                    && !matches!(
                        lease.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    )
                {
                    operation.expected_generation = Some(lease.generation);
                }
                if operation.expected_generation.is_none()
                    || (operation.state == LeaseOperationStateV1::Applied
                        && (operation.observed_at_unix_ms.is_none()
                            || operation.resulting_generation.is_none()))
                {
                    operation.legacy_binding_incomplete = true;
                }
            }
        }
    }
    Ok(state)
}

fn validate_state(state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    if state.schema_version != SCHEMA_VERSION
        || state.revision == 0
        || state.operations.len() > MAX_RECORDS
        || state.leases.len() > MAX_RECORDS
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }

    for (id, lease) in &state.leases {
        if id != &lease.lease_id {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        validate_persisted_lease(lease).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
    }

    let mut pending_renew = BTreeMap::<&str, usize>::new();
    let mut pending_revoke = BTreeMap::<&str, usize>::new();
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
        validate_operation(state, operation)?;
        if !operation.legacy_binding_incomplete
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
        {
            let Some(lease_id) = operation.lease_id.as_deref() else {
                continue;
            };
            let target = match operation.kind {
                LeaseOperationKindV1::Issue => continue,
                LeaseOperationKindV1::Renew => &mut pending_renew,
                LeaseOperationKindV1::Revoke => &mut pending_revoke,
            };
            let count = target.entry(lease_id).or_default();
            *count += 1;
            if *count > 1 {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
    }
    Ok(())
}

fn validate_operation(
    state: &StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    match operation.kind {
        LeaseOperationKindV1::Issue => {
            if operation.expected_generation.is_some() {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            if operation.state == LeaseOperationStateV1::Applied
                && !operation.legacy_binding_incomplete
                && (operation.lease_id.is_none()
                    || operation.observed_at_unix_ms.is_none()
                    || operation.resulting_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
        LeaseOperationKindV1::Renew | LeaseOperationKindV1::Revoke => {
            if !operation.legacy_binding_incomplete
                && (operation.lease_id.is_none() || operation.expected_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            if operation.state == LeaseOperationStateV1::Applied
                && !operation.legacy_binding_incomplete
                && (operation.observed_at_unix_ms.is_none()
                    || operation.resulting_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
    }

    if matches!(
        operation.state,
        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
    ) && operation.resulting_generation.is_some()
        && !operation.legacy_binding_incomplete
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let (Some(expected), Some(resulting)) = (
        operation.expected_generation,
        operation.resulting_generation,
    ) {
        if resulting <= expected {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    if let Some(lease_id) = operation.lease_id.as_deref() {
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        if operation
            .resulting_generation
            .is_some_and(|resulting| resulting > lease.generation)
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    Ok(())
}

fn validate_new_active_lease(
    lease: &SecretLeaseMetadataV1,
) -> Result<(), LeaseRegistryErrorV1> {
    validate_persisted_lease(lease)?;
    if lease.state != SecretLeaseStateV1::Active || lease.generation != 1 {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}

fn validate_persisted_lease(
    lease: &SecretLeaseMetadataV1,
) -> Result<(), LeaseRegistryErrorV1> {
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
    let encoded =
        serde_json::to_vec(lease).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    if encoded.len() > MAX_METADATA_BYTES {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}

fn encode_state(
    state: &StoredRegistryV1,
    required_reserve: usize,
) -> Result<Vec<u8>, LeaseRegistryErrorV1> {
    let bytes = serde_json::to_vec(state).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    if bytes
        .len()
        .checked_add(required_reserve)
        .is_none_or(|required| required > MAX_STORE_BYTES)
    {
        return Err(LeaseRegistryErrorV1::CapacityExceeded);
    }
    Ok(bytes)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PersistFailure {
    NotApplied,
    Indeterminate,
}

fn persist_bytes(
    path: &Path,
    bytes: &[u8],
    persistence: &dyn LeaseRegistryPersistenceV1,
) -> Result<(), PersistFailure> {
    let parent = parent_directory(path);
    let temp_path = sibling_with_suffix(path, ".next");
    remove_if_present(&temp_path).map_err(|_| PersistFailure::NotApplied)?;
    if persistence
        .write_and_sync_temp(&temp_path, bytes)
        .is_err()
    {
        let _ = fs::remove_file(&temp_path);
        return Err(PersistFailure::NotApplied);
    }
    if persistence.rename(&temp_path, path).is_err() {
        let _ = fs::remove_file(&temp_path);
        return Err(PersistFailure::NotApplied);
    }
    persistence
        .sync_parent(parent)
        .map_err(|_| PersistFailure::Indeterminate)
}

fn prepare_parent(parent: &Path) -> Result<(), LeaseRegistryErrorV1> {
    match fs::symlink_metadata(parent) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(LeaseRegistryErrorV1::Unavailable);
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            fs::create_dir_all(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
            let metadata = fs::symlink_metadata(parent)
                .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(LeaseRegistryErrorV1::Unavailable);
            }
        }
        Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
    }
    Ok(())
}

fn reject_existing_symlink(path: &Path) -> Result<(), LeaseRegistryErrorV1> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err(LeaseRegistryErrorV1::Unavailable)
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(LeaseRegistryErrorV1::Unavailable),
    }
}

fn remove_if_present(path: &Path) -> Result<(), LeaseRegistryErrorV1> {
    reject_existing_symlink(path)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(LeaseRegistryErrorV1::Unavailable),
    }
}

fn parent_directory(path: &Path) -> &Path {
    path.parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
}

fn sibling_with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

const fn is_false(value: &bool) -> bool {
    !*value
}

#[cfg(all(test, unix))]
#[path = "lease_lifecycle_tests.rs"]
mod tests;
