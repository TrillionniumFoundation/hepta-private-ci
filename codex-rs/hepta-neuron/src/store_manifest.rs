//! Crash-safe generation manifest and bounded segment index for Neuron stores.
//!
//! Journal, acknowledgement-witness and operation files remain independently
//! checksummed formats. This manifest publishes only a coherent set of already
//! created and synced files. Atomic same-directory replacement makes a rollover
//! visible as one generation transition; an unreferenced file left by a crash is
//! an orphan, never an implicitly admitted segment.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;
use std::str::FromStr;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use crate::JournalAnchor;
use crate::JournalScope;

pub const NEURON_STORE_MANIFEST_SCHEMA_V1: u32 = 1;
pub const NEURON_JOURNAL_ROOT_FORMAT_V1: &str = "HPTNSJ01";
pub const NEURON_JOURNAL_SUCCESSOR_FORMAT_V1: &str = "HPTNSJ02";
pub const NEURON_WITNESS_ROOT_FORMAT_V1: &str = "HPTNWA01";
pub const NEURON_WITNESS_SUCCESSOR_FORMAT_V1: &str = "HPTNWA02";
pub const NEURON_OPERATION_FORMAT_V1: &str = "HPTNOP01";

const MANIFEST_DOMAIN: &[u8] = b"hepta.neuron.store-manifest.v1";
const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_SEGMENTS_PER_KIND: usize = 1024;
const MAX_FILE_NAME_BYTES: usize = 128;
const MAX_FORMAT_ID_BYTES: usize = 32;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NeuronStoreSegmentKindV1 {
    Journal,
    Witness,
    Operation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStoreSegmentV1 {
    pub kind: NeuronStoreSegmentKindV1,
    pub ordinal: u32,
    pub file_name: String,
    pub format_id: String,
    pub seed_anchor: Option<JournalAnchor>,
    pub frontier_anchor: Option<JournalAnchor>,
    pub header_digest: Digest32,
    pub byte_length: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronStoreMigrationV1 {
    NativeV1,
    V1ToV2Prepared {
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
    },
    V1ToV2Committed {
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
        migrated_checkpoint_digest: Digest32,
        commit_receipt_digest: Digest32,
    },
    V1ToV2Aborted {
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
        abort_receipt_digest: Digest32,
    },
}

impl NeuronStoreMigrationV1 {
    #[must_use]
    pub const fn durable_version(&self) -> u8 {
        match self {
            Self::V1ToV2Committed { .. } => 2,
            Self::NativeV1
            | Self::V1ToV2Prepared { .. }
            | Self::V1ToV2Aborted { .. } => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStoreBootstrapV1 {
    pub generation: Generation,
    pub scope: JournalScope,
    pub runtime_config_digest: Digest32,
    pub key_epoch: u64,
    pub key_receipt_digest: Option<Digest32>,
    pub deletion_epoch: u64,
    pub deletion_receipt_digest: Option<Digest32>,
    pub predecessor_manifest_digest: Option<Digest32>,
    pub journal_file_name: String,
    pub journal_header_digest: Digest32,
    pub journal_header_bytes: u64,
    pub witness_file_name: String,
    pub witness_header_digest: Digest32,
    pub witness_header_bytes: u64,
    pub operation_file_name: String,
    pub operation_header_digest: Digest32,
    pub operation_header_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStoreManifestV1 {
    pub generation: Generation,
    pub scope: JournalScope,
    pub runtime_config_digest: Digest32,
    pub key_epoch: u64,
    pub key_receipt_digest: Option<Digest32>,
    pub deletion_epoch: u64,
    pub deletion_receipt_digest: Option<Digest32>,
    pub predecessor_manifest_digest: Option<Digest32>,
    pub segments: Vec<NeuronStoreSegmentV1>,
    pub current_journal_ordinal: u32,
    pub current_witness_ordinal: u32,
    pub operation_file_name: String,
    pub migration: NeuronStoreMigrationV1,
    pub manifest_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStoreReplayPlanV1 {
    pub journal_files: Vec<String>,
    pub witness_files: Vec<String>,
    pub operation_file: String,
    pub total_bytes: u64,
    pub manifest_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronStoreManifestError {
    Invalid(&'static str),
    DigestMismatch,
    Conflict,
    Capacity,
    ReplayBound,
    MigrationState,
    Json,
    Io(io::ErrorKind),
}

impl fmt::Display for NeuronStoreManifestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronStoreManifestError {}

impl From<io::Error> for NeuronStoreManifestError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl NeuronStoreManifestV1 {
    pub fn bootstrap(value: NeuronStoreBootstrapV1) -> Result<Self, NeuronStoreManifestError> {
        let mut manifest = Self {
            generation: value.generation,
            scope: value.scope,
            runtime_config_digest: value.runtime_config_digest,
            key_epoch: value.key_epoch,
            key_receipt_digest: value.key_receipt_digest,
            deletion_epoch: value.deletion_epoch,
            deletion_receipt_digest: value.deletion_receipt_digest,
            predecessor_manifest_digest: value.predecessor_manifest_digest,
            segments: vec![
                NeuronStoreSegmentV1 {
                    kind: NeuronStoreSegmentKindV1::Journal,
                    ordinal: 0,
                    file_name: value.journal_file_name,
                    format_id: NEURON_JOURNAL_ROOT_FORMAT_V1.to_owned(),
                    seed_anchor: None,
                    frontier_anchor: None,
                    header_digest: value.journal_header_digest,
                    byte_length: value.journal_header_bytes,
                },
                NeuronStoreSegmentV1 {
                    kind: NeuronStoreSegmentKindV1::Witness,
                    ordinal: 0,
                    file_name: value.witness_file_name,
                    format_id: NEURON_WITNESS_ROOT_FORMAT_V1.to_owned(),
                    seed_anchor: None,
                    frontier_anchor: None,
                    header_digest: value.witness_header_digest,
                    byte_length: value.witness_header_bytes,
                },
                NeuronStoreSegmentV1 {
                    kind: NeuronStoreSegmentKindV1::Operation,
                    ordinal: 0,
                    file_name: value.operation_file_name.clone(),
                    format_id: NEURON_OPERATION_FORMAT_V1.to_owned(),
                    seed_anchor: None,
                    frontier_anchor: None,
                    header_digest: value.operation_header_digest,
                    byte_length: value.operation_header_bytes,
                },
            ],
            current_journal_ordinal: 0,
            current_witness_ordinal: 0,
            operation_file_name: value.operation_file_name,
            migration: NeuronStoreMigrationV1::NativeV1,
            manifest_digest: Digest32::ZERO,
        };
        manifest.reseal()?;
        Ok(manifest)
    }

    /// Publish one completed operation frontier across journal, witness and
    /// full-result operation store. This API intentionally cannot represent the
    /// transient prepared/journal-only states internal to runtime recovery.
    pub fn advance_completed_frontier(
        &self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
        journal_bytes: u64,
        witness_bytes: u64,
        operation_bytes: u64,
    ) -> Result<Self, NeuronStoreManifestError> {
        if !matches!(
            self.migration,
            NeuronStoreMigrationV1::NativeV1 | NeuronStoreMigrationV1::V1ToV2Aborted { .. }
        ) {
            return Err(NeuronStoreManifestError::MigrationState);
        }
        if next.sequence == 0
            || next.checkpoint_digest.is_zero()
            || expected.map_or(next.sequence != 1, |anchor| {
                anchor.sequence.checked_add(1) != Some(next.sequence)
            })
        {
            return Err(NeuronStoreManifestError::Invalid("frontier successor"));
        }
        let mut value = self.clone();
        let journal = value.current_segment_mut(NeuronStoreSegmentKindV1::Journal)?;
        if journal.frontier_anchor != expected || journal_bytes < journal.byte_length {
            return Err(NeuronStoreManifestError::Conflict);
        }
        journal.frontier_anchor = Some(next);
        journal.byte_length = journal_bytes;

        let witness = value.current_segment_mut(NeuronStoreSegmentKindV1::Witness)?;
        if witness.frontier_anchor != expected || witness_bytes < witness.byte_length {
            return Err(NeuronStoreManifestError::Conflict);
        }
        witness.frontier_anchor = Some(next);
        witness.byte_length = witness_bytes;

        let operation = value.current_segment_mut(NeuronStoreSegmentKindV1::Operation)?;
        if operation_bytes < operation.byte_length {
            return Err(NeuronStoreManifestError::Conflict);
        }
        operation.byte_length = operation_bytes;
        value.reseal()?;
        Ok(value)
    }

    /// Atomically describe a paired journal/witness rollover after both new
    /// files were created, fully synced and seeded from the same exact frontier.
    /// Publishing this returned manifest is the commit point. Orphan files from
    /// a crash before publication are ignored during bounded startup replay.
    #[allow(clippy::too_many_arguments)]
    pub fn rollover_pair(
        &self,
        journal_file_name: String,
        journal_header_digest: Digest32,
        journal_header_bytes: u64,
        witness_file_name: String,
        witness_header_digest: Digest32,
        witness_header_bytes: u64,
    ) -> Result<Self, NeuronStoreManifestError> {
        let frontier = self.coherent_frontier()?.ok_or(
            NeuronStoreManifestError::Invalid("rollover requires committed frontier"),
        )?;
        let journal_ordinal = self
            .current_journal_ordinal
            .checked_add(1)
            .ok_or(NeuronStoreManifestError::Capacity)?;
        let witness_ordinal = self
            .current_witness_ordinal
            .checked_add(1)
            .ok_or(NeuronStoreManifestError::Capacity)?;
        if usize::try_from(journal_ordinal).map_err(|_| NeuronStoreManifestError::Capacity)?
            >= MAX_SEGMENTS_PER_KIND
            || usize::try_from(witness_ordinal)
                .map_err(|_| NeuronStoreManifestError::Capacity)?
                >= MAX_SEGMENTS_PER_KIND
        {
            return Err(NeuronStoreManifestError::Capacity);
        }
        let mut value = self.clone();
        value.segments.push(NeuronStoreSegmentV1 {
            kind: NeuronStoreSegmentKindV1::Journal,
            ordinal: journal_ordinal,
            file_name: journal_file_name,
            format_id: NEURON_JOURNAL_SUCCESSOR_FORMAT_V1.to_owned(),
            seed_anchor: Some(frontier),
            frontier_anchor: Some(frontier),
            header_digest: journal_header_digest,
            byte_length: journal_header_bytes,
        });
        value.segments.push(NeuronStoreSegmentV1 {
            kind: NeuronStoreSegmentKindV1::Witness,
            ordinal: witness_ordinal,
            file_name: witness_file_name,
            format_id: NEURON_WITNESS_SUCCESSOR_FORMAT_V1.to_owned(),
            seed_anchor: Some(frontier),
            frontier_anchor: Some(frontier),
            header_digest: witness_header_digest,
            byte_length: witness_header_bytes,
        });
        value.current_journal_ordinal = journal_ordinal;
        value.current_witness_ordinal = witness_ordinal;
        value.reseal()?;
        Ok(value)
    }

    pub fn prepare_v2_migration(
        &self,
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
    ) -> Result<Self, NeuronStoreManifestError> {
        if !matches!(self.migration, NeuronStoreMigrationV1::NativeV1)
            || target_config_digest.is_zero()
            || transformer_receipt_digest.is_zero()
        {
            return Err(NeuronStoreManifestError::MigrationState);
        }
        let mut value = self.clone();
        value.migration = NeuronStoreMigrationV1::V1ToV2Prepared {
            target_config_digest,
            transformer_receipt_digest,
        };
        value.reseal()?;
        Ok(value)
    }

    pub fn commit_v2_migration(
        &self,
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
        migrated_checkpoint_digest: Digest32,
        commit_receipt_digest: Digest32,
    ) -> Result<Self, NeuronStoreManifestError> {
        if self.migration
            != (NeuronStoreMigrationV1::V1ToV2Prepared {
                target_config_digest,
                transformer_receipt_digest,
            })
            || migrated_checkpoint_digest.is_zero()
            || commit_receipt_digest.is_zero()
        {
            return Err(NeuronStoreManifestError::MigrationState);
        }
        let mut value = self.clone();
        value.migration = NeuronStoreMigrationV1::V1ToV2Committed {
            target_config_digest,
            transformer_receipt_digest,
            migrated_checkpoint_digest,
            commit_receipt_digest,
        };
        value.reseal()?;
        Ok(value)
    }

    pub fn abort_v2_migration(
        &self,
        target_config_digest: Digest32,
        transformer_receipt_digest: Digest32,
        abort_receipt_digest: Digest32,
    ) -> Result<Self, NeuronStoreManifestError> {
        if self.migration
            != (NeuronStoreMigrationV1::V1ToV2Prepared {
                target_config_digest,
                transformer_receipt_digest,
            })
            || abort_receipt_digest.is_zero()
        {
            return Err(NeuronStoreManifestError::MigrationState);
        }
        let mut value = self.clone();
        value.migration = NeuronStoreMigrationV1::V1ToV2Aborted {
            target_config_digest,
            transformer_receipt_digest,
            abort_receipt_digest,
        };
        value.reseal()?;
        Ok(value)
    }

    pub fn bounded_replay_plan(
        &self,
        maximum_segments_per_kind: usize,
        maximum_total_bytes: u64,
    ) -> Result<NeuronStoreReplayPlanV1, NeuronStoreManifestError> {
        self.validate()?;
        if maximum_segments_per_kind == 0 || maximum_total_bytes == 0 {
            return Err(NeuronStoreManifestError::ReplayBound);
        }
        let journals = self.segments_of_kind(NeuronStoreSegmentKindV1::Journal);
        let witnesses = self.segments_of_kind(NeuronStoreSegmentKindV1::Witness);
        if journals.len() > maximum_segments_per_kind
            || witnesses.len() > maximum_segments_per_kind
        {
            return Err(NeuronStoreManifestError::ReplayBound);
        }
        let total_bytes = self.segments.iter().try_fold(0_u64, |total, segment| {
            total
                .checked_add(segment.byte_length)
                .ok_or(NeuronStoreManifestError::ReplayBound)
        })?;
        if total_bytes > maximum_total_bytes {
            return Err(NeuronStoreManifestError::ReplayBound);
        }
        Ok(NeuronStoreReplayPlanV1 {
            journal_files: journals
                .into_iter()
                .map(|segment| segment.file_name.clone())
                .collect(),
            witness_files: witnesses
                .into_iter()
                .map(|segment| segment.file_name.clone())
                .collect(),
            operation_file: self.operation_file_name.clone(),
            total_bytes,
            manifest_digest: self.manifest_digest,
        })
    }

    /// Backup restore admission is fail-closed against deletion/key/config
    /// rollback. The caller still authenticates the receipts and decrypts bytes;
    /// this manifest never mints trust or encryption authority.
    pub fn verify_restore_frontier(
        &self,
        minimum_deletion_epoch: u64,
        minimum_key_epoch: u64,
        runtime_config_digest: Digest32,
    ) -> Result<(), NeuronStoreManifestError> {
        self.validate()?;
        if self.deletion_epoch < minimum_deletion_epoch
            || self.key_epoch < minimum_key_epoch
            || self.runtime_config_digest != runtime_config_digest
        {
            return Err(NeuronStoreManifestError::Conflict);
        }
        Ok(())
    }

    pub fn validate(&self) -> Result<(), NeuronStoreManifestError> {
        if self.scope.scope_digest.is_zero()
            || self.scope.objective_digest.is_zero()
            || self.runtime_config_digest.is_zero()
            || self.key_epoch == 0
            || self.deletion_epoch == 0
            || self.key_receipt_digest.is_some_and(Digest32::is_zero)
            || self.deletion_receipt_digest.is_some_and(Digest32::is_zero)
            || self.predecessor_manifest_digest.is_some_and(Digest32::is_zero)
            || (self.key_epoch > 1 && self.key_receipt_digest.is_none())
            || (self.deletion_epoch > 1 && self.deletion_receipt_digest.is_none())
            || self.segments.is_empty()
        {
            return Err(NeuronStoreManifestError::Invalid("manifest fields"));
        }
        validate_migration(&self.migration)?;
        validate_file_name(&self.operation_file_name)?;

        let mut names = BTreeSet::new();
        for segment in &self.segments {
            validate_segment(segment)?;
            if !names.insert(segment.file_name.as_str()) {
                return Err(NeuronStoreManifestError::Invalid("duplicate segment file"));
            }
        }
        let journals = self.segments_of_kind(NeuronStoreSegmentKindV1::Journal);
        let witnesses = self.segments_of_kind(NeuronStoreSegmentKindV1::Witness);
        let operations = self.segments_of_kind(NeuronStoreSegmentKindV1::Operation);
        validate_chain(&journals, NEURON_JOURNAL_ROOT_FORMAT_V1, NEURON_JOURNAL_SUCCESSOR_FORMAT_V1)?;
        validate_chain(
            &witnesses,
            NEURON_WITNESS_ROOT_FORMAT_V1,
            NEURON_WITNESS_SUCCESSOR_FORMAT_V1,
        )?;
        if operations.len() != 1
            || operations[0].ordinal != 0
            || operations[0].format_id != NEURON_OPERATION_FORMAT_V1
            || operations[0].seed_anchor.is_some()
            || operations[0].frontier_anchor.is_some()
            || operations[0].file_name != self.operation_file_name
        {
            return Err(NeuronStoreManifestError::Invalid("operation segment"));
        }
        let journal_last = journals
            .last()
            .ok_or(NeuronStoreManifestError::Invalid("journal chain"))?;
        let witness_last = witnesses
            .last()
            .ok_or(NeuronStoreManifestError::Invalid("witness chain"))?;
        if journal_last.ordinal != self.current_journal_ordinal
            || witness_last.ordinal != self.current_witness_ordinal
            || journal_last.frontier_anchor != witness_last.frontier_anchor
        {
            return Err(NeuronStoreManifestError::Invalid("coherent frontier"));
        }
        let expected = Digest32::of_bytes(&canonical_manifest_bytes(self)?);
        if self.manifest_digest.is_zero() || self.manifest_digest != expected {
            return Err(NeuronStoreManifestError::DigestMismatch);
        }
        Ok(())
    }

    fn coherent_frontier(&self) -> Result<Option<JournalAnchor>, NeuronStoreManifestError> {
        let journal = self.current_segment(NeuronStoreSegmentKindV1::Journal)?;
        let witness = self.current_segment(NeuronStoreSegmentKindV1::Witness)?;
        if journal.frontier_anchor != witness.frontier_anchor {
            return Err(NeuronStoreManifestError::Conflict);
        }
        Ok(journal.frontier_anchor)
    }

    fn current_segment(
        &self,
        kind: NeuronStoreSegmentKindV1,
    ) -> Result<&NeuronStoreSegmentV1, NeuronStoreManifestError> {
        let ordinal = match kind {
            NeuronStoreSegmentKindV1::Journal => self.current_journal_ordinal,
            NeuronStoreSegmentKindV1::Witness => self.current_witness_ordinal,
            NeuronStoreSegmentKindV1::Operation => 0,
        };
        self.segments
            .iter()
            .find(|segment| segment.kind == kind && segment.ordinal == ordinal)
            .ok_or(NeuronStoreManifestError::Invalid("current segment"))
    }

    fn current_segment_mut(
        &mut self,
        kind: NeuronStoreSegmentKindV1,
    ) -> Result<&mut NeuronStoreSegmentV1, NeuronStoreManifestError> {
        let ordinal = match kind {
            NeuronStoreSegmentKindV1::Journal => self.current_journal_ordinal,
            NeuronStoreSegmentKindV1::Witness => self.current_witness_ordinal,
            NeuronStoreSegmentKindV1::Operation => 0,
        };
        self.segments
            .iter_mut()
            .find(|segment| segment.kind == kind && segment.ordinal == ordinal)
            .ok_or(NeuronStoreManifestError::Invalid("current segment"))
    }

    fn segments_of_kind(
        &self,
        kind: NeuronStoreSegmentKindV1,
    ) -> Vec<&NeuronStoreSegmentV1> {
        let mut values = self
            .segments
            .iter()
            .filter(|segment| segment.kind == kind)
            .collect::<Vec<_>>();
        values.sort_by_key(|segment| segment.ordinal);
        values
    }

    fn reseal(&mut self) -> Result<(), NeuronStoreManifestError> {
        self.manifest_digest = Digest32::ZERO;
        validate_without_digest(self)?;
        self.manifest_digest = Digest32::of_bytes(&canonical_manifest_bytes(self)?);
        self.validate()
    }
}

pub fn write_neuron_store_manifest_v1(
    path: &Path,
    manifest: &NeuronStoreManifestV1,
) -> Result<(), NeuronStoreManifestError> {
    manifest.validate()?;
    validate_manifest_parent(path)?;
    let encoded = serde_json::to_vec_pretty(&manifest_to_dto(manifest))
        .map_err(|_| NeuronStoreManifestError::Json)?;
    let encoded_bytes =
        u64::try_from(encoded.len()).map_err(|_| NeuronStoreManifestError::Capacity)?;
    if encoded.is_empty() || encoded_bytes > MAX_MANIFEST_BYTES {
        return Err(NeuronStoreManifestError::Capacity);
    }
    let parent = path
        .parent()
        .ok_or(NeuronStoreManifestError::Invalid("manifest parent"))?;
    let final_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(NeuronStoreManifestError::Invalid("manifest file name"))?;
    validate_file_name(final_name)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temporary = parent.join(format!(
        ".{final_name}.{}.{sequence}.tmp",
        std::process::id()
    ));
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        drop(file);
        replace_same_directory(&temporary, path)?;
        sync_directory(parent)?;
        validate_manifest_parent(path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

pub fn read_neuron_store_manifest_v1(
    path: &Path,
) -> Result<NeuronStoreManifestV1, NeuronStoreManifestError> {
    validate_manifest_parent(path)?;
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_MANIFEST_BYTES
    {
        return Err(NeuronStoreManifestError::Invalid("manifest file"));
    }
    let bytes = std::fs::read(path)?;
    let dto: ManifestDto =
        serde_json::from_slice(&bytes).map_err(|_| NeuronStoreManifestError::Json)?;
    let manifest = manifest_from_dto(dto)?;
    manifest.validate()?;
    Ok(manifest)
}

fn validate_without_digest(
    manifest: &NeuronStoreManifestV1,
) -> Result<(), NeuronStoreManifestError> {
    let digest = manifest.manifest_digest;
    let mut candidate = manifest.clone();
    candidate.manifest_digest = Digest32::of_bytes(b"temporary-manifest-validation");
    if candidate.manifest_digest == digest {
        candidate.manifest_digest = Digest32::of_bytes(b"alternate-temporary-validation");
    }
    candidate.validate().or_else(|error| match error {
        NeuronStoreManifestError::DigestMismatch => Ok(()),
        other => Err(other),
    })
}

fn validate_chain(
    segments: &[&NeuronStoreSegmentV1],
    root_format: &str,
    successor_format: &str,
) -> Result<(), NeuronStoreManifestError> {
    if segments.is_empty() || segments.len() > MAX_SEGMENTS_PER_KIND {
        return Err(NeuronStoreManifestError::Invalid("segment chain"));
    }
    let mut previous_frontier = None;
    for (index, segment) in segments.iter().enumerate() {
        let expected_ordinal =
            u32::try_from(index).map_err(|_| NeuronStoreManifestError::Capacity)?;
        if segment.ordinal != expected_ordinal {
            return Err(NeuronStoreManifestError::Invalid("segment ordinal"));
        }
        if index == 0 {
            if segment.format_id != root_format || segment.seed_anchor.is_some() {
                return Err(NeuronStoreManifestError::Invalid("root segment"));
            }
        } else if segment.format_id != successor_format
            || segment.seed_anchor.is_none()
            || segment.seed_anchor != previous_frontier
        {
            return Err(NeuronStoreManifestError::Invalid("successor segment"));
        }
        if let (Some(seed), Some(frontier)) = (segment.seed_anchor, segment.frontier_anchor)
            && frontier.sequence < seed.sequence
        {
            return Err(NeuronStoreManifestError::Invalid("segment frontier"));
        }
        previous_frontier = segment.frontier_anchor;
    }
    Ok(())
}

fn validate_segment(segment: &NeuronStoreSegmentV1) -> Result<(), NeuronStoreManifestError> {
    validate_file_name(&segment.file_name)?;
    if segment.format_id.is_empty()
        || segment.format_id.len() > MAX_FORMAT_ID_BYTES
        || !segment
            .format_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'.' || byte == b'-')
        || segment.header_digest.is_zero()
        || segment.byte_length == 0
        || segment
            .seed_anchor
            .is_some_and(|anchor| anchor.sequence == 0 || anchor.checkpoint_digest.is_zero())
        || segment
            .frontier_anchor
            .is_some_and(|anchor| anchor.sequence == 0 || anchor.checkpoint_digest.is_zero())
    {
        return Err(NeuronStoreManifestError::Invalid("segment fields"));
    }
    Ok(())
}

fn validate_migration(value: &NeuronStoreMigrationV1) -> Result<(), NeuronStoreManifestError> {
    let valid = match value {
        NeuronStoreMigrationV1::NativeV1 => true,
        NeuronStoreMigrationV1::V1ToV2Prepared {
            target_config_digest,
            transformer_receipt_digest,
        } => !target_config_digest.is_zero() && !transformer_receipt_digest.is_zero(),
        NeuronStoreMigrationV1::V1ToV2Committed {
            target_config_digest,
            transformer_receipt_digest,
            migrated_checkpoint_digest,
            commit_receipt_digest,
        } => {
            !target_config_digest.is_zero()
                && !transformer_receipt_digest.is_zero()
                && !migrated_checkpoint_digest.is_zero()
                && !commit_receipt_digest.is_zero()
        }
        NeuronStoreMigrationV1::V1ToV2Aborted {
            target_config_digest,
            transformer_receipt_digest,
            abort_receipt_digest,
        } => {
            !target_config_digest.is_zero()
                && !transformer_receipt_digest.is_zero()
                && !abort_receipt_digest.is_zero()
        }
    };
    if valid {
        Ok(())
    } else {
        Err(NeuronStoreManifestError::Invalid("migration"))
    }
}

fn validate_file_name(value: &str) -> Result<(), NeuronStoreManifestError> {
    if value.is_empty()
        || value.len() > MAX_FILE_NAME_BYTES
        || value == "."
        || value == ".."
        || value.contains("..")
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
    {
        return Err(NeuronStoreManifestError::Invalid("file name"));
    }
    Ok(())
}

fn canonical_manifest_bytes(
    manifest: &NeuronStoreManifestV1,
) -> Result<Vec<u8>, NeuronStoreManifestError> {
    let mut bytes = MANIFEST_DOMAIN.to_vec();
    bytes.extend_from_slice(&NEURON_STORE_MANIFEST_SCHEMA_V1.to_be_bytes());
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    bytes.extend_from_slice(manifest.scope.scope_digest.as_array());
    bytes.extend_from_slice(manifest.scope.objective_digest.as_array());
    bytes.extend_from_slice(manifest.runtime_config_digest.as_array());
    bytes.extend_from_slice(&manifest.key_epoch.to_be_bytes());
    push_optional_digest(&mut bytes, manifest.key_receipt_digest);
    bytes.extend_from_slice(&manifest.deletion_epoch.to_be_bytes());
    push_optional_digest(&mut bytes, manifest.deletion_receipt_digest);
    push_optional_digest(&mut bytes, manifest.predecessor_manifest_digest);
    bytes.extend_from_slice(&manifest.current_journal_ordinal.to_be_bytes());
    bytes.extend_from_slice(&manifest.current_witness_ordinal.to_be_bytes());
    push_string(&mut bytes, &manifest.operation_file_name)?;
    push_migration(&mut bytes, &manifest.migration);
    let mut segments = manifest.segments.iter().collect::<Vec<_>>();
    segments.sort_by_key(|segment| (segment_kind_code(segment.kind), segment.ordinal));
    bytes.extend_from_slice(
        &u32::try_from(segments.len())
            .map_err(|_| NeuronStoreManifestError::Capacity)?
            .to_be_bytes(),
    );
    for segment in segments {
        bytes.push(segment_kind_code(segment.kind));
        bytes.extend_from_slice(&segment.ordinal.to_be_bytes());
        push_string(&mut bytes, &segment.file_name)?;
        push_string(&mut bytes, &segment.format_id)?;
        push_optional_anchor(&mut bytes, segment.seed_anchor);
        push_optional_anchor(&mut bytes, segment.frontier_anchor);
        bytes.extend_from_slice(segment.header_digest.as_array());
        bytes.extend_from_slice(&segment.byte_length.to_be_bytes());
    }
    Ok(bytes)
}

fn push_migration(bytes: &mut Vec<u8>, migration: &NeuronStoreMigrationV1) {
    match migration {
        NeuronStoreMigrationV1::NativeV1 => bytes.push(0),
        NeuronStoreMigrationV1::V1ToV2Prepared {
            target_config_digest,
            transformer_receipt_digest,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(target_config_digest.as_array());
            bytes.extend_from_slice(transformer_receipt_digest.as_array());
        }
        NeuronStoreMigrationV1::V1ToV2Committed {
            target_config_digest,
            transformer_receipt_digest,
            migrated_checkpoint_digest,
            commit_receipt_digest,
        } => {
            bytes.push(2);
            bytes.extend_from_slice(target_config_digest.as_array());
            bytes.extend_from_slice(transformer_receipt_digest.as_array());
            bytes.extend_from_slice(migrated_checkpoint_digest.as_array());
            bytes.extend_from_slice(commit_receipt_digest.as_array());
        }
        NeuronStoreMigrationV1::V1ToV2Aborted {
            target_config_digest,
            transformer_receipt_digest,
            abort_receipt_digest,
        } => {
            bytes.push(3);
            bytes.extend_from_slice(target_config_digest.as_array());
            bytes.extend_from_slice(transformer_receipt_digest.as_array());
            bytes.extend_from_slice(abort_receipt_digest.as_array());
        }
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_optional_anchor(bytes: &mut Vec<u8>, anchor: Option<JournalAnchor>) {
    match anchor {
        Some(anchor) => {
            bytes.push(1);
            bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
            bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_string(bytes: &mut Vec<u8>, value: &str) -> Result<(), NeuronStoreManifestError> {
    let length = u32::try_from(value.len()).map_err(|_| NeuronStoreManifestError::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

const fn segment_kind_code(kind: NeuronStoreSegmentKindV1) -> u8 {
    match kind {
        NeuronStoreSegmentKindV1::Journal => 0,
        NeuronStoreSegmentKindV1::Witness => 1,
        NeuronStoreSegmentKindV1::Operation => 2,
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AnchorDto {
    sequence: u64,
    checkpoint_digest: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentDto {
    kind: String,
    ordinal: u32,
    file_name: String,
    format_id: String,
    seed_anchor: Option<AnchorDto>,
    frontier_anchor: Option<AnchorDto>,
    header_digest: String,
    byte_length: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct MigrationDto {
    state: String,
    target_config_digest: Option<String>,
    transformer_receipt_digest: Option<String>,
    migrated_checkpoint_digest: Option<String>,
    terminal_receipt_digest: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ManifestDto {
    schema_version: u32,
    generation: u64,
    scope_digest: String,
    objective_digest: String,
    runtime_config_digest: String,
    key_epoch: u64,
    key_receipt_digest: Option<String>,
    deletion_epoch: u64,
    deletion_receipt_digest: Option<String>,
    predecessor_manifest_digest: Option<String>,
    segments: Vec<SegmentDto>,
    current_journal_ordinal: u32,
    current_witness_ordinal: u32,
    operation_file_name: String,
    migration: MigrationDto,
    manifest_digest: String,
}

fn manifest_to_dto(value: &NeuronStoreManifestV1) -> ManifestDto {
    ManifestDto {
        schema_version: NEURON_STORE_MANIFEST_SCHEMA_V1,
        generation: value.generation.get(),
        scope_digest: value.scope.scope_digest.to_string(),
        objective_digest: value.scope.objective_digest.to_string(),
        runtime_config_digest: value.runtime_config_digest.to_string(),
        key_epoch: value.key_epoch,
        key_receipt_digest: value.key_receipt_digest.map(|digest| digest.to_string()),
        deletion_epoch: value.deletion_epoch,
        deletion_receipt_digest: value
            .deletion_receipt_digest
            .map(|digest| digest.to_string()),
        predecessor_manifest_digest: value
            .predecessor_manifest_digest
            .map(|digest| digest.to_string()),
        segments: value.segments.iter().map(segment_to_dto).collect(),
        current_journal_ordinal: value.current_journal_ordinal,
        current_witness_ordinal: value.current_witness_ordinal,
        operation_file_name: value.operation_file_name.clone(),
        migration: migration_to_dto(&value.migration),
        manifest_digest: value.manifest_digest.to_string(),
    }
}

fn manifest_from_dto(value: ManifestDto) -> Result<NeuronStoreManifestV1, NeuronStoreManifestError> {
    if value.schema_version != NEURON_STORE_MANIFEST_SCHEMA_V1 {
        return Err(NeuronStoreManifestError::Invalid("manifest schema"));
    }
    Ok(NeuronStoreManifestV1 {
        generation: Generation::new(value.generation)
            .map_err(|_| NeuronStoreManifestError::Invalid("generation"))?,
        scope: JournalScope {
            scope_digest: parse_digest(&value.scope_digest)?,
            objective_digest: parse_digest(&value.objective_digest)?,
        },
        runtime_config_digest: parse_digest(&value.runtime_config_digest)?,
        key_epoch: value.key_epoch,
        key_receipt_digest: parse_optional_digest(value.key_receipt_digest)?,
        deletion_epoch: value.deletion_epoch,
        deletion_receipt_digest: parse_optional_digest(value.deletion_receipt_digest)?,
        predecessor_manifest_digest: parse_optional_digest(value.predecessor_manifest_digest)?,
        segments: value
            .segments
            .into_iter()
            .map(segment_from_dto)
            .collect::<Result<Vec<_>, _>>()?,
        current_journal_ordinal: value.current_journal_ordinal,
        current_witness_ordinal: value.current_witness_ordinal,
        operation_file_name: value.operation_file_name,
        migration: migration_from_dto(value.migration)?,
        manifest_digest: parse_digest(&value.manifest_digest)?,
    })
}

fn segment_to_dto(value: &NeuronStoreSegmentV1) -> SegmentDto {
    SegmentDto {
        kind: match value.kind {
            NeuronStoreSegmentKindV1::Journal => "journal",
            NeuronStoreSegmentKindV1::Witness => "witness",
            NeuronStoreSegmentKindV1::Operation => "operation",
        }
        .to_owned(),
        ordinal: value.ordinal,
        file_name: value.file_name.clone(),
        format_id: value.format_id.clone(),
        seed_anchor: value.seed_anchor.map(anchor_to_dto),
        frontier_anchor: value.frontier_anchor.map(anchor_to_dto),
        header_digest: value.header_digest.to_string(),
        byte_length: value.byte_length,
    }
}

fn segment_from_dto(value: SegmentDto) -> Result<NeuronStoreSegmentV1, NeuronStoreManifestError> {
    let kind = match value.kind.as_str() {
        "journal" => NeuronStoreSegmentKindV1::Journal,
        "witness" => NeuronStoreSegmentKindV1::Witness,
        "operation" => NeuronStoreSegmentKindV1::Operation,
        _ => return Err(NeuronStoreManifestError::Invalid("segment kind")),
    };
    Ok(NeuronStoreSegmentV1 {
        kind,
        ordinal: value.ordinal,
        file_name: value.file_name,
        format_id: value.format_id,
        seed_anchor: value.seed_anchor.map(anchor_from_dto).transpose()?,
        frontier_anchor: value.frontier_anchor.map(anchor_from_dto).transpose()?,
        header_digest: parse_digest(&value.header_digest)?,
        byte_length: value.byte_length,
    })
}

fn migration_to_dto(value: &NeuronStoreMigrationV1) -> MigrationDto {
    match value {
        NeuronStoreMigrationV1::NativeV1 => MigrationDto {
            state: "native_v1".to_owned(),
            target_config_digest: None,
            transformer_receipt_digest: None,
            migrated_checkpoint_digest: None,
            terminal_receipt_digest: None,
        },
        NeuronStoreMigrationV1::V1ToV2Prepared {
            target_config_digest,
            transformer_receipt_digest,
        } => MigrationDto {
            state: "v1_to_v2_prepared".to_owned(),
            target_config_digest: Some(target_config_digest.to_string()),
            transformer_receipt_digest: Some(transformer_receipt_digest.to_string()),
            migrated_checkpoint_digest: None,
            terminal_receipt_digest: None,
        },
        NeuronStoreMigrationV1::V1ToV2Committed {
            target_config_digest,
            transformer_receipt_digest,
            migrated_checkpoint_digest,
            commit_receipt_digest,
        } => MigrationDto {
            state: "v1_to_v2_committed".to_owned(),
            target_config_digest: Some(target_config_digest.to_string()),
            transformer_receipt_digest: Some(transformer_receipt_digest.to_string()),
            migrated_checkpoint_digest: Some(migrated_checkpoint_digest.to_string()),
            terminal_receipt_digest: Some(commit_receipt_digest.to_string()),
        },
        NeuronStoreMigrationV1::V1ToV2Aborted {
            target_config_digest,
            transformer_receipt_digest,
            abort_receipt_digest,
        } => MigrationDto {
            state: "v1_to_v2_aborted".to_owned(),
            target_config_digest: Some(target_config_digest.to_string()),
            transformer_receipt_digest: Some(transformer_receipt_digest.to_string()),
            migrated_checkpoint_digest: None,
            terminal_receipt_digest: Some(abort_receipt_digest.to_string()),
        },
    }
}

fn migration_from_dto(value: MigrationDto) -> Result<NeuronStoreMigrationV1, NeuronStoreManifestError> {
    match value.state.as_str() {
        "native_v1"
            if value.target_config_digest.is_none()
                && value.transformer_receipt_digest.is_none()
                && value.migrated_checkpoint_digest.is_none()
                && value.terminal_receipt_digest.is_none() =>
        {
            Ok(NeuronStoreMigrationV1::NativeV1)
        }
        "v1_to_v2_prepared"
            if value.migrated_checkpoint_digest.is_none()
                && value.terminal_receipt_digest.is_none() =>
        {
            Ok(NeuronStoreMigrationV1::V1ToV2Prepared {
                target_config_digest: parse_required_digest(value.target_config_digest)?,
                transformer_receipt_digest: parse_required_digest(
                    value.transformer_receipt_digest,
                )?,
            })
        }
        "v1_to_v2_committed" => Ok(NeuronStoreMigrationV1::V1ToV2Committed {
            target_config_digest: parse_required_digest(value.target_config_digest)?,
            transformer_receipt_digest: parse_required_digest(
                value.transformer_receipt_digest,
            )?,
            migrated_checkpoint_digest: parse_required_digest(value.migrated_checkpoint_digest)?,
            commit_receipt_digest: parse_required_digest(value.terminal_receipt_digest)?,
        }),
        "v1_to_v2_aborted" if value.migrated_checkpoint_digest.is_none() => {
            Ok(NeuronStoreMigrationV1::V1ToV2Aborted {
                target_config_digest: parse_required_digest(value.target_config_digest)?,
                transformer_receipt_digest: parse_required_digest(
                    value.transformer_receipt_digest,
                )?,
                abort_receipt_digest: parse_required_digest(value.terminal_receipt_digest)?,
            })
        }
        _ => Err(NeuronStoreManifestError::Invalid("migration state")),
    }
}

fn anchor_to_dto(value: JournalAnchor) -> AnchorDto {
    AnchorDto {
        sequence: value.sequence,
        checkpoint_digest: value.checkpoint_digest.to_string(),
    }
}

fn anchor_from_dto(value: AnchorDto) -> Result<JournalAnchor, NeuronStoreManifestError> {
    Ok(JournalAnchor {
        sequence: value.sequence,
        checkpoint_digest: parse_digest(&value.checkpoint_digest)?,
    })
}

fn parse_required_digest(value: Option<String>) -> Result<Digest32, NeuronStoreManifestError> {
    parse_digest(
        value
            .as_deref()
            .ok_or(NeuronStoreManifestError::Invalid("required digest"))?,
    )
}

fn parse_optional_digest(
    value: Option<String>,
) -> Result<Option<Digest32>, NeuronStoreManifestError> {
    value.as_deref().map(parse_digest).transpose()
}

fn parse_digest(value: &str) -> Result<Digest32, NeuronStoreManifestError> {
    Digest32::from_str(value).map_err(|_| NeuronStoreManifestError::Invalid("digest"))
}

fn validate_manifest_parent(path: &Path) -> Result<(), NeuronStoreManifestError> {
    let parent = path
        .parent()
        .ok_or(NeuronStoreManifestError::Invalid("manifest parent"))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(NeuronStoreManifestError::Invalid("manifest directory"));
    }
    Ok(())
}

fn replace_same_directory(temporary: &Path, destination: &Path) -> Result<(), io::Error> {
    #[cfg(unix)]
    {
        std::fs::rename(temporary, destination)
    }
    #[cfg(not(unix))]
    {
        if destination.exists() {
            std::fs::remove_file(destination)?;
        }
        std::fs::rename(temporary, destination)
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), io::Error> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), io::Error> {
    Ok(())
}

#[cfg(test)]
#[path = "store_manifest_tests.rs"]
mod tests;
