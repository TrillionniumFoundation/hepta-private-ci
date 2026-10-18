//! Explicit adoption of a pre-HPTNOP01 V1 journal.
//!
//! A historical sparse journal cannot manufacture the complete model/runtime
//! result that was never stored beside it.  Migration therefore requires a
//! bounded, independently retained archive of every complete operation from
//! sequence one through the externally acknowledged frontier.  Ordinary
//! recovery never calls this module and never initializes a missing sidecar.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AnchorWitnessStore;
use crate::FileNeuronOperationStore;
use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronModelOutputV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronRuntimeError;
use crate::NeuronRuntimeOutputV1;
use crate::OperationStoreError;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::WitnessStoreError;
use crate::canonical_model_output_digest_v1;
use crate::operation_store::PreparedNeuronOperationV1;
use crate::runtime_types::calibrate;
use crate::runtime_types::digest_model_binding;
use crate::runtime_types::validate_model_output;
use crate::sparse_tick;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronLegacyOperationRecordV1 {
    pub input_digest: Digest32,
    pub tick_id: StableId,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub sparse_tick: SparseTick,
    pub output: NeuronRuntimeOutputV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronLegacyOperationMigrationReceiptV1 {
    pub config_digest: Digest32,
    pub scope: JournalScope,
    pub imported_operations: u64,
    pub frontier: Option<JournalAnchor>,
    pub archive_digest: Digest32,
    pub receipt_digest: Digest32,
}

#[derive(Debug)]
pub enum NeuronLegacyOperationMigrationError {
    InvalidArchive,
    FrontierMismatch,
    Arithmetic,
    Journal(JournalError),
    Witness(WitnessStoreError),
    Operation(OperationStoreError),
    Runtime(NeuronRuntimeError),
}

impl fmt::Display for NeuronLegacyOperationMigrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronLegacyOperationMigrationError {}

impl From<JournalError> for NeuronLegacyOperationMigrationError {
    fn from(value: JournalError) -> Self {
        Self::Journal(value)
    }
}

impl From<WitnessStoreError> for NeuronLegacyOperationMigrationError {
    fn from(value: WitnessStoreError) -> Self {
        Self::Witness(value)
    }
}

impl From<OperationStoreError> for NeuronLegacyOperationMigrationError {
    fn from(value: OperationStoreError) -> Self {
        Self::Operation(value)
    }
}

impl From<NeuronRuntimeError> for NeuronLegacyOperationMigrationError {
    fn from(value: NeuronRuntimeError) -> Self {
        Self::Runtime(value)
    }
}

/// Canonical identity for a complete legacy operation archive. This helper
/// validates the archive's internal deterministic semantics; it does not
/// authenticate where the archive came from. Enrollment must retain the
/// returned digest in a separately authenticated manifest before migration.
pub fn canonical_legacy_operation_archive_digest_v1(
    native: &SparseConfig,
    scope: JournalScope,
    config: &NeuronRuntimeConfigV1,
    archive: &[NeuronLegacyOperationRecordV1],
) -> Result<Digest32, NeuronLegacyOperationMigrationError> {
    config.validate_native(native)?;
    let prepared = validate_archive(native, scope, config, archive)?;
    archive_digest(&prepared)
}

/// Build or resume the HPTNOP01 operation history for one acknowledged V1
/// generation.  The archive is fully validated before the operation file is
/// opened, so an invalid archive cannot create even an empty sidecar.
///
/// The operation file may be empty or may contain an exact prefix written by a
/// previous interrupted migration.  Any conflicting prefix fails closed.
///
/// `trusted_archive_digest` must come from an authenticated manifest retained
/// outside the journal, witness and archive being adopted. Computing it from
/// the candidate archive at migration time does not establish authenticity.
#[allow(clippy::too_many_arguments)]
pub fn migrate_legacy_v1_operation_history<W: AnchorWitnessStore>(
    operation_file: File,
    native: &SparseConfig,
    journal: &SparseJournal,
    witness: &W,
    scope: JournalScope,
    max_operations: usize,
    config: &NeuronRuntimeConfigV1,
    archive: &[NeuronLegacyOperationRecordV1],
    trusted_archive_digest: Digest32,
) -> Result<NeuronLegacyOperationMigrationReceiptV1, NeuronLegacyOperationMigrationError> {
    config.validate_native(native)?;
    let config_digest = config.semantic_digest()?;
    let journal_frontier = journal.current_anchor()?;
    let witness_frontier = witness.current()?;
    if journal_frontier != witness_frontier {
        return Err(NeuronLegacyOperationMigrationError::FrontierMismatch);
    }
    if journal_frontier.is_some() == archive.is_empty() {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }
    if archive.len() > max_operations {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }

    let prepared = validate_archive(native, scope, config, archive)?;
    let replay_frontier = prepared.last().map(|value| value.next_anchor);
    if replay_frontier != journal_frontier {
        return Err(NeuronLegacyOperationMigrationError::FrontierMismatch);
    }
    if let Some(frontier) = replay_frontier {
        if !journal.contains_anchor(frontier)? {
            return Err(NeuronLegacyOperationMigrationError::FrontierMismatch);
        }
        let journal_receipt = journal
            .receipt_at(frontier.sequence)?
            .ok_or(NeuronLegacyOperationMigrationError::FrontierMismatch)?;
        let replay_receipt = replay_receipt(native, archive)?
            .ok_or(NeuronLegacyOperationMigrationError::FrontierMismatch)?;
        if journal_receipt != &replay_receipt {
            return Err(NeuronLegacyOperationMigrationError::FrontierMismatch);
        }
    }

    let archive_digest = archive_digest(&prepared)?;
    if trusted_archive_digest.is_zero() || archive_digest != trusted_archive_digest {
        return Err(NeuronLegacyOperationMigrationError::InvalidArchive);
    }
    let mut store = FileNeuronOperationStore::open(
        operation_file,
        config_digest,
        scope,
        config.generation,
        config.state_width,
        max_operations,
    )?;
    for value in &prepared {
        match store.find_tick(&value.tick_id)? {
            Some(existing) if existing.operation_digest == value.operation_digest => {
                if store
                    .pending()?
                    .is_some_and(|pending| pending.operation_digest == value.operation_digest)
                {
                    store.complete(value.operation_digest)?;
                }
            }
            Some(_) => return Err(NeuronLegacyOperationMigrationError::InvalidArchive),
            None => {
                store.prepare(value.clone())?;
                store.complete(value.operation_digest)?;
            }
        }
    }
    if store.frontier()? != replay_frontier || store.pending()?.is_some() {
        return Err(NeuronLegacyOperationMigrationError::FrontierMismatch);
    }

    let imported_operations = u64::try_from(prepared.len())
        .map_err(|_| NeuronLegacyOperationMigrationError::Arithmetic)?;
    let receipt_digest = migration_receipt_digest(
        config_digest,
        scope,
        imported_operations,
        replay_frontier,
        archive_digest,
    );
    drop(store);
    Ok(NeuronLegacyOperationMigrationReceiptV1 {
        config_digest,
        scope,
        imported_operations,
        frontier: replay_frontier,
        archive_digest,
        receipt_digest,
    })
}

include!("legacy_migration_validation.rs");

#[cfg(test)]
#[path = "legacy_migration_tests.rs"]
mod tests;
