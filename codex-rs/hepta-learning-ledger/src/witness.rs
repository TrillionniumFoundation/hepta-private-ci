//! Independently retained durable acknowledgement witness.
//!
//! The witness is deliberately a separate host-authorized file and binding from
//! the learning journal. It stores only acknowledged anchors. It grants no
//! authority and cannot reconstruct missing ledger history.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::LedgerAnchor;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTAW01";
const HEADER: usize = 72;
const RECORD: usize = 72;
const MAX_WITNESSES: usize = 1_000_000;

pub struct DurableAnchorWitness {
    file: LockedFile,
    current: Option<LedgerAnchor>,
    count: usize,
    length: u64,
    poisoned: bool,
}

impl DurableAnchorWitness {
    pub fn create(file: File, binding: Digest32) -> Result<Self, AnchorWitnessError> {
        if binding.is_zero() {
            return Err(AnchorWitnessError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_durable)?;
        if file.metadata()?.len() != 0 {
            return Err(AnchorWitnessError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| AnchorWitnessError::Indeterminate)?;
        Ok(Self {
            file,
            current: None,
            count: 0,
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(file: File, binding: Digest32) -> Result<Self, AnchorWitnessError> {
        if binding.is_zero() {
            return Err(AnchorWitnessError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_durable)?;
        let length = file.metadata()?.len();
        if length < HEADER as u64 || (length - HEADER as u64) % RECORD as u64 != 0 {
            return Err(AnchorWitnessError::Corrupt);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER];
        file.read_exact(&mut header)?;
        if &header[..8] != MAGIC
            || &header[8..40] != binding.as_array()
            || Digest32::of_bytes(&header[..40]).as_array() != &header[40..72]
        {
            return Err(AnchorWitnessError::Corrupt);
        }

        let count = usize::try_from((length - HEADER as u64) / RECORD as u64)
            .map_err(|_| AnchorWitnessError::Capacity)?;
        if count > MAX_WITNESSES {
            return Err(AnchorWitnessError::Capacity);
        }

        let mut current = None;
        for index in 0..count {
            let mut row = [0_u8; RECORD];
            file.read_exact(&mut row)?;
            if Digest32::of_bytes(&row[..40]).as_array() != &row[40..72] {
                return Err(AnchorWitnessError::Corrupt);
            }
            let sequence = u64::from_be_bytes(
                row[..8]
                    .try_into()
                    .map_err(|_| AnchorWitnessError::Corrupt)?,
            );
            let chain_digest = Digest32::from_array(
                row[8..40]
                    .try_into()
                    .map_err(|_| AnchorWitnessError::Corrupt)?,
            );
            if sequence == 0 || chain_digest.is_zero() {
                return Err(AnchorWitnessError::Corrupt);
            }
            if let Some(previous) = current {
                if sequence <= previous.sequence {
                    return Err(AnchorWitnessError::Corrupt);
                }
            }
            current = Some(LedgerAnchor {
                sequence,
                chain_digest,
            });
            let expected_offset = HEADER as u64 + ((index + 1) * RECORD) as u64;
            if file.stream_position()? != expected_offset {
                return Err(AnchorWitnessError::Corrupt);
            }
        }
        file.seek(SeekFrom::End(0))?;
        Ok(Self {
            file,
            current,
            count,
            length,
            poisoned: false,
        })
    }

    pub fn publish(&mut self, anchor: LedgerAnchor) -> Result<(), AnchorWitnessError> {
        if self.poisoned {
            return Err(AnchorWitnessError::Poisoned);
        }
        if anchor.sequence == 0 || anchor.chain_digest.is_zero() {
            return Err(AnchorWitnessError::InvalidAnchor);
        }
        if let Some(current) = self.current {
            if anchor == current {
                return Ok(());
            }
            if anchor.sequence <= current.sequence {
                return Err(AnchorWitnessError::Regression);
            }
        }
        if self.count >= MAX_WITNESSES {
            return Err(AnchorWitnessError::Capacity);
        }

        let mut row = Vec::with_capacity(RECORD);
        row.extend_from_slice(&anchor.sequence.to_be_bytes());
        row.extend_from_slice(anchor.chain_digest.as_array());
        row.extend_from_slice(Digest32::of_bytes(&row).as_array());
        if row.len() != RECORD {
            return Err(AnchorWitnessError::Corrupt);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.length {
            return Err(AnchorWitnessError::Corrupt);
        }
        self.file
            .write_all(&row)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| AnchorWitnessError::Indeterminate)?;
        self.length += RECORD as u64;
        self.count += 1;
        self.current = Some(anchor);
        self.poisoned = false;
        Ok(())
    }

    pub fn current(&self) -> Result<Option<LedgerAnchor>, AnchorWitnessError> {
        if self.poisoned {
            Err(AnchorWitnessError::Poisoned)
        } else {
            Ok(self.current)
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AnchorWitnessError {
    InvalidBinding,
    InvalidAnchor,
    AlreadyInitialized,
    Busy,
    Capacity,
    Regression,
    Corrupt,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for AnchorWitnessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AnchorWitnessError {}

impl From<io::Error> for AnchorWitnessError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

fn map_durable(value: crate::DurableLedgerError) -> AnchorWitnessError {
    match value {
        crate::DurableLedgerError::Busy => AnchorWitnessError::Busy,
        crate::DurableLedgerError::Io(kind) => AnchorWitnessError::Io(kind),
        _ => AnchorWitnessError::Corrupt,
    }
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
