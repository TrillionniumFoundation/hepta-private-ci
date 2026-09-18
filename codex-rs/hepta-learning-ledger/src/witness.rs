//! Independent append-only acknowledgement witness for the production ledger.
//!
//! The witness uses a separately authorized file and lock. A ledger commit is
//! not externally acknowledged by LedgerWriter until the corresponding
//! frontier has been synced here. The witness never derives its own state from
//! the ledger file it is meant to protect.

use std::fs::File;
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
const FRAME: usize = 88;
const NO_SEGMENT: u64 = u64::MAX;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerWitnessFrontier {
    pub anchor: LedgerAnchor,
    pub segment: Option<usize>,
    pub sealed: bool,
}

impl LedgerWitnessFrontier {
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            anchor: LedgerAnchor {
                sequence: 0,
                chain_digest: Digest32::ZERO,
            },
            segment: None,
            sealed: false,
        }
    }
}

/// Append-only witness retained independently from the causal ledger.
pub struct LedgerWitnessStore {
    file: LockedFile,
    binding: Digest32,
    frontier: LedgerWitnessFrontier,
    length: u64,
    poisoned: bool,
}

impl LedgerWitnessStore {
    pub fn create(file: File, binding: Digest32) -> Result<Self, DurableLedgerError> {
        validate_binding(binding)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            frontier: LedgerWitnessFrontier::empty(),
            length: HEADER as u64,
            poisoned: false,
        })
    }

    /// Recover the independently retained witness. Only an incomplete final
    /// frame can be truncated; complete invalid history is corruption.
    pub fn recover(file: File, binding: Digest32) -> Result<Self, DurableLedgerError> {
        validate_binding(binding)?;
        let mut file = LockedFile::acquire(file)?;
        let length = file.metadata()?.len();
        if length < HEADER as u64 {
            return Err(DurableLedgerError::MissingHeader);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER];
        file.read_exact(&mut header)?;
        if &header[..8] != MAGIC
            || &header[8..40] != binding.as_array()
            || Digest32::of_bytes(&header[..40]).as_array() != &header[40..]
        {
            return Err(DurableLedgerError::BindingMismatch);
        }

        let mut cursor = HEADER as u64;
        let mut frontier = LedgerWitnessFrontier::empty();
        while length - cursor >= FRAME as u64 {
            let mut frame = [0_u8; FRAME];
            file.read_exact(&mut frame)?;
            if Digest32::of_bytes(&frame[..FRAME - 32]).as_array() != &frame[FRAME - 32..] {
                return Err(DurableLedgerError::Corrupt);
            }
            let next = decode_frontier(&frame[..FRAME - 32])?;
            validate_advance(frontier, next)?;
            frontier = next;
            cursor += FRAME as u64;
        }
        if cursor != length {
            file.set_len(cursor)
                .and_then(|()| file.sync_all())
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        file.seek(SeekFrom::Start(cursor))?;
        Ok(Self {
            file,
            binding,
            frontier,
            length: cursor,
            poisoned: false,
        })
    }

    #[must_use]
    pub const fn binding(&self) -> Digest32 {
        self.binding
    }

    pub fn frontier(&self) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(self.frontier)
        }
    }

    /// Advance exactly one acknowledged ledger record, or replay the exact same
    /// frontier idempotently. Sync completes before the in-memory frontier moves.
    pub fn advance(
        &mut self,
        expected: LedgerWitnessFrontier,
        next: LedgerWitnessFrontier,
    ) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        if self.frontier != expected {
            return Err(DurableLedgerError::Conflict);
        }
        if next == expected {
            return Ok(next);
        }
        validate_advance(expected, next)?;
        let frame = encode_frontier(next)?;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.length {
            return Err(DurableLedgerError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        self.length += frame.len() as u64;
        self.frontier = next;
        self.poisoned = false;
        Ok(next)
    }
}

fn validate_binding(binding: Digest32) -> Result<(), DurableLedgerError> {
    if binding.is_zero() {
        Err(DurableLedgerError::InvalidBinding)
    } else {
        Ok(())
    }
}

fn validate_advance(
    previous: LedgerWitnessFrontier,
    next: LedgerWitnessFrontier,
) -> Result<(), DurableLedgerError> {
    let expected_sequence = previous
        .anchor
        .sequence
        .checked_add(1)
        .ok_or(DurableLedgerError::InvalidAnchor)?;
    if next.anchor.sequence != expected_sequence || next.anchor.chain_digest.is_zero() {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    match (previous.segment, next.segment) {
        (None, None) => {}
        (None, Some(segment)) if segment == 0 => {}
        (Some(previous_segment), Some(next_segment))
            if next_segment == previous_segment || next_segment == previous_segment + 1 => {}
        _ => return Err(DurableLedgerError::InvalidAnchor),
    }
    Ok(())
}

fn encode_frontier(frontier: LedgerWitnessFrontier) -> Result<Vec<u8>, DurableLedgerError> {
    let segment = match frontier.segment {
        Some(segment) => u64::try_from(segment).map_err(|_| DurableLedgerError::InvalidAnchor)?,
        None => NO_SEGMENT,
    };
    let mut bytes = Vec::with_capacity(FRAME);
    bytes.extend_from_slice(&frontier.anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(&segment.to_be_bytes());
    bytes.push(u8::from(frontier.sealed));
    bytes.extend_from_slice(&[0_u8; 7]);
    bytes.extend_from_slice(frontier.anchor.chain_digest.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    Ok(bytes)
}

fn decode_frontier(bytes: &[u8]) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
    if bytes.len() != FRAME - 32 || bytes[17..24].iter().any(|value| *value != 0) {
        return Err(DurableLedgerError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        bytes[0..8]
            .try_into()
            .map_err(|_| DurableLedgerError::Corrupt)?,
    );
    let raw_segment = u64::from_be_bytes(
        bytes[8..16]
            .try_into()
            .map_err(|_| DurableLedgerError::Corrupt)?,
    );
    let sealed = match bytes[16] {
        0 => false,
        1 => true,
        _ => return Err(DurableLedgerError::Corrupt),
    };
    let segment = if raw_segment == NO_SEGMENT {
        None
    } else {
        Some(usize::try_from(raw_segment).map_err(|_| DurableLedgerError::Corrupt)?)
    };
    let chain_digest = Digest32::from_array(
        bytes[24..56]
            .try_into()
            .map_err(|_| DurableLedgerError::Corrupt)?,
    );
    Ok(LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence,
            chain_digest,
        },
        segment,
        sealed,
    })
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
