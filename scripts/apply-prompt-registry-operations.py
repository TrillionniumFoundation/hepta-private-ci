#!/usr/bin/env python3
"""Apply the prompt.registry operational-closure patch on the bounded remediation branch.

This bootstrap is intentionally self-deleting. The resulting source commit contains
only the maintained implementation, tests, documentation and qualification workflows.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


MAINTENANCE_RS = r'''
//! Bounded operational maintenance for the durable prompt registry.
//!
//! Maintenance never rewrites the live owner in place. It produces a fresh,
//! independently reopenable V4 checkpoint and returns a receipt that binds the
//! source and checkpoint identities. An external owner may switch to a verified
//! checkpoint only under its own quiescence and activation protocol.

use std::collections::BTreeSet;
use std::fmt;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;
use std::time::SystemTime;
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
'''

MAP_GENERATOR = r'''
#!/usr/bin/env python3
"""Generate the curated prompt.registry implementation claims before exact-blob materialization."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
SOURCE_BASE = {
    "commit": "a126987b84737dbc2ee2592442a314117bddb4a2",
    "tree": "a22fd0074c45ae6f3cef2092cd6e273bf9c26c30",
}


def operation(
    name: str,
    symbol: str,
    source: str,
    authority: str,
    tests: list[str],
) -> dict:
    return {
        "operation": name,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "state": "source_composed_product_activation_pending",
        "authority": authority,
        "tests": tests,
        "sourcePathExists": True,
        "designOperation": name,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    }


def main() -> None:
    row = json.loads(PATH.read_text(encoding="utf-8"))
    row.update(
        {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceBase": SOURCE_BASE,
            "module": "prompt.registry",
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productCallerState": "source_composed",
            "productionWriterState": "source_composed_authenticated_publisher",
            "schemaState": "strict_durable_v4",
            "activePersistentSchema": 4,
            "closedWorldPublicFunctions": False,
            "lifecycleStates": {
                "sourceImplemented": True,
                "sourceComposed": True,
                "productActivated": False,
                "accepted": False,
                "released": False,
            },
            "status": {
                "implemented": True,
                "composed": True,
                "qualified": False,
            },
            "productCallers": [
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_pipeline.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_runtime.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_final_use.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
                    "state": "source_composed",
                },
            ],
        }
    )

    durable_tests = [
        "codex-rs/hepta-prompt-registry/src/durable.rs::tests",
        "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs::metadata_changes_never_rewrite_old_payloads_and_reopen_never_rewrites_manifest",
    ]
    maintenance_tests = [
        "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs::tests",
    ]
    row["operations"] = [
        operation(
            "open_state_dir",
            "DurablePromptRegistry::open_state_dir",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "exclusive_private_state_owner",
            durable_tests,
        ),
        operation(
            "register_factor_final_use",
            "DurablePromptRegistry::register_factor_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs::final_use"],
        ),
        operation(
            "register_factor_relation_final_use",
            "DurablePromptRegistry::register_factor_relation_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs::relation"],
        ),
        operation(
            "admit_factor_final_use",
            "DurablePromptRegistry::admit_factor_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs::admission"],
        ),
        operation(
            "register_realization_payload_final_use_v2",
            "DurablePromptRegistry::register_realization_payload_final_use_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs::delivery"],
        ),
        operation(
            "read_compatible_v2",
            "DurablePromptRegistry::read_compatible_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "deny_all_read_receipt",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs::compatible"],
        ),
        operation(
            "dereference_realization_v2",
            "DurablePromptRegistry::dereference_realization_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "deny_all_read_receipt",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs::dereference"],
        ),
        operation(
            "operational_metrics",
            "DurablePromptRegistry::operational_metrics",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_read",
            maintenance_tests,
        ),
        operation(
            "export_consistent_checkpoint",
            "DurablePromptRegistry::export_consistent_checkpoint",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_copy",
            maintenance_tests,
        ),
        operation(
            "checkpoint_compacted",
            "DurablePromptRegistry::checkpoint_compacted",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_copy",
            maintenance_tests,
        ),
        operation(
            "verify_restore_checkpoint",
            "DurablePromptRegistry::verify_restore_checkpoint",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_reopen",
            maintenance_tests,
        ),
        operation(
            "probe_fsync",
            "DurablePromptRegistry::probe_fsync",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "private_filesystem_probe",
            maintenance_tests,
        ),
    ]
    row["repositoryControlledGaps"] = [
        "Require green exact-head and deterministic synthetic-merge qualification receipts for the current source candidate.",
        "Require protected postmerge checks before any production-ready statement.",
        "Checkpoint activation remains an external quiescent owner decision; copy-compaction never self-switches the live store.",
    ]
    row["externalEvidenceGates"] = [
        "independent semantic and security review",
        "deployed product activation and target-host qualification",
        "operator acceptance, canary, promotion and release",
    ]
    row["claimBoundary"] = {
        "nativeSourceMappingComplete": True,
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "implementedOperationMappingComplete": True,
    }
    PATH.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
'''

MAP_REFRESH_WORKFLOW = r'''
name: Prompt registry exact implementation map refresh

on:
  workflow_dispatch:
  push:
    branches: [codex/prompt-registry-remediation-20260927]
    paths:
      - "codex-rs/hepta-prompt-registry/**"
      - "codex-rs/hepta-prompt-optimizer/**"
      - "codex-rs/hepta-agentd/src/prompt_*.rs"
      - "codex-rs/hepta-intelligence/src/prompt_delivery.rs"
      - "docs/modules/prompt.registry/TECHNICAL.md"
      - "docs/modules/prompt.registry/QUALIFICATION_STATUS.md"
      - "qualification/module-execution-dossiers/detail/prompt.registry.md"
      - "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
      - "scripts/hepta-prompt-registry-map.py"
      - "scripts/hepta-implementation-maps.py"
      - ".github/workflows/hepta-prompt-registry-qualification.yml"
      - ".github/workflows/prompt-registry-map-refresh.yml"

permissions:
  contents: write

concurrency:
  group: prompt-registry-map-refresh-${{ github.ref }}
  cancel-in-progress: true

jobs:
  refresh:
    runs-on: ubuntu-slim
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ github.sha }}
          fetch-depth: 0
          persist-credentials: true

      - name: Bind clean exact candidate
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"
          git diff --quiet
          git diff --cached --quiet
          git rev-parse HEAD HEAD^{tree}

      - name: Generate prompt.registry map from current source
        shell: bash
        env:
          PYTHONDONTWRITEBYTECODE: "1"
        run: |
          set -euo pipefail
          python3 scripts/hepta-prompt-registry-map.py
          python3 scripts/hepta-implementation-maps.py migrate --module prompt.registry
          python3 - <<'PY'
          import json
          from pathlib import Path
          path = Path("docs/modules/prompt.registry/IMPLEMENTATION_MAP.json")
          row = json.loads(path.read_text(encoding="utf-8"))
          if row.get("schema") != "hepta.module-implementation-map.v3":
              raise SystemExit("unexpected implementation-map schema")
          if row.get("module") != "prompt.registry":
              raise SystemExit("wrong implementation-map module")
          if not row.get("operations"):
              raise SystemExit("empty prompt.registry operation inventory")
          expected = {
              "sourceImplemented": True,
              "sourceComposed": True,
              "productActivated": False,
              "accepted": False,
              "released": False,
          }
          if row.get("lifecycleStates") != expected:
              raise SystemExit("prompt.registry lifecycle states drifted")
          print(json.dumps({
              "module": row["module"],
              "sourceBase": row.get("sourceBase"),
              "observedAtHead": row.get("observedAtHead"),
              "operations": len(row["operations"]),
              "lifecycleStates": row["lifecycleStates"],
          }, sort_keys=True))
          PY
          git diff --check -- docs/modules/prompt.registry/IMPLEMENTATION_MAP.json

      - name: Commit exact generated map
        shell: bash
        run: |
          set -euo pipefail
          if git diff --quiet -- docs/modules/prompt.registry/IMPLEMENTATION_MAP.json; then
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/modules/prompt.registry/IMPLEMENTATION_MAP.json
          git commit -m "prompt.registry: refresh exact implementation map [prompt-registry-map]"
          git push origin "HEAD:${GITHUB_REF_NAME}"
'''

BOOTSTRAP_WORKFLOW = r'''
name: Prompt registry operational closure bootstrap

on:
  push:
    branches: [codex/prompt-registry-remediation-20260927]
    paths:
      - "scripts/apply-prompt-registry-operations.py"
      - ".github/workflows/prompt-registry-operations-bootstrap.yml"

permissions:
  contents: write

concurrency:
  group: prompt-registry-operations-bootstrap-${{ github.sha }}
  cancel-in-progress: false

jobs:
  apply:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ github.sha }}
          fetch-depth: 0
          persist-credentials: true

      - name: Bind exact bootstrap source
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"
          git diff --quiet
          git diff --cached --quiet

      - name: Install pinned Rust toolchain
        uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582
        with:
          toolchain: 1.95.0
          components: rustfmt, clippy

      - name: Apply bounded operational closure
        run: python3 scripts/apply-prompt-registry-operations.py

      - name: Format and test prompt registry
        working-directory: codex-rs
        shell: bash
        run: |
          set -euo pipefail
          cargo fmt --package codex-hepta-prompt-registry
          cargo test --locked -p codex-hepta-prompt-registry -- --nocapture --test-threads=1
          cargo test --locked -p codex-hepta-prompt-registry operational_ -- --ignored --nocapture --test-threads=1
          cargo clippy --locked -p codex-hepta-prompt-registry --all-targets --no-deps -- -D warnings

      - name: Validate generated Python and documents
        shell: bash
        run: |
          set -euo pipefail
          python3 - <<'PY'
          from pathlib import Path
          compile(
              Path("scripts/hepta-prompt-registry-map.py").read_text(encoding="utf-8"),
              "scripts/hepta-prompt-registry-map.py",
              "exec",
          )
          PY
          python3 scripts/hepta-prompt-registry-map.py
          python3 scripts/hepta-implementation-maps.py migrate --module prompt.registry
          git checkout -- docs/modules/prompt.registry/IMPLEMENTATION_MAP.json
          git diff --check

      - name: Commit operational closure
        shell: bash
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --cached --check
          git commit -m "prompt.registry: add operational checkpoint and qualification"
          git push origin "HEAD:${GITHUB_REF_NAME}"
'''

write("codex-rs/hepta-prompt-registry/src/durable_maintenance.rs", MAINTENANCE_RS)

replace_once(
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    '''#[path = "durable_payloads.rs"]
mod payloads;
''',
    '''#[path = "durable_payloads.rs"]
mod payloads;
#[path = "durable_maintenance.rs"]
mod maintenance;

pub use maintenance::PromptRegistryCheckpointKind;
pub use maintenance::PromptRegistryCheckpointReceipt;
pub use maintenance::PromptRegistryFsyncProbe;
pub use maintenance::PromptRegistryMaintenanceError;
pub use maintenance::PromptRegistryOperationalMetrics;
pub use maintenance::PromptRegistryQuota;
pub use maintenance::PromptRegistryRestoreReceipt;
''',
)

replace_once(
    "codex-rs/hepta-prompt-registry/src/lib.rs",
    "pub use durable::DurableRegistryError;\n",
    '''pub use durable::DurableRegistryError;
pub use durable::PromptRegistryCheckpointKind;
pub use durable::PromptRegistryCheckpointReceipt;
pub use durable::PromptRegistryFsyncProbe;
pub use durable::PromptRegistryMaintenanceError;
pub use durable::PromptRegistryOperationalMetrics;
pub use durable::PromptRegistryQuota;
pub use durable::PromptRegistryRestoreReceipt;
''',
)

replace_once(
    "codex-rs/hepta-prompt-registry/src/durable_payloads.rs",
    "const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;\n",
    "pub(super) const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;\n",
)

write("scripts/hepta-prompt-registry-map.py", MAP_GENERATOR)
write(".github/workflows/prompt-registry-map-refresh.yml", MAP_REFRESH_WORKFLOW)

qualification = ROOT / ".github/workflows/hepta-prompt-registry-qualification.yml"
qualification_text = qualification.read_text(encoding="utf-8")
qualification_text = qualification_text.replace(
    '      - "scripts/hepta-implementation-maps.py"\n',
    '      - "scripts/hepta-implementation-maps.py"\n'
    '      - "scripts/hepta-prompt-registry-map.py"\n',
)
profile_step = r'''
      - name: Measure prompt registry scale and fsync profiles
        working-directory: codex-rs
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p ../qualification-operational
          cargo test --locked -p codex-hepta-prompt-registry operational_ \
            -- --ignored --nocapture --test-threads=1 2>&1 \
            | tee ../qualification-operational/prompt-registry-${{ matrix.lane }}.log

      - name: Upload prompt registry operational profile
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: prompt-registry-operational-${{ matrix.lane }}-${{ github.run_id }}
          path: qualification-operational/prompt-registry-${{ matrix.lane }}.log
          if-no-files-found: error
          retention-days: 30

'''
clippy_anchor = "      - name: Strict prompt-owned Clippy\n"
if profile_step.strip() not in qualification_text:
    if qualification_text.count(clippy_anchor) != 1:
        raise SystemExit("qualification workflow: strict Clippy anchor drifted")
    qualification_text = qualification_text.replace(
        clippy_anchor, profile_step + clippy_anchor
    )

receipt_anchor = '''          target = pathlib.Path("qualification-receipts") / f"prompt-registry-{os.environ['MATRIX_LANE']}.json"
'''
receipt_insert = '''          profile_path = pathlib.Path("qualification-operational") / f"prompt-registry-{os.environ['MATRIX_LANE']}.log"
          receipt["operationalProfileSha256"] = hashlib.sha256(profile_path.read_bytes()).hexdigest()
          receipt["operationalProfilePath"] = profile_path.as_posix()
          target = pathlib.Path("qualification-receipts") / f"prompt-registry-{os.environ['MATRIX_LANE']}.json"
'''
if receipt_insert not in qualification_text:
    if qualification_text.count(receipt_anchor) != 1:
        raise SystemExit("qualification workflow: receipt anchor drifted")
    qualification_text = qualification_text.replace(receipt_anchor, receipt_insert)
qualification.write_text(qualification_text, encoding="utf-8")

status = ROOT / "docs/modules/prompt.registry/QUALIFICATION_STATUS.md"
status_text = status.read_text(encoding="utf-8")
status_text = status_text.replace(
    "The registry, strict durable V4 relation state, authenticated publisher, consumer capability filtering and dispatch-time final-use fencing exist in source.",
    "The registry, strict durable V4 relation state, authenticated publisher, consumer capability filtering, dispatch-time final-use fencing, copy-compacted checkpoints, unified quota metrics, restore verification and fsync probes exist in source.",
)
status_text += """

## Operational evidence boundary

The owner can export or copy-compact one independently reopenable V4 checkpoint,
report unified logical/payload/byte quotas, verify a restore candidate, and emit
bounded fsync and 1k/8k/16k profiles. Checkpoint creation never switches the live
store. Product activation, operator acceptance and release remain external
decisions even when these source tests pass.
"""
status.write_text(status_text.strip() + "\n", encoding="utf-8")

technical = ROOT / "docs/modules/prompt.registry/TECHNICAL.md"
technical_text = technical.read_text(encoding="utf-8")
marker = "## Operational checkpoints, quotas and measurement"
if marker not in technical_text:
    technical_text += r'''

## Operational checkpoints, quotas and measurement

`DurablePromptRegistry` exposes a read-only operational metrics snapshot that
unifies logical-record, payload-record, selected/physical payload-byte,
single-payload and metadata ceilings. The metrics distinguish selected active
payload bytes from reclaimable inactive payload bytes and report a bounded
high-water value. These are owner-local facts, not acceptance or deployment
authority.

`export_consistent_checkpoint` writes the current committed V4 image to a fresh
private directory and reopens it before issuing a receipt.
`checkpoint_compacted` copy-compacts into another fresh directory, retaining
factor, realization, binding, relation, supersession and lifecycle history while
omitting payload bytes for inactive realizations. Neither operation rewrites or
switches the live owner. Activation of a verified checkpoint requires an
external quiescent owner protocol.

`verify_restore_checkpoint` reopens and reconciles one candidate against an
optional exact revision and registry digest. `probe_fsync` measures a bounded
private temporary-file write, file synchronization and directory
synchronization, then removes the probe. The module qualification workflow runs
the named 1k/8k/16k logical-scale and bounded fsync profiles and binds their log
digest into the exact qualification receipt. A WAL, Merkle tree or incremental
digest remains unjustified until those measurements show a material bottleneck.
'''
technical.write_text(technical_text.rstrip() + "\n", encoding="utf-8")

dossier = ROOT / "qualification/module-execution-dossiers/detail/prompt.registry.md"
dossier_text = dossier.read_text(encoding="utf-8")
dossier_text = dossier_text.replace(
    """Payload-generation compaction/GC, unified logical-record/payload/byte quota,
operational metrics, online consistent export/restore verification and
1k/8k/16k measurements remain qualification work. No WAL, Merkle or incremental
digest design is justified until those measurements exist.""",
    """The source owner now exposes unified logical-record/payload/byte quota
metrics, consistent checkpoint export, copy-compaction/GC into a fresh V4
directory, restore verification and bounded fsync probes. The qualification
workflow executes the 1k/8k/16k logical-scale and fsync profiles and binds the
profile digest into each exact-candidate receipt. No WAL, Merkle or incremental
digest design is justified unless those measurements identify a material
bottleneck.""",
)
dossier_text = dossier_text.replace(
    """4. implement and qualify payload checkpoint/compaction/GC and unified quotas;
5. add capacity/fsync metrics, consistent export/restore verification and the
   named crash-injection matrix;
6. run 1k/8k/16k measurements and record the decision on WAL/incremental
   digest work;
7. obtain independent product activation, acceptance and release decisions.""",
    """4. review the emitted 1k/8k/16k and fsync profiles and record whether any
   WAL, Merkle or incremental-digest work is justified;
5. qualify external quiescent checkpoint activation and rollback in the named
   product environment;
6. obtain independent product activation, acceptance and release decisions.""",
)
dossier_text = dossier_text.replace(
    "- included optimizer relation graph tests rather than an orphan source file.\n",
    "- included optimizer relation graph tests rather than an orphan source file;\n"
    "- copy-compacted V4 checkpoints, unified quota metrics, restore verification,\n"
    "  bounded fsync probes and operational scale profiles.\n",
)
dossier.write_text(dossier_text, encoding="utf-8")

profiles = ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
profiles_data = json.loads(profiles.read_text(encoding="utf-8"))
prompt_profile = next(
    row for row in profiles_data["modules"] if row.get("module") == "prompt.registry"
)
prompt_profile.update(
    {
        "implementationState": "durable_v4_source_composed_product_activation_pending",
        "apiContract": "DurablePromptRegistry owns authenticated factor, relation and realization publication; exact-model and consumer-capability reads; payload dereference; copy-compacted V4 checkpoints; unified quota metrics; restore verification; and bounded fsync probes. Source composition does not activate a deployed product.",
        "stateAndEncoding": "Strict V4 metadata binds factors, realizations, bindings, relations, supersession and lifecycle history. Immutable payload extents are selected by atomic metadata. Inactive realizations may omit payload bytes in a verified compacted checkpoint; active realizations may not.",
        "linearizationAndRecovery": "New payload bytes sync before metadata rename and directory sync. Post-rename uncertainty poisons the writer until reopen. Export and compaction write a fresh directory and reopen it before receipt; neither self-switches the live owner.",
        "algorithmAndBounds": "Logical records <=16384, one payload <=64 KiB, selected physical payload extent <=32 MiB and metadata <=32 MiB. Metrics report logical, payload and byte high-water values. Qualification measures 1k/8k/16k snapshots and bounded fsync latency before any WAL or incremental-digest decision.",
        "acceptanceOracle": "Relations and revocation survive reopen; unsupported consumer roles are filtered before staging; revoke-before-dispatch fails closed and remains revoked after restart; unselected payload and metadata tails never become facts; compacted checkpoints reopen with identical retained semantics and without inactive payload bytes.",
        "productTestsExecuted": False,
        "deploymentQualified": False,
    }
)
native = prompt_profile.setdefault("nativeImplementation", {})
native["entrypoints"] = [
    {
        "path": "codex-rs/hepta-prompt-registry/src/durable.rs",
        "symbol": "DurablePromptRegistry",
    },
    {
        "path": "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
        "symbol": "DurablePromptRegistry::checkpoint_compacted",
    },
    {
        "path": "codex-rs/hepta-agentd/src/prompt_pipeline.rs",
        "symbol": "AgentdPromptPipelineOwner",
    },
    {
        "path": "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
        "symbol": "PromptFinalUseStore",
    },
]
native["stateAndRecovery"] = (
    "Strict durable V4 with exclusive private state-directory ownership, "
    "immutable payload extents, atomic metadata publication, poison-and-reopen "
    "after indeterminate directory sync, authenticated publisher ingress, "
    "dispatch-time final-use fencing, and independently reopenable copy checkpoints."
)
native["testFiles"] = [
    "codex-rs/hepta-prompt-registry/src/lib_tests.rs",
    "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs",
    "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
    "codex-rs/hepta-prompt-optimizer/tests/registry_graph.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
]
native["runtimeDocuments"] = [
    "docs/modules/prompt.registry/TECHNICAL.md",
    "docs/modules/prompt.registry/QUALIFICATION_STATUS.md",
    "qualification/module-execution-dossiers/detail/prompt.registry.md",
]
native["remainingWork"] = [
    "Make exact-head and deterministic base-merge qualification receipts and protected postmerge checks green for the current candidate.",
    "Review measured 1k/8k/16k and fsync profiles before approving any WAL, Merkle or incremental-digest work.",
    "Qualify external quiescent checkpoint activation and rollback, then obtain independent product activation, acceptance and release decisions.",
]
profiles.write_text(json.dumps(profiles_data, indent=2) + "\n", encoding="utf-8")

# The bootstrap mechanism is not part of the maintained product tree.
(ROOT / "scripts/apply-prompt-registry-operations.py").unlink()
(ROOT / ".github/workflows/prompt-registry-operations-bootstrap.yml").unlink()