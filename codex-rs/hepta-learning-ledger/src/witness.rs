//! Independently retained append-only acknowledgement witness for the learning ledger.
//!
//! This store is intentionally a separate file capability from the causal ledger.
//! It proves repository-level witness mechanics, not administrative independence:
//! production must place it on a separately governed durability path.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTLW01";
const HEADER: usize = 72;
const FRAME: usize = 104;
const MAX_WITNESSES: u64 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WitnessDisposition {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WitnessReceipt {
    pub disposition: WitnessDisposition,
    pub anchor: LedgerAnchor,
    pub witness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningWitnessError {
    InvalidBinding,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    Busy,
    NotRegular,
    Corrupt,
    InvalidAnchor,
    Regression,
    Gap,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for LearningWitnessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for LearningWitnessError {}

impl From<io::Error> for LearningWitnessError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// Minimum interface consumed by the production composition gate. A remote or
/// replicated product witness may implement this trait; `FileLearningWitnessStore`
/// is the concrete repository implementation and qualification fixture.
pub trait LearningWitnessStore {
    fn current_anchor(&self) -> LedgerAnchor;

    fn persist(&mut self, anchor: LedgerAnchor) -> Result<WitnessReceipt, LearningWitnessError>;
}

/// Fixed-format append-only witness journal. Each frame chains to the prior
/// witness frame so reordered or edited acknowledgements fail recovery.
pub struct FileLearningWitnessStore {
    file: LockedFile,
    binding: Digest32,
    current: LedgerAnchor,
    witness_digest: Digest32,
    durable_length: u64,
    poisoned: bool,
}

impl FileLearningWitnessStore {
    pub fn create(file: File, binding: Digest32) -> Result<Self, LearningWitnessError> {
        validate_binding(binding)?;
        let mut file = acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(LearningWitnessError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| LearningWitnessError::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            current: empty_anchor(),
            witness_digest: checksum,
            durable_length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(file: File, binding: Digest32) -> Result<Self, LearningWitnessError> {
        validate_binding(binding)?;
        let mut file = acquire(file)?;
        let length = file.metadata()?.len();
        if length < HEADER as u64 {
            return Err(LearningWitnessError::MissingHeader);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER];
        file.read_exact(&mut header)?;
        if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..] {
            return Err(LearningWitnessError::Corrupt);
        }
        if &header[8..40] != binding.as_array() {
            return Err(LearningWitnessError::BindingMismatch);
        }

        let mut cursor = HEADER as u64;
        let mut current = empty_anchor();
        let mut witness_digest = Digest32::from_array(
            header[40..72]
                .try_into()
                .map_err(|_| LearningWitnessError::Corrupt)?,
        );

        while length - cursor >= FRAME as u64 {
            let mut frame = [0_u8; FRAME];
            file.read_exact(&mut frame)?;
            let sequence = u64::from_be_bytes(
                frame[..8]
                    .try_into()
                    .map_err(|_| LearningWitnessError::Corrupt)?,
            );
            let chain_digest = Digest32::from_array(
                frame[8..40]
                    .try_into()
                    .map_err(|_| LearningWitnessError::Corrupt)?,
            );
            let predecessor_witness = Digest32::from_array(
                frame[40..72]
                    .try_into()
                    .map_err(|_| LearningWitnessError::Corrupt)?,
            );
            let stored_witness = Digest32::from_array(
                frame[72..104]
                    .try_into()
                    .map_err(|_| LearningWitnessError::Corrupt)?,
            );
            if sequence == 0
                || chain_digest.is_zero()
                || sequence != current.sequence + 1
                || predecessor_witness != witness_digest
                || Digest32::of_bytes(&frame[..72]) != stored_witness
            {
                return Err(LearningWitnessError::Corrupt);
            }
            current = LedgerAnchor {
                sequence,
                chain_digest,
            };
            witness_digest = stored_witness;
            cursor += FRAME as u64;
            if current.sequence > MAX_WITNESSES {
                return Err(LearningWitnessError::Capacity);
            }
        }

        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| LearningWitnessError::Indeterminate)?;
        }
        file.sync_all()
            .map_err(|_| LearningWitnessError::Indeterminate)?;
        file.seek(SeekFrom::Start(cursor))?;

        Ok(Self {
            file,
            binding,
            current,
            witness_digest,
            durable_length: cursor,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    #[must_use]
    pub fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }
}

impl LearningWitnessStore for FileLearningWitnessStore {
    fn current_anchor(&self) -> LedgerAnchor {
        self.current
    }

    fn persist(&mut self, anchor: LedgerAnchor) -> Result<WitnessReceipt, LearningWitnessError> {
        if self.poisoned {
            return Err(LearningWitnessError::Poisoned);
        }
        validate_anchor(anchor)?;
        if anchor == self.current {
            return Ok(WitnessReceipt {
                disposition: WitnessDisposition::IdempotentReplay,
                anchor,
                witness_digest: self.witness_digest,
            });
        }
        if anchor.sequence <= self.current.sequence {
            return Err(LearningWitnessError::Regression);
        }
        if anchor.sequence != self.current.sequence + 1 {
            return Err(LearningWitnessError::Gap);
        }
        if anchor.sequence > MAX_WITNESSES {
            return Err(LearningWitnessError::Capacity);
        }

        let mut frame = Vec::with_capacity(FRAME);
        frame.extend_from_slice(&anchor.sequence.to_be_bytes());
        frame.extend_from_slice(anchor.chain_digest.as_array());
        frame.extend_from_slice(self.witness_digest.as_array());
        let next_witness = Digest32::of_bytes(&frame);
        frame.extend_from_slice(next_witness.as_array());
        debug_assert_eq!(frame.len(), FRAME);

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(LearningWitnessError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| LearningWitnessError::Indeterminate)?;
        self.durable_length += FRAME as u64;
        self.current = anchor;
        self.witness_digest = next_witness;
        self.poisoned = false;

        Ok(WitnessReceipt {
            disposition: WitnessDisposition::Appended,
            anchor,
            witness_digest: next_witness,
        })
    }
}

fn validate_binding(binding: Digest32) -> Result<(), LearningWitnessError> {
    if binding.is_zero() {
        Err(LearningWitnessError::InvalidBinding)
    } else {
        Ok(())
    }
}

fn validate_anchor(anchor: LedgerAnchor) -> Result<(), LearningWitnessError> {
    if anchor.sequence == 0 || anchor.chain_digest.is_zero() {
        Err(LearningWitnessError::InvalidAnchor)
    } else {
        Ok(())
    }
}

const fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn acquire(file: File) -> Result<LockedFile, LearningWitnessError> {
    LockedFile::acquire(file).map_err(|error| match error {
        DurableLedgerError::Busy => LearningWitnessError::Busy,
        DurableLedgerError::NotRegular => LearningWitnessError::NotRegular,
        DurableLedgerError::Io(kind) => LearningWitnessError::Io(kind),
        _ => LearningWitnessError::Corrupt,
    })
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
