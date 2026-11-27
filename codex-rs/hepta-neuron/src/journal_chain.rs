//! Whole-chain recovery keeps every descriptor locked through readback and repair.

use super::HEADER;
use super::JournalAnchor;
use super::JournalError;
use super::JournalScope;
use super::LockedFile;
use super::MAGIC;
use super::RecoveryPolicy;
use super::SUCCESSOR_HEADER;
use super::SUCCESSOR_MAGIC;
use super::SparseCheckpoint;
use super::SparseConfig;
use super::SparseJournal;
use super::repair_recovered_file;
use super::root_header;
use super::successor_header;
use super::validate_exact_header;
use super::validate_limit;
use super::validate_scope;

use std::fs::File;
use std::io::Seek;
use std::io::SeekFrom;

impl SparseJournal {
    /// Recover existing segments with full predecessors and an exact final witness.
    ///
    /// Each tuple supplies a fresh read/write handle and its record capacity.
    /// All handles remain locked until every header, frame and chain boundary has
    /// passed read-only validation. Empty files are never initialized here.
    /// Fresh duplicate handles fail with Busy while the first lock is held;
    /// cloned or inherited handles remain unsupported, as for other journal APIs.
    ///
    /// A single segment retains open_anchored's minimum-witness semantics.
    /// Repair failures are Indeterminate: repairs across files are not atomic.
    pub fn recover_chain_anchored(
        segments: Vec<(File, usize)>,
        config: SparseConfig,
        scope: JournalScope,
        acknowledged: JournalAnchor,
    ) -> Result<Self, JournalError> {
        let final_index = segments
            .len()
            .checked_sub(1)
            .ok_or(JournalError::InvalidAnchor)?;
        if final_index == 0 {
            let (file, max_records) = segments
                .into_iter()
                .next()
                .ok_or(JournalError::InvalidAnchor)?;
            return Self::open_anchored(file, config, scope, max_records, acknowledged);
        }
        let mut end_capacity = 0_u64;
        let mut prefix_capacity = 0_u64;
        for (index, (_, max_records)) in segments.iter().enumerate() {
            validate_limit(*max_records)?;
            end_capacity = end_capacity
                .checked_add(*max_records as u64)
                .ok_or(JournalError::InvalidLimit)?;
            if index < final_index {
                prefix_capacity = end_capacity;
            }
        }
        if acknowledged.sequence <= prefix_capacity
            || acknowledged.sequence > end_capacity
            || acknowledged.checkpoint_digest.is_zero()
        {
            return Err(JournalError::InvalidAnchor);
        }
        let config_digest = config.digest().map_err(JournalError::Mechanism)?;
        validate_scope(scope)?;
        let locked = segments
            .into_iter()
            .map(|(file, capacity)| Ok((LockedFile::acquire(file)?, capacity)))
            .collect::<Result<Vec<_>, JournalError>>()?;
        let mut prefixes = Vec::with_capacity(final_index);
        let mut seed: Option<SparseCheckpoint> = None;
        let mut expected_end = 0_u64;
        for (index, (mut file, max_records)) in locked.into_iter().enumerate() {
            if file.metadata()?.len() == 0 {
                return Err(JournalError::AcknowledgedHistoryMissing);
            }
            file.seek(SeekFrom::Start(0))?;
            let data_offset = if let Some(checkpoint) = seed.as_ref() {
                if !checkpoint.matches_segment_context(
                    config_digest,
                    scope.scope_digest,
                    scope.objective_digest,
                ) {
                    return Err(JournalError::ContextMismatch);
                }
                let anchor = JournalAnchor {
                    sequence: checkpoint.sequence(),
                    checkpoint_digest: checkpoint.digest(),
                };
                validate_exact_header(
                    &mut file,
                    &successor_header(config_digest, scope, anchor),
                    SUCCESSOR_HEADER,
                    *SUCCESSOR_MAGIC,
                )?;
                SUCCESSOR_HEADER
            } else {
                validate_exact_header(
                    &mut file,
                    &root_header(config_digest, scope),
                    HEADER,
                    *MAGIC,
                )?;
                HEADER
            };
            let policy = if index == final_index {
                RecoveryPolicy::Require(acknowledged)
            } else {
                RecoveryPolicy::Unanchored
            };
            let (journal, repair_to) = Self::read_recovery_frames(
                file,
                config.clone(),
                scope,
                max_records,
                policy,
                seed,
                data_offset,
            )?;
            expected_end = expected_end
                .checked_add(max_records as u64)
                .ok_or(JournalError::InvalidLimit)?;
            if index == final_index {
                if journal.current_anchor()? != Some(acknowledged) {
                    return Err(JournalError::AnchorMismatch);
                }
                // No descriptor is reopened and no lock is released before repair.
                for (file, repair_to) in &prefixes {
                    repair_recovered_file(file, *repair_to)?;
                }
                repair_recovered_file(&journal.file, repair_to)?;
                return Ok(journal);
            }
            if journal.current()?.map(SparseCheckpoint::sequence) != Some(expected_end) {
                return Err(JournalError::AcknowledgedHistoryMissing);
            }
            seed = journal.current.clone();
            // Retain the lock and repair boundary, not every predecessor's history.
            prefixes.push((journal.file, repair_to));
        }
        Err(JournalError::InvalidAnchor)
    }
}
