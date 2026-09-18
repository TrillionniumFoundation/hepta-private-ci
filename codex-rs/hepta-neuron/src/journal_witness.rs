//! Durable, independently retained acknowledgement witness for SparseJournal.
//!
//! The witness is intentionally stored in a separate host-authorized file. It
//! is append-only and synchronized before acknowledgement. It is not a hostile
//! storage sandbox; the host remains responsible for protecting this file from
//! rollback or replacement.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::journal_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HPTNWA01";
const HEADER: usize = 136;
const FRAME: usize = 104;
const MAX_RECORDS: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WitnessError {
    Journal(JournalError),
    InvalidLimit,
    InvalidContext,
    AcknowledgedHistoryMissing,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for WitnessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WitnessError {}

impl From<io::Error> for WitnessError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub struct AnchorWitnessStore {
    file: LockedFile,
    max_records: usize,
    anchors: Vec<JournalAnchor>,
    poisoned: bool,
}

impl AnchorWitnessStore {
    pub fn open(
        file: File,
        config: &SparseConfig,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, WitnessError> {
        if !(1..=MAX_RECORDS).contains(&max_records) {
            return Err(WitnessError::InvalidLimit);
        }
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(WitnessError::InvalidContext);
        }
        let config_digest = config
            .digest()
            .map_err(|error| WitnessError::Journal(JournalError::Mechanism(error)))?;
        let mut header = MAGIC.to_vec();
        for digest in [config_digest, scope.scope_digest, scope.objective_digest] {
            header.extend_from_slice(digest.as_array());
        }
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());

        let mut file = LockedFile::acquire(file).map_err(WitnessError::Journal)?;
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            file.write_all(&header)
                .map_err(|_| WitnessError::Indeterminate)?;
            file.sync_all().map_err(|_| WitnessError::Indeterminate)?;
        } else {
            if length < HEADER as u64 {
                return Err(WitnessError::Corrupt);
            }
            let mut actual = [0_u8; HEADER];
            file.read_exact(&mut actual)?;
            if actual.as_slice() != header {
                return Err(WitnessError::InvalidContext);
            }
        }
        let available = length.saturating_sub(HEADER as u64) as usize;
        if available > max_records * FRAME + FRAME - 1 {
            return Err(WitnessError::Capacity);
        }
        let complete = available / FRAME;
        if complete > max_records {
            return Err(WitnessError::Capacity);
        }
        let mut anchors = Vec::with_capacity(complete);
        let mut prior_digest = Digest32::ZERO;
        let mut frame = [0_u8; FRAME];
        for index in 0..complete {
            file.read_exact(&mut frame)?;
            let checksum_start = FRAME - 32;
            if Digest32::of_bytes(&frame[..checksum_start]).as_array()
                != &frame[checksum_start..]
            {
                return Err(WitnessError::Corrupt);
            }
            let sequence = u64::from_be_bytes(
                frame[..8]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let checkpoint = Digest32::from_array(
                frame[8..40]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let predecessor = Digest32::from_array(
                frame[40..72]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let expected_sequence =
                u64::try_from(index + 1).map_err(|_| WitnessError::Capacity)?;
            if sequence != expected_sequence
                || checkpoint.is_zero()
                || predecessor != prior_digest
            {
                return Err(WitnessError::Corrupt);
            }
            let anchor = JournalAnchor {
                sequence,
                checkpoint_digest: checkpoint,
            };
            prior_digest = witness_semantic_digest(&anchor);
            anchors.push(anchor);
        }
        if !available.is_multiple_of(FRAME) {
            file.set_len((HEADER + complete * FRAME) as u64)
                .map_err(|_| WitnessError::Indeterminate)?;
            file.sync_all().map_err(|_| WitnessError::Indeterminate)?;
        }
        file.sync_data().map_err(|_| WitnessError::Indeterminate)?;
        Ok(Self {
            file,
            max_records,
            anchors,
            poisoned: false,
        })
    }

    pub fn current(&self) -> Result<Option<JournalAnchor>, WitnessError> {
        if self.poisoned {
            Err(WitnessError::Poisoned)
        } else {
            Ok(self.anchors.last().copied())
        }
    }

    pub fn acknowledge(&mut self, anchor: JournalAnchor) -> Result<JournalAnchor, WitnessError> {
        if self.poisoned {
            return Err(WitnessError::Poisoned);
        }
        if anchor.sequence == 0 || anchor.checkpoint_digest.is_zero() {
            return Err(WitnessError::Conflict);
        }
        if let Some(current) = self.anchors.last().copied() {
            if anchor.sequence <= current.sequence {
                return if anchor == current {
                    Ok(current)
                } else {
                    Err(WitnessError::Conflict)
                };
            }
            if anchor.sequence != current.sequence + 1 {
                return Err(WitnessError::Conflict);
            }
        } else if anchor.sequence != 1 {
            return Err(WitnessError::Conflict);
        }
        if self.anchors.len() >= self.max_records {
            return Err(WitnessError::Capacity);
        }
        let predecessor = self
            .anchors
            .last()
            .map_or(Digest32::ZERO, witness_semantic_digest);
        let mut frame = Vec::with_capacity(FRAME);
        frame.extend_from_slice(&anchor.sequence.to_be_bytes());
        frame.extend_from_slice(anchor.checkpoint_digest.as_array());
        frame.extend_from_slice(predecessor.as_array());
        let checksum = Digest32::of_bytes(&frame);
        frame.extend_from_slice(checksum.as_array());
        if frame.len() != FRAME {
            return Err(WitnessError::Corrupt);
        }
        let expected_length = (HEADER + self.anchors.len() * FRAME) as u64;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(WitnessError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .map_err(|_| WitnessError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| WitnessError::Indeterminate)?;
        self.anchors.push(anchor);
        self.poisoned = false;
        Ok(anchor)
    }
}

pub struct ManagedSparseJournal {
    journal: SparseJournal,
    witness: AnchorWitnessStore,
    poisoned: bool,
}

impl ManagedSparseJournal {
    pub fn open(
        journal_file: File,
        witness_file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, WitnessError> {
        let journal_length = journal_file.metadata()?.len();
        let witness = AnchorWitnessStore::open(witness_file, &config, scope, max_records)?;
        let anchor = witness.current()?;
        if anchor.is_none() && journal_length > HEADER as u64 {
            return Err(WitnessError::AcknowledgedHistoryMissing);
        }
        let journal = match anchor {
            Some(value) => SparseJournal::open_anchored(
                journal_file,
                config,
                scope,
                max_records,
                value,
            ),
            None => SparseJournal::open(journal_file, config, scope, max_records),
        }
        .map_err(WitnessError::Journal)?;
        Ok(Self {
            journal,
            witness,
            poisoned: false,
        })
    }

    pub fn open_seeded(
        journal_file: File,
        witness_file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        seed: crate::SparseCheckpoint,
    ) -> Result<Self, WitnessError> {
        let journal_length = journal_file.metadata()?.len();
        let witness = AnchorWitnessStore::open(witness_file, &config, scope, max_records)?;
        let anchor = witness.current()?;
        if anchor.is_none() && journal_length > HEADER as u64 {
            return Err(WitnessError::AcknowledgedHistoryMissing);
        }
        let journal = match anchor {
            Some(value) => SparseJournal::open_seeded_anchored(
                journal_file,
                config,
                scope,
                max_records,
                seed,
                value,
            ),
            None => SparseJournal::open_seeded(
                journal_file,
                config,
                scope,
                max_records,
                seed,
            ),
        }
        .map_err(WitnessError::Journal)?;
        Ok(Self {
            journal,
            witness,
            poisoned: false,
        })
    }

    pub fn commit(
        &mut self,
        expected_predecessor: Digest32,
        tick: &SparseTick,
    ) -> Result<SparseSignalReceipt, WitnessError> {
        if self.poisoned {
            return Err(WitnessError::Poisoned);
        }
        let receipt = self
            .journal
            .commit(expected_predecessor, tick)
            .map_err(WitnessError::Journal)?;
        let anchor = JournalAnchor {
            sequence: tick.sequence,
            checkpoint_digest: receipt.checkpoint_after,
        };
        self.poisoned = true;
        self.witness.acknowledge(anchor)?;
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current(&self) -> Result<Option<&crate::SparseCheckpoint>, WitnessError> {
        if self.poisoned {
            Err(WitnessError::Poisoned)
        } else {
            self.journal.current().map_err(WitnessError::Journal)
        }
    }

    pub fn acknowledged(&self) -> Result<Option<JournalAnchor>, WitnessError> {
        if self.poisoned {
            Err(WitnessError::Poisoned)
        } else {
            self.witness.current()
        }
    }
}

fn witness_semantic_digest(anchor: &JournalAnchor) -> Digest32 {
    let mut bytes = b"hepta.neuron.witness-anchor.v1".to_vec();
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "journal_witness_tests.rs"]
mod tests;
