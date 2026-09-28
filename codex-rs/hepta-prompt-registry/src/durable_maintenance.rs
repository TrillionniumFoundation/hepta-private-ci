//! Bounded checkpoint maintenance. No operation activates a checkpoint or erases
//! the source directory. Audit facts survive payload copy-compaction unchanged.

use std::fmt;
use std::fs::File;
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
#[cfg(unix)]
use std::time::Instant;
#[cfg(unix)]
use std::time::SystemTime;
#[cfg(unix)]
use std::time::UNIX_EPOCH;

use serde::Serialize;

use super::Access;
use super::DurablePromptRegistry;
use super::DurableRegistryError;
use super::MAX_STATE_BYTES;
use super::Store;
use super::entry_exists;
use super::open_private;
use super::payloads;
#[cfg(unix)]
use super::prepare_directory;
use super::restore_v4;
use super::stored_metadata;
use super::validate_restored;
use crate::MAX_REALIZATION_PAYLOAD_BYTES;
use crate::PromptRegistry;

const MAX_FSYNC_PROBE_BYTES: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptRegistryCheckpointKind {
    ConsistentExport,
    CompactedGc,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryQuota {
    pub maximum_logical_records: usize,
    pub maximum_payload_records: usize,
    pub maximum_payload_bytes: u64,
    pub maximum_payload_file_bytes: u64,
    pub maximum_single_payload_bytes: usize,
    pub maximum_metadata_bytes: u64,
    pub maximum_full_sized_payload_records: u64,
}

impl PromptRegistryQuota {
    fn for_registry(registry: &PromptRegistry) -> Self {
        Self {
            maximum_logical_records: registry.maximum_records,
            maximum_payload_records: registry.maximum_records,
            maximum_payload_bytes: payloads::MAX_PAYLOAD_BYTES,
            maximum_payload_file_bytes: payloads::MAX_PHYSICAL_PAYLOAD_FILE_BYTES,
            maximum_single_payload_bytes: MAX_REALIZATION_PAYLOAD_BYTES,
            maximum_metadata_bytes: MAX_STATE_BYTES,
            maximum_full_sized_payload_records: payloads::MAX_PAYLOAD_BYTES
                / u64::try_from(MAX_REALIZATION_PAYLOAD_BYTES).unwrap_or(u64::MAX),
        }
    }
}

/// Diagnostic counters, never an authorization or a provider success receipt.
/// After poisoning, logical values describe the last acknowledged in-memory
/// predecessor, not necessarily the image currently selected on disk.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryOperationalMetrics {
    /// Process-generation I/O observations, not persistent authority.
    pub io: super::PromptRegistryIoMetrics,
    pub active_storage_schema: u32,
    pub unselected_payload_file_bytes: u64,
    pub revision: u64,
    pub registry_digest: [u8; 32],
    pub authoritative: bool,
    pub factor_records: usize,
    pub admitted_factor_records: usize,
    pub realization_records: usize,
    pub active_realization_records: usize,
    pub inactive_realization_records: usize,
    pub relation_records: usize,
    pub lifecycle_event_records: usize,
    pub revocation_frontier: u64,
    pub payload_records: usize,
    pub selected_payload_bytes: u64,
    pub active_payload_bytes: u64,
    pub reclaimable_payload_records: usize,
    pub reclaimable_payload_bytes: u64,
    /// None: V4 has no durable GC enqueue timestamp. Never report an invented 0.
    pub oldest_reclaimable_age_ms: Option<u64>,
    pub physical_payload_file_bytes: u64,
    pub metadata_file_bytes: u64,
    pub remaining_logical_records: usize,
    pub remaining_payload_bytes: u64,
    pub remaining_metadata_bytes: u64,
    pub high_water_basis_points: u16,
    pub requires_reopen: bool,
    pub quota: PromptRegistryQuota,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryCheckpointReceipt {
    pub kind: PromptRegistryCheckpointKind,
    pub source_revision: u64,
    pub source_registry_digest: [u8; 32],
    pub checkpoint_revision: u64,
    pub checkpoint_registry_digest: [u8; 32],
    pub source_history_digest: [u8; 32],
    pub checkpoint_history_digest: [u8; 32],
    /// Bytes omitted from the destination; the source has NOT been erased.
    pub reclaimed_payload_records: usize,
    pub reclaimed_payload_bytes: u64,
    pub source_erased: bool,
    pub checkpoint_payload_records: usize,
    pub checkpoint_selected_payload_bytes: u64,
    pub checkpoint_physical_payload_file_bytes: u64,
    pub checkpoint_metadata_file_bytes: u64,
    pub verified_by_reopen: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryRestoreReceipt {
    pub revision: u64,
    pub registry_digest: [u8; 32],
    pub payload_records: usize,
    pub selected_payload_bytes: u64,
    pub physical_payload_file_bytes: u64,
    pub metadata_file_bytes: u64,
    pub verified: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryFsyncProbe {
    pub bytes: u64,
    pub open_nanos: u128,
    pub write_nanos: u128,
    pub file_sync_nanos: u128,
    pub directory_sync_nanos: u128,
    pub cleanup_directory_sync_nanos: u128,
    pub total_nanos: u128,
}

#[derive(Debug)]
pub enum PromptRegistryMaintenanceError {
    Durable(DurableRegistryError),
    DestinationNotEmpty,
    CheckpointVerificationMismatch,
    RestoreIdentityRequired,
    MissingCheckpoint,
    FsyncProbeSizeOutOfRange,
    FilesystemUnavailable,
    CleanupUncertain,
}

impl fmt::Display for PromptRegistryMaintenanceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptRegistryMaintenanceError {}

impl From<DurableRegistryError> for PromptRegistryMaintenanceError {
    fn from(error: DurableRegistryError) -> Self {
        Self::Durable(error)
    }
}

impl DurablePromptRegistry {
    /// Read diagnostics even when authoritative reads are fenced by poisoning.
    pub fn operational_metrics(
        &self,
    ) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
        metrics_for(self)
    }

    /// Copy a committed image. An identical completed destination is an
    /// idempotent retry; a different or partial destination is never overwritten.
    pub fn export_consistent_checkpoint(
        &self,
        destination: &Path,
    ) -> Result<PromptRegistryCheckpointReceipt, PromptRegistryMaintenanceError> {
        self.ensure_available()?;
        write_checkpoint(
            self,
            destination,
            self.registry.clone(),
            PromptRegistryCheckpointKind::ConsistentExport,
            0,
            0,
        )
    }

    /// Omit inactive payload bytes only. Retain identities, bindings, relations,
    /// supersession and the complete lifecycle/audit history. No live swap.
    pub fn checkpoint_compacted(
        &self,
        destination: &Path,
    ) -> Result<PromptRegistryCheckpointReceipt, PromptRegistryMaintenanceError> {
        self.ensure_available()?;
        let mut checkpoint = self.registry.clone();
        let before_records = checkpoint.realization_payloads.len();
        let before_bytes = payload_bytes(&checkpoint.realization_payloads);
        checkpoint.realization_payloads.retain(|id, _| {
            checkpoint
                .realizations
                .get(id)
                .is_some_and(|realization| realization.active)
        });
        let records = before_records.saturating_sub(checkpoint.realization_payloads.len());
        let bytes = before_bytes.saturating_sub(payload_bytes(&checkpoint.realization_payloads));
        validate_restored(&checkpoint)?;
        write_checkpoint(
            self,
            destination,
            checkpoint,
            PromptRegistryCheckpointKind::CompactedGc,
            records,
            bytes,
        )
    }

    /// Strict, non-mutating V4 verification. Both expected identity fields are
    /// mandatory and must come from a trusted current checkpoint receipt, not
    /// from the candidate itself. This is not restore activation or authority.
    /// Missing paths, legacy schemas and partial checkpoints fail without repair.
    pub fn verify_restore_checkpoint(
        directory: &Path,
        maximum_records: usize,
        expected_revision: Option<u64>,
        expected_registry_digest: Option<[u8; 32]>,
    ) -> Result<PromptRegistryRestoreReceipt, PromptRegistryMaintenanceError> {
        let (Some(revision), Some(digest)) = (expected_revision, expected_registry_digest) else {
            return Err(PromptRegistryMaintenanceError::RestoreIdentityRequired);
        };
        let owner = load_strict_checkpoint(directory, maximum_records)?;
        let metrics = owner.operational_metrics()?;
        if revision != metrics.revision || digest != metrics.registry_digest {
            return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
        }
        Ok(PromptRegistryRestoreReceipt {
            revision: metrics.revision,
            registry_digest: metrics.registry_digest,
            payload_records: metrics.payload_records,
            selected_payload_bytes: metrics.selected_payload_bytes,
            physical_payload_file_bytes: metrics.physical_payload_file_bytes,
            metadata_file_bytes: metrics.metadata_file_bytes,
            verified: true,
        })
    }

    /// Measure anchored private-file fsync without modifying any registry fact.
    pub fn probe_fsync(
        directory: &Path,
        bytes: u64,
    ) -> Result<PromptRegistryFsyncProbe, PromptRegistryMaintenanceError> {
        if bytes == 0 || bytes > MAX_FSYNC_PROBE_BYTES {
            return Err(PromptRegistryMaintenanceError::FsyncProbeSizeOutOfRange);
        }
        fsync_probe(directory, bytes)
    }
}

fn metrics_for(
    owner: &DurablePromptRegistry,
) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
    let registry = &owner.registry;
    let quota = PromptRegistryQuota::for_registry(registry);
    let selected_payload_bytes = payload_bytes(&registry.realization_payloads);
    let active_realization_records = registry.realizations.values().filter(|r| r.active).count();
    let mut active_payload_bytes = 0_u64;
    let mut reclaimable_payload_records = 0_usize;
    let mut reclaimable_payload_bytes = 0_u64;
    for (id, payload) in &registry.realization_payloads {
        let bytes = u64::try_from(payload.len()).unwrap_or(u64::MAX);
        if registry.realizations.get(id).is_some_and(|r| r.active) {
            active_payload_bytes = active_payload_bytes.saturating_add(bytes);
        } else {
            reclaimable_payload_records = reclaimable_payload_records.saturating_add(1);
            reclaimable_payload_bytes = reclaimable_payload_bytes.saturating_add(bytes);
        }
    }
    let physical_payload_file_bytes = file_bytes(&owner.store, owner.store.payloads.file_name())?;
    let metadata_file_bytes = file_bytes(&owner.store, "registry.json")?;
    let logical_records = registry
        .factors
        .len()
        .saturating_add(registry.realizations.len())
        .saturating_add(registry.relations.len());
    let high_water_basis_points = [
        basis_points(
            u64::try_from(logical_records).unwrap_or(u64::MAX),
            u64::try_from(quota.maximum_logical_records).unwrap_or(u64::MAX),
        ),
        basis_points(
            u64::try_from(registry.realization_payloads.len()).unwrap_or(u64::MAX),
            u64::try_from(quota.maximum_payload_records).unwrap_or(u64::MAX),
        ),
        basis_points(
            physical_payload_file_bytes,
            quota.maximum_payload_file_bytes,
        ),
        basis_points(metadata_file_bytes, quota.maximum_metadata_bytes),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);
    let unselected = owner.store.payloads.slot().other().file_name();
    let unselected_payload_file_bytes = if entry_exists(&owner.store.root, unselected)? {
        file_bytes(&owner.store, unselected)?
    } else {
        0
    };
    Ok(PromptRegistryOperationalMetrics {
        io: owner.store.io.clone(),
        active_storage_schema: if owner.store.payloads.uses_generation_manifest() {
            5
        } else {
            4
        },
        unselected_payload_file_bytes,
        revision: registry.revision.get(),
        registry_digest: registry.snapshot_digest().into_array(),
        authoritative: !owner.requires_reopen(),
        factor_records: registry.factors.len(),
        admitted_factor_records: registry
            .factors
            .values()
            .filter(|factor| factor.lifecycle == crate::Lifecycle::Admitted)
            .count(),
        realization_records: registry.realizations.len(),
        active_realization_records,
        inactive_realization_records: registry
            .realizations
            .len()
            .saturating_sub(active_realization_records),
        relation_records: registry.relations.len(),
        lifecycle_event_records: registry.lifecycle_events.len(),
        revocation_frontier: registry.revocation_frontier,
        payload_records: registry.realization_payloads.len(),
        selected_payload_bytes,
        active_payload_bytes,
        reclaimable_payload_records,
        reclaimable_payload_bytes,
        oldest_reclaimable_age_ms: None,
        physical_payload_file_bytes,
        metadata_file_bytes,
        remaining_logical_records: quota
            .maximum_logical_records
            .saturating_sub(logical_records),
        remaining_payload_bytes: quota
            .maximum_payload_file_bytes
            .saturating_sub(physical_payload_file_bytes),
        remaining_metadata_bytes: quota
            .maximum_metadata_bytes
            .saturating_sub(metadata_file_bytes),
        high_water_basis_points,
        requires_reopen: owner.requires_reopen(),
        quota,
    })
}

fn history_digest(registry: &PromptRegistry) -> Result<[u8; 32], PromptRegistryMaintenanceError> {
    let mut metadata = stored_metadata(registry);
    // The full snapshot digest includes payload presence. Audit equality must
    // deliberately exclude that digest and payload bytes, but no other facts.
    metadata.registry_digest = [0; 32];
    metadata.payloads.clear();
    let mut bytes = b"hepta.prompt-registry.retained-history.v1".to_vec();
    bytes.extend(
        serde_json::to_vec(&metadata)
            .map_err(|_| PromptRegistryMaintenanceError::CheckpointVerificationMismatch)?,
    );
    Ok(codex_hepta_types::Digest32::of_bytes(&bytes).into_array())
}

fn write_checkpoint(
    source: &DurablePromptRegistry,
    destination: &Path,
    checkpoint: PromptRegistry,
    kind: PromptRegistryCheckpointKind,
    reclaimed_payload_records: usize,
    reclaimed_payload_bytes: u64,
) -> Result<PromptRegistryCheckpointReceipt, PromptRegistryMaintenanceError> {
    validate_restored(&checkpoint)?;
    let source_history_digest = history_digest(&source.registry)?;
    let checkpoint_history_digest = history_digest(&checkpoint)?;
    if source_history_digest != checkpoint_history_digest {
        return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
    }
    // Atomic directory creation, not exists()/read_dir()/overwrite. Completed
    // retries are verified below. Partial directories remain available to audit.
    if create_destination(destination)? {
        let (mut store, prior) = Store::open(destination)?;
        if prior.is_some() {
            return Err(PromptRegistryMaintenanceError::DestinationNotEmpty);
        }
        store.persist(&checkpoint)?;
    }
    let reopened = load_strict_checkpoint(destination, checkpoint.maximum_records)?;
    if reopened.registry != checkpoint {
        return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
    }
    // Stabilize an identical retry after an unknown post-rename outcome. This
    // writes no data and makes no lifecycle transition or source-owner swap.
    open_private(
        &reopened.store.root,
        reopened.store.payloads.file_name(),
        Access::Read,
    )?
    .sync_all()
    .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?;
    open_private(&reopened.store.root, "registry.json", Access::Read)?
        .sync_all()
        .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?;
    reopened
        .store
        .root
        .sync_all()
        .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?;
    sync_parent(destination)?;
    let metrics = reopened.operational_metrics()?;
    Ok(PromptRegistryCheckpointReceipt {
        kind,
        source_revision: source.registry.revision.get(),
        source_registry_digest: source.registry.snapshot_digest().into_array(),
        checkpoint_revision: metrics.revision,
        checkpoint_registry_digest: metrics.registry_digest,
        source_history_digest,
        checkpoint_history_digest,
        reclaimed_payload_records,
        reclaimed_payload_bytes,
        source_erased: false,
        checkpoint_payload_records: metrics.payload_records,
        checkpoint_selected_payload_bytes: metrics.selected_payload_bytes,
        checkpoint_physical_payload_file_bytes: metrics.physical_payload_file_bytes,
        checkpoint_metadata_file_bytes: metrics.metadata_file_bytes,
        verified_by_reopen: true,
    })
}

/// Unlike open_state_dir, this path never creates a directory/lock, migrates,
/// republishes metadata, or trims an unselected payload tail.
fn load_strict_checkpoint(
    directory: &Path,
    maximum_records: usize,
) -> Result<DurablePromptRegistry, PromptRegistryMaintenanceError> {
    let root = open_existing_directory(directory)?;
    let lock = open_private(&root, "registry.lock", Access::Read)?;
    lock.try_lock()
        .map_err(|_| DurableRegistryError::StateLocked)?;
    let mut bytes = Vec::new();
    open_private(&root, "registry.json", Access::Read)?
        .take(MAX_STATE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
        return Err(DurableRegistryError::Corrupt.into());
    }
    let value: serde_json::Value =
        serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
    let (payloads, stored) = match value.get("schema").and_then(serde_json::Value::as_u64) {
        Some(4) => payloads::PayloadState::hydrate_v4(
            &root,
            serde_json::from_value(value).map_err(|_| DurableRegistryError::Corrupt)?,
        )?,
        Some(5) => payloads::PayloadState::hydrate_v5(
            &root,
            serde_json::from_value(value).map_err(|_| DurableRegistryError::Corrupt)?,
        )?,
        _ => return Err(DurableRegistryError::Corrupt.into()),
    };
    let actual_payload_bytes = open_private(&root, payloads.file_name(), Access::Read)?
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?
        .len();
    if actual_payload_bytes != payloads.selected_file_bytes() {
        return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
    }
    let registry = restore_v4(stored, maximum_records)?;
    Ok(DurablePromptRegistry {
        registry,
        store: Store {
            root,
            _lock: lock,
            payloads,
            io: super::PromptRegistryIoMetrics::default(),
            #[cfg(test)]
            fail_directory_sync_after_rename_once: std::cell::Cell::new(false),
            #[cfg(test)]
            fail_storage_full_before_rename_once: std::cell::Cell::new(false),
        },
        poisoned: false,
    })
}

#[cfg(unix)]
fn open_existing_directory(directory: &Path) -> Result<File, PromptRegistryMaintenanceError> {
    use std::os::unix::fs::MetadataExt;

    let root: File = rustix::fs::open(
        directory,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| PromptRegistryMaintenanceError::MissingCheckpoint)?
    .into();
    let metadata = root
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if metadata.mode() & 0o077 != 0 || metadata.uid() != rustix::process::geteuid().as_raw() {
        return Err(DurableRegistryError::UnsafeStateDirectory.into());
    }
    Ok(root)
}

#[cfg(unix)]
fn create_destination(destination: &Path) -> Result<bool, PromptRegistryMaintenanceError> {
    use std::os::unix::fs::DirBuilderExt;

    match std::fs::DirBuilder::new().mode(0o700).create(destination) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(false),
        Err(_) => Err(PromptRegistryMaintenanceError::FilesystemUnavailable),
    }
}

#[cfg(unix)]
fn sync_parent(destination: &Path) -> Result<(), PromptRegistryMaintenanceError> {
    let parent = destination
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let directory: File = rustix::fs::open(
        parent,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?
    .into();
    directory
        .sync_all()
        .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)
}

#[cfg(unix)]
fn fsync_probe(
    directory: &Path,
    bytes: u64,
) -> Result<PromptRegistryFsyncProbe, PromptRegistryMaintenanceError> {
    let root = prepare_directory(directory)?;
    let started = Instant::now();
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?
        .as_nanos();
    let name = format!(".prompt-fsync-{}-{stamp}", std::process::id());
    let open_started = Instant::now();
    let mut file: File = rustix::fs::openat(
        &root,
        name.as_str(),
        rustix::fs::OFlags::WRONLY
            | rustix::fs::OFlags::CREATE
            | rustix::fs::OFlags::EXCL
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?
    .into();
    let open_nanos = open_started.elapsed().as_nanos();
    // Cleanup starts only after exclusive creation succeeds: never unlink a
    // colliding pre-existing file belonging to another operation.
    let result: Result<(u128, u128, u128), PromptRegistryMaintenanceError> = (|| {
        let write_started = Instant::now();
        let length = usize::try_from(bytes)
            .map_err(|_| PromptRegistryMaintenanceError::FsyncProbeSizeOutOfRange)?;
        file.write_all(&vec![0_u8; length])
            .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
        let write_nanos = write_started.elapsed().as_nanos();
        let sync_started = Instant::now();
        file.sync_all()
            .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
        let file_sync_nanos = sync_started.elapsed().as_nanos();
        let dir_started = Instant::now();
        root.sync_all()
            .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
        Ok((
            write_nanos,
            file_sync_nanos,
            dir_started.elapsed().as_nanos(),
        ))
    })();
    drop(file);
    let cleanup_started = Instant::now();
    rustix::fs::unlinkat(&root, name.as_str(), rustix::fs::AtFlags::empty())
        .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?;
    root.sync_all()
        .map_err(|_| PromptRegistryMaintenanceError::CleanupUncertain)?;
    let cleanup_directory_sync_nanos = cleanup_started.elapsed().as_nanos();
    let (write_nanos, file_sync_nanos, directory_sync_nanos) = result?;
    Ok(PromptRegistryFsyncProbe {
        bytes,
        open_nanos,
        write_nanos,
        file_sync_nanos,
        directory_sync_nanos,
        cleanup_directory_sync_nanos,
        total_nanos: started.elapsed().as_nanos(),
    })
}

#[cfg(not(unix))]
fn open_existing_directory(_directory: &Path) -> Result<File, PromptRegistryMaintenanceError> {
    Err(DurableRegistryError::UnsafeStateDirectory.into())
}

#[cfg(not(unix))]
fn create_destination(_destination: &Path) -> Result<bool, PromptRegistryMaintenanceError> {
    Err(DurableRegistryError::UnsafeStateDirectory.into())
}

#[cfg(not(unix))]
fn sync_parent(_destination: &Path) -> Result<(), PromptRegistryMaintenanceError> {
    Err(DurableRegistryError::UnsafeStateDirectory.into())
}

#[cfg(not(unix))]
fn fsync_probe(
    _directory: &Path,
    _bytes: u64,
) -> Result<PromptRegistryFsyncProbe, PromptRegistryMaintenanceError> {
    Err(DurableRegistryError::UnsafeStateDirectory.into())
}

fn file_bytes(store: &Store, name: &str) -> Result<u64, PromptRegistryMaintenanceError> {
    if !entry_exists(&store.root, name)? {
        return Ok(0);
    }
    open_private(&store.root, name, Access::Read)?
        .metadata()
        .map(|metadata| metadata.len())
        .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)
}

fn payload_bytes(
    payloads: &std::collections::BTreeMap<codex_hepta_types::StableId, std::sync::Arc<[u8]>>,
) -> u64 {
    payloads.values().fold(0_u64, |total, payload| {
        total.saturating_add(u64::try_from(payload.len()).unwrap_or(u64::MAX))
    })
}

fn basis_points(current: u64, maximum: u64) -> u16 {
    if maximum == 0 {
        return 10_000;
    }
    u16::try_from(
        current
            .saturating_mul(10_000)
            .checked_div(maximum)
            .unwrap_or(10_000)
            .min(10_000),
    )
    .unwrap_or(10_000)
}

#[cfg(all(test, unix))]
#[path = "durable_maintenance_tests.rs"]
pub(super) mod tests;
