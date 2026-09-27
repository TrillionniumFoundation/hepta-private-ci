//! Product durability wrapper for the supervisor-owned fleet allocation state.
//!
//! The core publishes checksummed state generations. This wrapper adds exact,
//! create-only operation and allocation identity indexes so full receipts and
//! grant history may be compacted without losing exactly-once semantics or
//! permitting an allocation identity to be reused.

#[path = "durable_owner_core.rs"]
mod core;

pub use core::DURABLE_FLEET_STATE_SCHEMA_VERSION;
pub use core::DurableFleetError;
pub use core::DurableFleetIssueReceiptV1;
pub use core::DurableFleetMutationReceiptV1;
pub use core::DurableFleetStateV1;
pub use core::FleetHostRecordV1;
pub use core::FleetOperationKindV1;
pub use core::FleetOperationReceiptV1;
pub use core::FleetOperationalMetricsV1;
pub use core::FleetResultCountersV1;
pub use core::MAX_DURABLE_OPERATION_RECEIPTS;

use crate::AllocationGrant;
use crate::FleetAuthorityPort;
use crate::FleetCapacityObserverV1;
use crate::FleetClock;
use crate::GrantUseWitnessV1;
use crate::LeaseDisposition;
use crate::LeaseReceipt;
use crate::FleetRevocationSnapshotV1;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const INDEX_SCHEMA_VERSION: u32 = 1;
const OPERATION_INDEX_DIRECTORY: &str = "fleet-operation-index-v1";
const ALLOCATION_INDEX_DIRECTORY: &str = "fleet-allocation-index-v1";
const CORE_STATE_DIRECTORY: &str = "fleet-allocation-v1";
const STATE_FILE_PREFIX: &str = "generation-";
const STATE_FILE_SUFFIX: &str = ".json";
const MAX_INDEX_ENTRY_BYTES: u64 = 1 << 20;
static INDEX_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct OperationIndexEntryV1 {
    schema_version: u32,
    operation_id: String,
    operation_kind: FleetOperationKindV1,
    operation_digest: String,
    committed_generation: u64,
    committed_at_ms: u64,
    committed_state_sha256: String,
    lease_receipt: Option<LeaseReceipt>,
    authority_witness: Option<VerifiedUseTokenWitnessV1>,
    content_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct AllocationIdentityV1 {
    schema_version: u32,
    allocation_id: String,
    grant_digest: String,
    issue_operation_id: String,
    committed_generation: u64,
    content_sha256: String,
}

pub struct DurableFleetOwner {
    supervisor_state_root: PathBuf,
    clock: Arc<dyn FleetClock>,
    inner: core::DurableFleetOwner,
}

impl fmt::Debug for DurableFleetOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableFleetOwner")
            .field("supervisor_state_root", &self.supervisor_state_root)
            .field("generation", &self.inner.state().generation)
            .finish()
    }
}

impl DurableFleetOwner {
    pub fn open_supervisor_state_root(
        supervisor_state_root: impl Into<PathBuf>,
        clock: Arc<dyn FleetClock>,
    ) -> Result<Self, DurableFleetError> {
        let supervisor_state_root = supervisor_state_root.into();
        validate_physical_directory(&supervisor_state_root)?;
        ensure_private_directory(&supervisor_state_root.join(OPERATION_INDEX_DIRECTORY))?;
        ensure_private_directory(&supervisor_state_root.join(ALLOCATION_INDEX_DIRECTORY))?;
        let inner = core::DurableFleetOwner::open_supervisor_state_root(
            supervisor_state_root.clone(),
            Arc::clone(&clock),
        )?;
        Ok(Self {
            supervisor_state_root,
            clock,
            inner,
        })
    }

    pub fn state(&self) -> &DurableFleetStateV1 {
        self.inner.state()
    }

    pub fn refresh_capacity<O: FleetCapacityObserverV1>(
        &mut self,
        operation_id: &str,
        observer: &O,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        if let Some(entry) = self.lookup_operation(
            operation_id,
            FleetOperationKindV1::CapacityObservation,
            None,
        )? {
            return mutation_from_index(entry);
        }
        match self.inner.refresh_capacity(operation_id, observer) {
            Ok(_) => self.record_mutation(operation_id),
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                self.reopen_inner()?;
                match self.lookup_operation(
                    operation_id,
                    FleetOperationKindV1::CapacityObservation,
                    None,
                )? {
                    Some(entry) => mutation_from_index(entry),
                    None => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    pub fn issue_with_authority(
        &mut self,
        operation_id: &str,
        authority: &FleetAuthorityPort,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        let expected_operation_digest = operation_digest(
            b"issue",
            &(
                operation_id,
                lease_id,
                expected_lease_revision,
                &grant,
            ),
        )?;
        if let Some(entry) = self.lookup_operation(
            operation_id,
            FleetOperationKindV1::Issue,
            Some(&expected_operation_digest),
        )? {
            let result = issue_from_index(entry)?;
            self.ensure_allocation_identity(&grant, operation_id, result.generation)?;
            return Ok(result);
        }
        self.reject_reused_allocation_identity(&grant, operation_id)?;
        match self.inner.issue_with_authority(
            operation_id,
            authority,
            lease_id,
            expected_lease_revision,
            grant.clone(),
        ) {
            Ok(_) => {
                let entry = self.record_current_operation(operation_id)?;
                let result = issue_from_index(entry)?;
                self.ensure_allocation_identity(&grant, operation_id, result.generation)?;
                Ok(result)
            }
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                self.reopen_inner()?;
                match self.lookup_operation(
                    operation_id,
                    FleetOperationKindV1::Issue,
                    Some(&expected_operation_digest),
                )? {
                    Some(entry) => {
                        let result = issue_from_index(entry)?;
                        self.ensure_allocation_identity(
                            &grant,
                            operation_id,
                            result.generation,
                        )?;
                        Ok(result)
                    }
                    None => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    pub fn renew_or_revoke(
        &mut self,
        operation_id: &str,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let disposition_digest = match disposition {
            LeaseDisposition::Renew { expires_at_ms } => format!("renew:{expires_at_ms}"),
            LeaseDisposition::Revoke => "revoke".to_string(),
        };
        let expected_digest = operation_digest(
            b"renew-or-revoke",
            &(
                operation_id,
                allocation_id,
                expected_lease_generation,
                authority_epoch,
                semantic_digest,
                &disposition_digest,
            ),
        )?;
        let expected_kind = if matches!(disposition, LeaseDisposition::Revoke) {
            FleetOperationKindV1::Revoke
        } else {
            FleetOperationKindV1::Renew
        };
        if let Some(entry) =
            self.lookup_operation(operation_id, expected_kind, Some(&expected_digest))?
        {
            return mutation_from_index(entry);
        }
        match self.inner.renew_or_revoke(
            operation_id,
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        ) {
            Ok(_) => self.record_mutation(operation_id),
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                self.reopen_inner()?;
                match self.lookup_operation(operation_id, expected_kind, Some(&expected_digest))? {
                    Some(entry) => mutation_from_index(entry),
                    None => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    pub fn reconcile_expired(
        &mut self,
        operation_id: &str,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        if let Some(entry) = self.lookup_operation(
            operation_id,
            FleetOperationKindV1::ExpiryReconciliation,
            None,
        )? {
            return mutation_from_index(entry);
        }
        match self.inner.reconcile_expired(operation_id) {
            Ok(_) => self.record_mutation(operation_id),
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                self.reopen_inner()?;
                match self.lookup_operation(
                    operation_id,
                    FleetOperationKindV1::ExpiryReconciliation,
                    None,
                )? {
                    Some(entry) => mutation_from_index(entry),
                    None => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    pub fn persist_revocation_snapshot(
        &mut self,
        operation_id: &str,
        snapshot: FleetRevocationSnapshotV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let expected_digest =
            operation_digest(b"revocation-snapshot", &(operation_id, &snapshot))?;
        if let Some(entry) = self.lookup_operation(
            operation_id,
            FleetOperationKindV1::RevocationSnapshot,
            Some(&expected_digest),
        )? {
            return mutation_from_index(entry);
        }
        match self
            .inner
            .persist_revocation_snapshot(operation_id, snapshot)
        {
            Ok(_) => self.record_mutation(operation_id),
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                self.reopen_inner()?;
                match self.lookup_operation(
                    operation_id,
                    FleetOperationKindV1::RevocationSnapshot,
                    Some(&expected_digest),
                )? {
                    Some(entry) => mutation_from_index(entry),
                    None => Err(error),
                }
            }
            Err(error) => Err(error),
        }
    }

    pub fn verify_final_use(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, DurableFleetError> {
        self.inner.verify_final_use(
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        )
    }

    pub fn metrics(&mut self) -> Result<FleetOperationalMetricsV1, DurableFleetError> {
        self.inner.metrics()
    }

    pub fn note_registry_conflict(&mut self) {
        self.inner.note_registry_conflict();
    }

    pub fn note_indeterminate_commit(&mut self) {
        self.inner.note_indeterminate_commit();
    }

    fn record_mutation(
        &mut self,
        operation_id: &str,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        mutation_from_index(self.record_current_operation(operation_id)?)
    }

    fn record_current_operation(
        &mut self,
        operation_id: &str,
    ) -> Result<OperationIndexEntryV1, DurableFleetError> {
        let operation = self
            .inner
            .state()
            .fleet_operation_receipts
            .iter()
            .find(|candidate| candidate.operation_id == operation_id)
            .cloned()
            .ok_or(DurableFleetError::CorruptState)?;
        let state_sha256 = self.state_digest_for_generation(operation.committed_generation)?;
        let entry = operation_index_entry(operation, state_sha256)?;
        self.persist_operation_index(&entry)?;
        Ok(entry)
    }

    fn lookup_operation(
        &mut self,
        operation_id: &str,
        expected_kind: FleetOperationKindV1,
        expected_digest: Option<&str>,
    ) -> Result<Option<OperationIndexEntryV1>, DurableFleetError> {
        validate_identity(operation_id)?;
        let entry = match self.read_operation_index(operation_id)? {
            Some(entry) => Some(entry),
            None => {
                let retained = self
                    .inner
                    .state()
                    .fleet_operation_receipts
                    .iter()
                    .find(|candidate| candidate.operation_id == operation_id)
                    .cloned();
                match retained {
                    Some(operation) => {
                        let state_sha256 =
                            self.state_digest_for_generation(operation.committed_generation)?;
                        let entry = operation_index_entry(operation, state_sha256)?;
                        self.persist_operation_index(&entry)?;
                        Some(entry)
                    }
                    None => None,
                }
            }
        };
        if let Some(entry) = entry {
            if entry.operation_kind != expected_kind
                || expected_digest.is_some_and(|digest| entry.operation_digest != digest)
            {
                return Err(DurableFleetError::OperationConflict(
                    operation_id.to_string(),
                ));
            }
            Ok(Some(entry))
        } else {
            Ok(None)
        }
    }

    fn reject_reused_allocation_identity(
        &self,
        grant: &AllocationGrant,
        operation_id: &str,
    ) -> Result<(), DurableFleetError> {
        let Some(existing) = self.read_allocation_index(&grant.allocation_id)? else {
            return Ok(());
        };
        let digest = grant_identity_digest(grant)?;
        if existing.issue_operation_id == operation_id && existing.grant_digest == digest {
            return Err(DurableFleetError::CorruptState);
        }
        Err(DurableFleetError::OperationConflict(
            grant.allocation_id.clone(),
        ))
    }

    fn ensure_allocation_identity(
        &self,
        grant: &AllocationGrant,
        operation_id: &str,
        committed_generation: u64,
    ) -> Result<(), DurableFleetError> {
        let mut entry = AllocationIdentityV1 {
            schema_version: INDEX_SCHEMA_VERSION,
            allocation_id: grant.allocation_id.clone(),
            grant_digest: grant_identity_digest(grant)?,
            issue_operation_id: operation_id.to_string(),
            committed_generation,
            content_sha256: String::new(),
        };
        entry.content_sha256 = allocation_entry_digest(&entry)?;
        if let Some(existing) = self.read_allocation_index(&grant.allocation_id)? {
            if existing == entry {
                return Ok(());
            }
            return Err(DurableFleetError::OperationConflict(
                grant.allocation_id.clone(),
            ));
        }
        publish_index_entry(
            &self.supervisor_state_root.join(ALLOCATION_INDEX_DIRECTORY),
            &grant.allocation_id,
            &entry,
            committed_generation,
        )?;
        let published = self
            .read_allocation_index(&grant.allocation_id)?
            .ok_or(DurableFleetError::CorruptState)?;
        if published != entry {
            return Err(DurableFleetError::OperationConflict(
                grant.allocation_id.clone(),
            ));
        }
        Ok(())
    }

    fn persist_operation_index(
        &self,
        entry: &OperationIndexEntryV1,
    ) -> Result<(), DurableFleetError> {
        if let Some(existing) = self.read_operation_index(&entry.operation_id)? {
            if existing == *entry {
                return Ok(());
            }
            return Err(DurableFleetError::OperationConflict(
                entry.operation_id.clone(),
            ));
        }
        publish_index_entry(
            &self.supervisor_state_root.join(OPERATION_INDEX_DIRECTORY),
            &entry.operation_id,
            entry,
            entry.committed_generation,
        )?;
        let published = self
            .read_operation_index(&entry.operation_id)?
            .ok_or(DurableFleetError::CorruptState)?;
        if published != *entry {
            return Err(DurableFleetError::OperationConflict(
                entry.operation_id.clone(),
            ));
        }
        Ok(())
    }

    fn read_operation_index(
        &self,
        operation_id: &str,
    ) -> Result<Option<OperationIndexEntryV1>, DurableFleetError> {
        let path = index_path(
            &self.supervisor_state_root.join(OPERATION_INDEX_DIRECTORY),
            operation_id,
        );
        let Some(entry): Option<OperationIndexEntryV1> = read_index_entry(&path)? else {
            return Ok(None);
        };
        if entry.schema_version != INDEX_SCHEMA_VERSION
            || entry.operation_id != operation_id
            || entry.committed_generation == 0
            || !valid_digest(&entry.operation_digest)
            || !valid_digest(&entry.committed_state_sha256)
            || entry.content_sha256 != operation_entry_digest(&entry)?
        {
            return Err(DurableFleetError::CorruptState);
        }
        Ok(Some(entry))
    }

    fn read_allocation_index(
        &self,
        allocation_id: &str,
    ) -> Result<Option<AllocationIdentityV1>, DurableFleetError> {
        validate_identity(allocation_id)?;
        let path = index_path(
            &self.supervisor_state_root.join(ALLOCATION_INDEX_DIRECTORY),
            allocation_id,
        );
        let Some(entry): Option<AllocationIdentityV1> = read_index_entry(&path)? else {
            return Ok(None);
        };
        if entry.schema_version != INDEX_SCHEMA_VERSION
            || entry.allocation_id != allocation_id
            || entry.committed_generation == 0
            || !valid_digest(&entry.grant_digest)
            || entry.content_sha256 != allocation_entry_digest(&entry)?
        {
            return Err(DurableFleetError::CorruptState);
        }
        Ok(Some(entry))
    }

    fn state_digest_for_generation(
        &self,
        generation: u64,
    ) -> Result<String, DurableFleetError> {
        let path = self
            .supervisor_state_root
            .join(CORE_STATE_DIRECTORY)
            .join(format!(
                "{STATE_FILE_PREFIX}{generation:020}{STATE_FILE_SUFFIX}"
            ));
        let state: DurableFleetStateV1 = serde_json::from_slice(&std::fs::read(path)?)?;
        if state.generation != generation || state.content_sha256 != durable_state_digest(&state)? {
            return Err(DurableFleetError::CorruptState);
        }
        Ok(state.content_sha256)
    }

    fn reopen_inner(&mut self) -> Result<(), DurableFleetError> {
        self.inner = core::DurableFleetOwner::open_supervisor_state_root(
            self.supervisor_state_root.clone(),
            Arc::clone(&self.clock),
        )?;
        Ok(())
    }
}

fn operation_index_entry(
    operation: FleetOperationReceiptV1,
    committed_state_sha256: String,
) -> Result<OperationIndexEntryV1, DurableFleetError> {
    let mut entry = OperationIndexEntryV1 {
        schema_version: INDEX_SCHEMA_VERSION,
        operation_id: operation.operation_id,
        operation_kind: operation.operation_kind,
        operation_digest: operation.operation_digest,
        committed_generation: operation.committed_generation,
        committed_at_ms: operation.committed_at_ms,
        committed_state_sha256,
        lease_receipt: operation.lease_receipt,
        authority_witness: operation.authority_witness,
        content_sha256: String::new(),
    };
    entry.content_sha256 = operation_entry_digest(&entry)?;
    Ok(entry)
}

fn mutation_from_index(
    entry: OperationIndexEntryV1,
) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
    let operation = FleetOperationReceiptV1 {
        operation_id: entry.operation_id,
        operation_kind: entry.operation_kind,
        operation_digest: entry.operation_digest,
        committed_generation: entry.committed_generation,
        committed_at_ms: entry.committed_at_ms,
        lease_receipt: entry.lease_receipt,
        authority_witness: entry.authority_witness,
    };
    Ok(DurableFleetMutationReceiptV1 {
        generation: operation.committed_generation,
        state_sha256: entry.committed_state_sha256,
        operation,
    })
}

fn issue_from_index(
    entry: OperationIndexEntryV1,
) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
    if entry.operation_kind != FleetOperationKindV1::Issue {
        return Err(DurableFleetError::CorruptState);
    }
    Ok(DurableFleetIssueReceiptV1 {
        generation: entry.committed_generation,
        state_sha256: entry.committed_state_sha256,
        lease: entry
            .lease_receipt
            .ok_or(DurableFleetError::CorruptState)?,
        authority_witness: entry
            .authority_witness
            .ok_or(DurableFleetError::CorruptState)?,
    })
}

fn operation_digest<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<String, DurableFleetError> {
    let encoded = serde_json::to_vec(value)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.operation.v1\0");
    digest.update(domain);
    digest.update([0]);
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn grant_identity_digest(grant: &AllocationGrant) -> Result<String, DurableFleetError> {
    let mut canonical = grant.clone();
    canonical.revoked = false;
    operation_digest(b"allocation-identity", &canonical)
}

fn operation_entry_digest(entry: &OperationIndexEntryV1) -> Result<String, DurableFleetError> {
    let mut candidate = entry.clone();
    candidate.content_sha256.clear();
    content_digest(b"operation-index", &candidate)
}

fn allocation_entry_digest(entry: &AllocationIdentityV1) -> Result<String, DurableFleetError> {
    let mut candidate = entry.clone();
    candidate.content_sha256.clear();
    content_digest(b"allocation-index", &candidate)
}

fn durable_state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    content_digest(b"durable-state", &candidate)
}

fn content_digest<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<String, DurableFleetError> {
    let encoded = serde_json::to_vec(value)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.");
    digest.update(domain);
    digest.update(b".v1\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn index_path(root: &Path, identity: &str) -> PathBuf {
    let digest = format!("{:x}", Sha256::digest(identity.as_bytes()));
    root.join(&digest[..2]).join(format!("{digest}.json"))
}

fn read_index_entry<T: for<'de> Deserialize<'de>>(
    path: &Path,
) -> Result<Option<T>, DurableFleetError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.file_type().is_file()
                || metadata.file_type().is_symlink()
                || metadata.len() > MAX_INDEX_ENTRY_BYTES
            {
                return Err(DurableFleetError::CorruptState);
            }
            Ok(Some(serde_json::from_slice(&std::fs::read(path)?)?))
        }
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

fn publish_index_entry<T: Serialize>(
    root: &Path,
    identity: &str,
    entry: &T,
    generation: u64,
) -> Result<(), DurableFleetError> {
    validate_identity(identity)?;
    ensure_private_directory(root)?;
    let final_path = index_path(root, identity);
    let shard = final_path
        .parent()
        .ok_or(DurableFleetError::InvalidPath)?;
    ensure_private_directory(shard)?;
    let temp_path = shard.join(format!(
        ".index-{generation}-{}-{}.tmp",
        std::process::id(),
        INDEX_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut encoded = serde_json::to_vec(entry)?;
    encoded.push(b'\n');
    let mut file = open_private_new_file(&temp_path)?;
    file.write_all(&encoded)?;
    file.sync_all()?;
    match std::fs::hard_link(&temp_path, &final_path) {
        Ok(()) => {
            let _ = std::fs::remove_file(&temp_path);
            if let Err(error) = sync_directory(shard).and_then(|()| sync_directory(root)) {
                return Err(DurableFleetError::IndeterminateCommit {
                    operation_id: identity.to_string(),
                    generation,
                    detail: error.to_string(),
                });
            }
            Ok(())
        }
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            let _ = std::fs::remove_file(&temp_path);
            Ok(())
        }
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            Err(error.into())
        }
    }
}

fn validate_identity(value: &str) -> Result<(), DurableFleetError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(DurableFleetError::InvalidOperationId);
    }
    Ok(())
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(unix)]
fn ensure_private_directory(path: &Path) -> Result<(), DurableFleetError> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::create_dir_all(path)?;
    validate_physical_directory(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    Ok(())
}

#[cfg(not(unix))]
fn ensure_private_directory(path: &Path) -> Result<(), DurableFleetError> {
    std::fs::create_dir_all(path)?;
    validate_physical_directory(path)
}

fn validate_physical_directory(path: &Path) -> Result<(), DurableFleetError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(DurableFleetError::InvalidPath);
    }
    Ok(())
}

#[cfg(unix)]
fn open_private_new_file(path: &Path) -> Result<File, DurableFleetError> {
    use std::os::unix::fs::OpenOptionsExt;

    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(Into::into)
}

#[cfg(not(unix))]
fn open_private_new_file(path: &Path) -> Result<File, DurableFleetError> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(Into::into)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}

#[cfg(test)]
#[path = "durable_owner_index_tests.rs"]
mod index_tests;
