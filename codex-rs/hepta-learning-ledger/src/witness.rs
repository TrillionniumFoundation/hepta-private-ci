//! Independent, host-authorized acknowledgement witness storage for the causal ledger.
//!
//! The witness is intentionally a separate file capability from the ledger. The host
//! is responsible for placing and protecting that file on an independently governed
//! durability boundary. The store is append-only, checksum chained, bounded, and
//! synced before an acknowledgement can be returned to a caller.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::LedgerAnchor;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTLW01";
const HEADER: usize = 72;
const ENTRY: usize = 104;
const MAX_WITNESSES: usize = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WitnessStoreError {
    InvalidBinding,
    InvalidAnchor,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    Corrupt,
    Gap,
    Conflict,
    Capacity,
    Indeterminate,
    Io(std::io::ErrorKind),
}

impl fmt::Display for WitnessStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for WitnessStoreError {}

impl From<std::io::Error> for WitnessStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// Append-only independently retained acknowledgement frontier.
pub struct LedgerWitnessStore {
    file: LockedFile,
    binding: Digest32,
    latest: Option<LedgerAnchor>,
    last_entry_digest: Digest32,
    entries: usize,
    length: u64,
    poisoned: bool,
}

impl LedgerWitnessStore {
    pub fn create(file: File, binding: Digest32) -> Result<Self, WitnessStoreError> {
        if binding.is_zero() {
            return Err(WitnessStoreError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_lock_error)?;
        if file.metadata()?.len() != 0 {
            return Err(WitnessStoreError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            latest: None,
            last_entry_digest: Digest32::ZERO,
            entries: 0,
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(file: File, binding: Digest32) -> Result<Self, WitnessStoreError> {
        if binding.is_zero() {
            return Err(WitnessStoreError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_lock_error)?;
        let length = file.metadata()?.len();
        if length < HEADER as u64 {
            return Err(WitnessStoreError::MissingHeader);
        }
        if (length - HEADER as u64) % ENTRY as u64 != 0 {
            return Err(WitnessStoreError::Corrupt);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER];
        file.read_exact(&mut header)?;
        if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..] {
            return Err(WitnessStoreError::Corrupt);
        }
        if &header[8..40] != binding.as_array() {
            return Err(WitnessStoreError::BindingMismatch);
        }

        let mut latest = None;
        let mut last_entry_digest = Digest32::ZERO;
        let mut entries = 0_usize;
        while HEADER as u64 + entries as u64 * (ENTRY as u64) < length {
            if entries >= MAX_WITNESSES {
                return Err(WitnessStoreError::Capacity);
            }
            let mut raw = [0_u8; ENTRY];
            file.read_exact(&mut raw)?;
            if &raw[40..72] != last_entry_digest.as_array()
                || Digest32::of_bytes(&raw[..72]).as_array() != &raw[72..]
            {
                return Err(WitnessStoreError::Corrupt);
            }
            let sequence = u64::from_be_bytes(
                raw[..8]
                    .try_into()
                    .map_err(|_| WitnessStoreError::Corrupt)?,
            );
            let chain_digest = Digest32::from_array(
                raw[8..40]
                    .try_into()
                    .map_err(|_| WitnessStoreError::Corrupt)?,
            );
            if sequence == 0 || chain_digest.is_zero() {
                return Err(WitnessStoreError::Corrupt);
            }
            if latest.is_some_and(|anchor: LedgerAnchor| sequence != anchor.sequence + 1) {
                return Err(WitnessStoreError::Gap);
            }
            latest = Some(LedgerAnchor {
                sequence,
                chain_digest,
            });
            last_entry_digest = Digest32::of_bytes(&raw);
            entries += 1;
        }
        file.seek(SeekFrom::Start(length))?;
        Ok(Self {
            file,
            binding,
            latest,
            last_entry_digest,
            entries,
            length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn latest(&self) -> Option<LedgerAnchor> {
        self.latest
    }

    #[must_use]
    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    /// Persist and sync one acknowledgement frontier. Equal retries are idempotent.
    pub fn persist(&mut self, anchor: LedgerAnchor) -> Result<(), WitnessStoreError> {
        if self.poisoned {
            return Err(WitnessStoreError::Indeterminate);
        }
        if anchor.sequence == 0 || anchor.chain_digest.is_zero() {
            return Err(WitnessStoreError::InvalidAnchor);
        }
        if let Some(latest) = self.latest {
            if anchor.sequence == latest.sequence {
                return if anchor == latest {
                    Ok(())
                } else {
                    Err(WitnessStoreError::Conflict)
                };
            }
            if anchor.sequence != latest.sequence + 1 {
                return Err(WitnessStoreError::Gap);
            }
        } else if anchor.sequence != 1 {
            return Err(WitnessStoreError::Gap);
        }
        if self.entries >= MAX_WITNESSES {
            return Err(WitnessStoreError::Capacity);
        }

        let mut raw = Vec::with_capacity(ENTRY);
        raw.extend_from_slice(&anchor.sequence.to_be_bytes());
        raw.extend_from_slice(anchor.chain_digest.as_array());
        raw.extend_from_slice(self.last_entry_digest.as_array());
        raw.extend_from_slice(Digest32::of_bytes(&raw).as_array());
        debug_assert_eq!(raw.len(), ENTRY);

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.length {
            return Err(WitnessStoreError::Corrupt);
        }
        self.file
            .write_all(&raw)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        self.latest = Some(anchor);
        self.last_entry_digest = Digest32::of_bytes(&raw);
        self.entries += 1;
        self.length += ENTRY as u64;
        self.poisoned = false;
        Ok(())
    }
}

fn map_lock_error(error: crate::DurableLedgerError) -> WitnessStoreError {
    match error {
        crate::DurableLedgerError::Io(kind) => WitnessStoreError::Io(kind),
        crate::DurableLedgerError::Busy => WitnessStoreError::Conflict,
        crate::DurableLedgerError::NotRegular => WitnessStoreError::Corrupt,
        _ => WitnessStoreError::Corrupt,
    }
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
