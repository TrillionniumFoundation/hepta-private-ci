
//! Bounded operational maintenance for the durable prompt registry.
//!
//! Maintenance never rewrites the live owner in place. It produces a fresh,
//! independently reopenable V4 checkpoint and returns a receipt that binds the
//! source and checkpoint identities. An external owner may switch to a verified
//! checkpoint only under its own quiescence and activation protocol.

use std::collections::BTreeSet;
use std::fmt;
#[cfg(unix)]
use std::fs::OpenOptions;
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
use super::validate_restored;
use crate::MAX_REALIZATION_PAYLOAD_BYTES;
use crate::PromptRegistry;

const MAX_FSYNC_PROBE_BYTES: u64 = 1024 * 1024;
const BASIS_POINTS_DENOMINATOR: u64 = 10_000;

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
            maximum_single_payload_bytes: MAX_REALIZATION_PAYLOAD_BYTES,
            maximum_metadata_bytes: MAX_STATE_BYTES,
            maximum_full_sized_payload_records: payloads::MAX_PAYLOAD_BYTES
                / u64::try_from(MAX_REALIZATION_PAYLOAD_BYTES).unwrap_or(u64::MAX),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryOperationalMetrics {
    pub revision: u64,
    pub registry_digest: [u8; 32],
    pub factor_records: usize,
    pub admitted_factor_records: usize,
    pub realization_records: usize,
    pub active_realization_records: usize,
    pub inactive_realization_records: usize,
    pub relation_records: usize,
    pub payload_records: usize,
    pub selected_payload_bytes: u64,
    pub active_payload_bytes: u64,
    pub reclaimable_payload_records: usize,
    pub reclaimable_payload_bytes: u64,
    pub physical_payload_file_bytes: u64,
    pub metadata_file_bytes: u64,
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
    pub reclaimed_payload_records: usize,
    pub reclaimed_payload_bytes: u64,
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
    FsyncProbeSizeOutOfRange,
    FilesystemUnavailable,
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
    /// Return one bounded view of the logical, selected and physical quotas.
    pub fn operational_metrics(
        &self,
    ) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
        self.ensure_available()?;
        metrics_for(self)
    }

    /// Export the current committed image to a fresh V4 checkpoint.
    ///
    /// The source owner is never rewritten. The destination must be absent or
    /// empty and is reopened before a successful receipt is returned.
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

    /// Produce a fresh V4 checkpoint that drops payload bytes for inactive
    /// realizations while preserving factor, realization, binding, relation,
    /// supersession and lifecycle history.
    ///
    /// This is copy-compaction. It does not switch or mutate the live owner.
    pub fn checkpoint_compacted(
        &self,
        destination: &Path,
    ) -> Result<PromptRegistryCheckpointReceipt, PromptRegistryMaintenanceError> {
        self.ensure_available()?;
        let mut checkpoint = self.registry.clone();
        let active_ids = checkpoint
            .realizations
            .iter()
            .filter_map(|(realization_id, realization)| {
                realization.active.then_some(realization_id.clone())
            })
            .collect::<BTreeSet<_>>();

        let before_records = checkpoint.realization_payloads.len();
        let before_bytes = payload_bytes(&checkpoint.realization_payloads);
        checkpoint
            .realization_payloads
            .retain(|realization_id, _| active_ids.contains(realization_id));
        let reclaimed_records = before_records.saturating_sub(checkpoint.realization_payloads.len());
        let reclaimed_bytes =
            before_bytes.saturating_sub(payload_bytes(&checkpoint.realization_payloads));

        validate_restored(&checkpoint)?;

        write_checkpoint(
            self,
            destination,
            checkpoint,
            PromptRegistryCheckpointKind::CompactedGc,
            reclaimed_records,
            reclaimed_bytes,
        )
    }

    /// Reopen and reconcile a checkpoint, optionally requiring an exact
    /// revision and registry digest.
    pub fn verify_restore_checkpoint(
        directory: &Path,
        maximum_records: usize,
        expected_revision: Option<u64>,
        expected_registry_digest: Option<[u8; 32]>,
    ) -> Result<PromptRegistryRestoreReceipt, PromptRegistryMaintenanceError> {
        let owner = Self::open_state_dir(directory, maximum_records)?;
        let metrics = owner.operational_metrics()?;
        if expected_revision.is_some_and(|expected| expected != metrics.revision)
            || expected_registry_digest
                .is_some_and(|expected| expected != metrics.registry_digest)
        {
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

    /// Measure one bounded private-file write, file fsync and directory fsync.
    ///
    /// The probe creates no registry fact and removes its private temporary file
    /// before returning.
    pub fn probe_fsync(
        directory: &Path,
        bytes: u64,
    ) -> Result<PromptRegistryFsyncProbe, PromptRegistryMaintenanceError> {
        if bytes == 0 || bytes > MAX_FSYNC_PROBE_BYTES {
            return Err(PromptRegistryMaintenanceError::FsyncProbeSizeOutOfRange);
        }

        #[cfg(not(unix))]
        {
            let _ = directory;
            return Err(PromptRegistryMaintenanceError::Durable(
                DurableRegistryError::UnsafeStateDirectory,
            ));
        }

        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;

            let root = prepare_directory(directory)?;
            let started = Instant::now();
            let stamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?
                .as_nanos();
            let name = format!(
                ".prompt-registry-fsync-probe-{}-{stamp}",
                std::process::id()
            );
            let path = directory.join(&name);
            let result = (|| {
                let open_started = Instant::now();
                let mut file = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .open(&path)
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let open_nanos = open_started.elapsed().as_nanos();

                let write_started = Instant::now();
                let length = usize::try_from(bytes)
                    .map_err(|_| PromptRegistryMaintenanceError::FsyncProbeSizeOutOfRange)?;
                file.write_all(&vec![0_u8; length])
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let write_nanos = write_started.elapsed().as_nanos();

                let file_sync_started = Instant::now();
                file.sync_all()
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let file_sync_nanos = file_sync_started.elapsed().as_nanos();

                let directory_sync_started = Instant::now();
                root.sync_all()
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let directory_sync_nanos = directory_sync_started.elapsed().as_nanos();

                drop(file);
                std::fs::remove_file(&path)
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let cleanup_sync_started = Instant::now();
                root.sync_all()
                    .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
                let cleanup_directory_sync_nanos = cleanup_sync_started.elapsed().as_nanos();

                Ok(PromptRegistryFsyncProbe {
                    bytes,
                    open_nanos,
                    write_nanos,
                    file_sync_nanos,
                    directory_sync_nanos,
                    cleanup_directory_sync_nanos,
                    total_nanos: started.elapsed().as_nanos(),
                })
            })();

            if result.is_err() {
                let _ = std::fs::remove_file(path);
                let _ = root.sync_all();
            }
            result
        }
    }
}

fn metrics_for(
    owner: &DurablePromptRegistry,
) -> Result<PromptRegistryOperationalMetrics, PromptRegistryMaintenanceError> {
    let registry = &owner.registry;
    let quota = PromptRegistryQuota::for_registry(registry);
    let selected_payload_bytes = payload_bytes(&registry.realization_payloads);
    let active_realization_records = registry
        .realizations
        .values()
        .filter(|realization| realization.active)
        .count();
    let mut active_payload_bytes = 0_u64;
    let mut reclaimable_payload_records = 0_usize;
    let mut reclaimable_payload_bytes = 0_u64;
    for (realization_id, payload) in &registry.realization_payloads {
        let bytes = u64::try_from(payload.len()).unwrap_or(u64::MAX);
        if registry
            .realizations
            .get(realization_id)
            .is_some_and(|realization| realization.active)
        {
            active_payload_bytes = active_payload_bytes.saturating_add(bytes);
        } else {
            reclaimable_payload_records = reclaimable_payload_records.saturating_add(1);
            reclaimable_payload_bytes = reclaimable_payload_bytes.saturating_add(bytes);
        }
    }
    let physical_payload_file_bytes = file_bytes(&owner.store, payloads::FILE_NAME)?;
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
            quota.maximum_payload_bytes,
        ),
        basis_points(metadata_file_bytes, quota.maximum_metadata_bytes),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);

    Ok(PromptRegistryOperationalMetrics {
        revision: registry.revision.get(),
        registry_digest: registry.snapshot_digest().into_array(),
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
        payload_records: registry.realization_payloads.len(),
        selected_payload_bytes,
        active_payload_bytes,
        reclaimable_payload_records,
        reclaimable_payload_bytes,
        physical_payload_file_bytes,
        metadata_file_bytes,
        high_water_basis_points,
        requires_reopen: owner.requires_reopen(),
        quota,
    })
}

fn write_checkpoint(
    source: &DurablePromptRegistry,
    destination: &Path,
    checkpoint: PromptRegistry,
    kind: PromptRegistryCheckpointKind,
    reclaimed_payload_records: usize,
    reclaimed_payload_bytes: u64,
) -> Result<PromptRegistryCheckpointReceipt, PromptRegistryMaintenanceError> {
    ensure_fresh_destination(destination)?;
    validate_restored(&checkpoint)?;
    let source_revision = source.registry.revision.get();
    let source_registry_digest = source.registry.snapshot_digest().into_array();
    let checkpoint_revision = checkpoint.revision.get();
    let checkpoint_registry_digest = checkpoint.snapshot_digest().into_array();
    let maximum_records = checkpoint.maximum_records;

    let (mut store, prior) = Store::open(destination)?;
    if prior.is_some() {
        return Err(PromptRegistryMaintenanceError::DestinationNotEmpty);
    }
    store.persist(&checkpoint)?;
    drop(store);

    let reopened = DurablePromptRegistry::open_state_dir(destination, maximum_records)?;
    let reopened_metrics = reopened.operational_metrics()?;
    if reopened_metrics.revision != checkpoint_revision
        || reopened_metrics.registry_digest != checkpoint_registry_digest
    {
        return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
    }

    Ok(PromptRegistryCheckpointReceipt {
        kind,
        source_revision,
        source_registry_digest,
        checkpoint_revision,
        checkpoint_registry_digest,
        reclaimed_payload_records,
        reclaimed_payload_bytes,
        checkpoint_payload_records: reopened_metrics.payload_records,
        checkpoint_selected_payload_bytes: reopened_metrics.selected_payload_bytes,
        checkpoint_physical_payload_file_bytes: reopened_metrics.physical_payload_file_bytes,
        checkpoint_metadata_file_bytes: reopened_metrics.metadata_file_bytes,
        verified_by_reopen: true,
    })
}

fn ensure_fresh_destination(
    destination: &Path,
) -> Result<(), PromptRegistryMaintenanceError> {
    if destination.exists() {
        if !destination.is_dir()
            || std::fs::read_dir(destination)
                .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?
                .next()
                .is_some()
        {
            return Err(PromptRegistryMaintenanceError::DestinationNotEmpty);
        }
    } else if let Some(parent) = destination.parent()
        && !parent.as_os_str().is_empty()
    {
        std::fs::create_dir_all(parent)
            .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)?;
    }
    Ok(())
}

fn file_bytes(
    store: &Store,
    name: &str,
) -> Result<u64, PromptRegistryMaintenanceError> {
    if !entry_exists(&store.root, name)? {
        return Ok(0);
    }
    open_private(&store.root, name, Access::Read)?
        .metadata()
        .map(|metadata| metadata.len())
        .map_err(|_| PromptRegistryMaintenanceError::FilesystemUnavailable)
}

fn payload_bytes(
    payloads: &std::collections::BTreeMap<
        codex_hepta_types::StableId,
        std::sync::Arc<[u8]>,
    >,
) -> u64 {
    payloads.values().fold(0_u64, |total, payload| {
        total.saturating_add(u64::try_from(payload.len()).unwrap_or(u64::MAX))
    })
}

fn basis_points(current: u64, maximum: u64) -> u16 {
    if maximum == 0 {
        return u16::MAX;
    }
    let value = current
        .saturating_mul(BASIS_POINTS_DENOMINATOR)
        .checked_div(maximum)
        .unwrap_or(BASIS_POINTS_DENOMINATOR)
        .min(BASIS_POINTS_DENOMINATOR);
    u16::try_from(value).unwrap_or(u16::MAX)
}

#[cfg(all(test, unix))]
mod tests {
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::time::Instant;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::FactorSource;
    use crate::Lifecycle;
    use crate::LifecycleEvent;
    use crate::LifecycleEventKind;
    use crate::PromptFactor;
    use crate::PromptRealizationBindingV2;
    use crate::PromptRoleV2;
    use crate::RegistryReceipt;
    use crate::TestMust;

    fn id(value: &str) -> StableId {
        StableId::new(value).must("test identity")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn factor(index: usize) -> PromptFactor {
        PromptFactor {
            factor_id: id(&format!("factor:{index}")),
            proposer_id: id("proposer:test"),
            semantic_version: id("v1"),
            semantic_purpose: "prompt registry operations test".into(),
            authority_class: "registered_prompt_factor".into(),
            eligible_objective_dimensions: vec![id("dimension:quality")],
            content_digest: digest(&format!("factor-content:{index}")),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        }
    }

    fn add_payload(
        core: &mut PromptRegistry,
        index: usize,
    ) -> Result<RegistryReceipt, crate::Error> {
        let factor = factor(index);
        let factor_id = factor.factor_id.clone();
        core.register_factor(factor)?;
        core.admit_factor(
            &factor_id,
            &id("reviewer:test"),
            digest("review-evidence"),
        )?;
        let payload = vec![65 + u8::try_from(index % 26).unwrap_or(0); 16 * 1024];
        core.register_realization_payload_v2(
            PromptRealizationBindingV2 {
                realization_id: id(&format!("realization:{index}")),
                factor_id,
                model_id: id("model:test"),
                model_version: "v1".into(),
                model_digest: digest("model"),
                tokenizer_digest: digest("tokenizer"),
                template_digest: digest("template"),
                tool_schema_digest: digest("tools"),
                context_profile_digest: digest("context"),
                locale_id: id("en-US"),
                role: PromptRoleV2::DeveloperInstruction,
                payload_digest: Digest32::of_bytes(&payload),
                token_cost: 4096,
                expires_unix_ms: None,
            },
            payload,
            None,
        )
    }

    #[test]
    fn operational_consistent_export_reopens_exactly() {
        let temporary = tempfile::tempdir().must("tempdir");
        let source = temporary.path().join("source");
        let destination = temporary.path().join("export");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&source, 64).must("source owner");
        owner
            .commit(|registry| add_payload(registry, 0))
            .must("seed payload");
        let source_metrics = owner.operational_metrics().must("source metrics");

        let receipt = owner
            .export_consistent_checkpoint(&destination)
            .must("consistent export");
        assert_eq!(receipt.kind, PromptRegistryCheckpointKind::ConsistentExport);
        assert_eq!(receipt.source_revision, receipt.checkpoint_revision);
        assert_eq!(
            receipt.source_registry_digest,
            receipt.checkpoint_registry_digest
        );
        assert!(receipt.verified_by_reopen);

        let restored = DurablePromptRegistry::verify_restore_checkpoint(
            &destination,
            64,
            Some(source_metrics.revision),
            Some(source_metrics.registry_digest),
        )
        .must("verify restore");
        assert!(restored.verified);
        assert_eq!(restored.payload_records, 1);
    }

    #[test]
    fn operational_compacted_checkpoint_reclaims_only_inactive_payloads() {
        let temporary = tempfile::tempdir().must("tempdir");
        let source = temporary.path().join("source");
        let destination = temporary.path().join("compacted");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&source, 64).must("source owner");
        owner
            .commit(|registry| add_payload(registry, 0))
            .must("seed payload");
        owner
            .retire_factor(
                &id("factor:0"),
                &id("operator:test"),
                digest("retirement"),
            )
            .must("retire factor");
        let before = owner.operational_metrics().must("metrics");
        assert_eq!(before.reclaimable_payload_records, 1);
        assert_eq!(before.reclaimable_payload_bytes, 16 * 1024);

        let receipt = owner
            .checkpoint_compacted(&destination)
            .must("compact checkpoint");
        assert_eq!(receipt.kind, PromptRegistryCheckpointKind::CompactedGc);
        assert_eq!(receipt.reclaimed_payload_records, 1);
        assert_eq!(receipt.reclaimed_payload_bytes, 16 * 1024);
        assert_eq!(receipt.checkpoint_payload_records, 0);
        assert!(
            owner
                .registry()
                .must("source registry")
                .realization_payloads
                .contains_key(&id("realization:0"))
        );

        let compacted =
            DurablePromptRegistry::open_state_dir(&destination, 64).must("open compacted");
        let compacted_registry = compacted.registry().must("compacted registry");
        assert_eq!(
            compacted_registry
                .realizations
                .get(&id("realization:0"))
                .map(|realization| realization.active),
            Some(false)
        );
        assert!(
            !compacted_registry
                .realization_payloads
                .contains_key(&id("realization:0"))
        );
    }

    #[test]
    fn operational_metrics_unify_logical_payload_and_byte_quotas() {
        let temporary = tempfile::tempdir().must("tempdir");
        let source = temporary.path().join("source");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&source, 64).must("source owner");
        owner
            .commit(|registry| add_payload(registry, 0))
            .must("seed payload");
        owner
            .retire_factor(
                &id("factor:0"),
                &id("operator:test"),
                digest("retirement"),
            )
            .must("retire factor");

        let metrics = owner.operational_metrics().must("metrics");
        assert_eq!(metrics.factor_records, 1);
        assert_eq!(metrics.realization_records, 1);
        assert_eq!(metrics.active_realization_records, 0);
        assert_eq!(metrics.payload_records, 1);
        assert_eq!(metrics.reclaimable_payload_bytes, 16 * 1024);
        assert_eq!(metrics.quota.maximum_logical_records, 64);
        assert_eq!(metrics.quota.maximum_payload_records, 64);
        assert_eq!(metrics.quota.maximum_full_sized_payload_records, 512);
        assert!(metrics.high_water_basis_points > 0);
    }

    #[test]
    fn operational_fsync_probe_is_bounded_and_cleans_up() {
        let temporary = tempfile::tempdir().must("tempdir");
        let directory = temporary.path().join("probe");
        let receipt =
            DurablePromptRegistry::probe_fsync(&directory, 4096).must("fsync probe");
        assert_eq!(receipt.bytes, 4096);
        assert!(
            std::fs::read_dir(directory)
                .must("read probe directory")
                .next()
                .is_none()
        );
        assert!(matches!(
            DurablePromptRegistry::probe_fsync(temporary.path(), 0),
            Err(PromptRegistryMaintenanceError::FsyncProbeSizeOutOfRange)
        ));
    }

    #[test]
    fn operational_unrenamed_metadata_is_never_selected() {
        let temporary = tempfile::tempdir().must("tempdir");
        let source = temporary.path().join("source");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&source, 64).must("source owner");
        owner
            .commit(|registry| add_payload(registry, 0))
            .must("seed payload");
        let expected = owner.registry().must("registry").clone();

        let mut staged =
            open_private(&owner.store.root, "registry.next", Access::Create)
                .must("staged metadata");
        staged.set_len(0).must("truncate staged metadata");
        staged
            .write_all(br#"{"schema":4,"state":{"schema":4}}"#)
            .must("write staged metadata");
        staged.sync_all().must("sync staged metadata");
        drop(staged);
        drop(owner);

        let reopened =
            DurablePromptRegistry::open_state_dir(&source, 64).must("reopen source");
        assert_eq!(reopened.registry().must("registry"), &expected);
    }

    #[test]
    fn operational_orphan_payload_tail_reconciliation_is_idempotent() {
        let temporary = tempfile::tempdir().must("tempdir");
        let source = temporary.path().join("source");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&source, 64).must("source owner");
        owner
            .commit(|registry| add_payload(registry, 0))
            .must("seed payload");
        let expected = owner.registry().must("registry").clone();
        let committed = file_bytes(&owner.store, payloads::FILE_NAME).must("file bytes");
        let mut payload =
            open_private(&owner.store.root, payloads::FILE_NAME, Access::Create)
                .must("payload file");
        payload.seek(SeekFrom::End(0)).must("seek payload tail");
        payload
            .write_all(b"orphan payload tail")
            .must("write orphan tail");
        payload.sync_all().must("sync orphan tail");
        drop(payload);
        drop(owner);

        let first =
            DurablePromptRegistry::open_state_dir(&source, 64).must("first reopen");
        assert_eq!(first.registry().must("registry"), &expected);
        assert_eq!(
            file_bytes(&first.store, payloads::FILE_NAME).must("first length"),
            committed
        );
        drop(first);
        let second =
            DurablePromptRegistry::open_state_dir(&source, 64).must("second reopen");
        assert_eq!(second.registry().must("registry"), &expected);
        assert_eq!(
            file_bytes(&second.store, payloads::FILE_NAME).must("second length"),
            committed
        );
    }

    #[test]
    #[ignore = "qualification operational profile"]
    fn operational_scale_profile_1k_8k_16k() {
        for count in [1000_usize, 8000, 16_384] {
            let build_started = Instant::now();
            let registry = large_registry(count);
            let build_micros = build_started.elapsed().as_micros();

            let digest_started = Instant::now();
            let registry_digest = registry.snapshot_digest();
            let digest_micros = digest_started.elapsed().as_micros();

            let temporary = tempfile::tempdir().must("tempdir");
            let destination = temporary.path().join(format!("registry-{count}"));
            let persist_started = Instant::now();
            let (mut store, prior) = Store::open(&destination).must("open store");
            assert!(prior.is_none());
            store.persist(&registry).must("persist profile registry");
            drop(store);
            let persist_micros = persist_started.elapsed().as_micros();

            let reopen_started = Instant::now();
            let reopened = DurablePromptRegistry::open_state_dir(&destination, count)
                .must("reopen profile registry");
            let reopen_micros = reopen_started.elapsed().as_micros();
            assert_eq!(
                reopened.registry().must("registry").snapshot_digest(),
                registry_digest
            );
            let metrics = reopened.operational_metrics().must("profile metrics");
            println!(
                "{}",
                serde_json::json!({
                    "schema": "hepta.prompt-registry.operational-scale.v1",
                    "records": count,
                    "buildMicros": build_micros,
                    "digestMicros": digest_micros,
                    "persistMicros": persist_micros,
                    "reopenMicros": reopen_micros,
                    "metadataBytes": metrics.metadata_file_bytes,
                    "payloadFileBytes": metrics.physical_payload_file_bytes,
                    "highWaterBasisPoints": metrics.high_water_basis_points,
                    "registryDigest": registry_digest.to_string(),
                })
            );
        }
    }

    #[test]
    #[ignore = "qualification operational profile"]
    fn operational_fsync_profile() {
        let temporary = tempfile::tempdir().must("tempdir");
        for bytes in [4096_u64, 64 * 1024, 1024 * 1024] {
            let directory = temporary.path().join(format!("probe-{bytes}"));
            let receipt =
                DurablePromptRegistry::probe_fsync(&directory, bytes).must("probe");
            println!(
                "{}",
                serde_json::to_string(&receipt).must("serialize fsync receipt")
            );
        }
    }

    fn large_registry(count: usize) -> PromptRegistry {
        let mut registry = PromptRegistry::new(count).must("registry");
        for index in 0..count {
            let factor = factor(index);
            let event_revision =
                Revision::new(u64::try_from(index).unwrap_or(u64::MAX) + 2)
                    .must("event revision");
            let mut event = LifecycleEvent {
                revision: event_revision,
                factor_id: factor.factor_id.clone(),
                kind: LifecycleEventKind::Registered,
                from: None,
                to: Lifecycle::Draft,
                actor_id: factor.proposer_id.clone(),
                admission_grant_id: None,
                evidence_digest: factor.content_digest,
                scope_digest: None,
                reason_digest: None,
                cutoff_unix_ms: None,
                event_digest: Digest32::ZERO,
            };
            event.event_digest = event.compute_digest();
            registry
                .factors
                .insert(factor.factor_id.clone(), factor);
            registry.lifecycle_events.push(event);
        }
        registry.revision =
            Revision::new(u64::try_from(count).unwrap_or(u64::MAX) + 1)
                .must("final revision");
        registry.lifecycle_frontier = registry.revision.get();
        validate_restored(&registry).must("profile registry");
        registry
    }
}
