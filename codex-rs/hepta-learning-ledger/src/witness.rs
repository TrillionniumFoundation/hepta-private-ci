//! Independently retained append-only acknowledgement witness for the production
//! learning ledger writer. The host supplies a separately authorized file and is
//! responsible for directory durability, isolation and backup policy.

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

const MAGIC: &[u8; 8] = b"HEPTLW01";
const HEADER: u64 = 72;
const RECORD: u64 = 104;
const MAX_WITNESSES: u64 = 1_000_000;
const WITNESS_DOMAIN: &[u8] = b"hepta.learning-ledger.witness.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WitnessError {
    InvalidBinding,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    Corrupt,
    SequenceConflict,
    AnchorConflict,
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
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// Separate durable witness. This file is intentionally not derived from or
/// stored inside the ledger journal it witnesses.
pub struct IndependentLedgerWitness {
    file: LockedFile,
    binding: Digest32,
    anchor: LedgerAnchor,
    witness_digest: Digest32,
    length: u64,
    poisoned: bool,
}

impl IndependentLedgerWitness {
    pub fn create(file: File, binding: Digest32) -> Result<Self, WitnessError> {
        if binding.is_zero() {
            return Err(WitnessError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_lock_error)?;
        if file.metadata()?.len() != 0 {
            return Err(WitnessError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| WitnessError::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            anchor: empty_anchor(),
            witness_digest: Digest32::ZERO,
            length: HEADER,
            poisoned: false,
        })
    }

    /// Replays every complete witness record. A partial final record can only be
    /// an unacknowledged write because `append_anchor` syncs before returning;
    /// it is therefore truncated after all complete predecessors verify.
    pub fn recover(file: File, binding: Digest32) -> Result<Self, WitnessError> {
        if binding.is_zero() {
            return Err(WitnessError::InvalidBinding);
        }
        let mut file = LockedFile::acquire(file).map_err(map_lock_error)?;
        let length = file.metadata()?.len();
        if length < HEADER {
            return Err(WitnessError::MissingHeader);
        }
        if length > HEADER + RECORD * MAX_WITNESSES {
            return Err(WitnessError::Capacity);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER as usize];
        file.read_exact(&mut header)?;
        if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..72] {
            return Err(WitnessError::Corrupt);
        }
        if &header[8..40] != binding.as_array() {
            return Err(WitnessError::BindingMismatch);
        }

        let complete = (length - HEADER) / RECORD;
        let cursor = HEADER + complete * RECORD;
        let mut anchor = empty_anchor();
        let mut witness_digest = Digest32::ZERO;
        for _ in 0..complete {
            let mut row = [0_u8; RECORD as usize];
            file.read_exact(&mut row)?;
            let sequence = u64::from_be_bytes(
                row[..8]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let chain_digest = Digest32::from_array(
                row[8..40]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let predecessor = Digest32::from_array(
                row[40..72]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            let stored = Digest32::from_array(
                row[72..104]
                    .try_into()
                    .map_err(|_| WitnessError::Corrupt)?,
            );
            if sequence != anchor.sequence + 1
                || chain_digest.is_zero()
                || predecessor != witness_digest
            {
                return Err(WitnessError::Corrupt);
            }
            let expected = digest_witness(binding, sequence, chain_digest, predecessor);
            if stored != expected {
                return Err(WitnessError::Corrupt);
            }
            anchor = LedgerAnchor {
                sequence,
                chain_digest,
            };
            witness_digest = stored;
        }
        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| WitnessError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| WitnessError::Indeterminate)?;
        }
        file.seek(SeekFrom::Start(cursor))?;
        Ok(Self {
            file,
            binding,
            anchor,
            witness_digest,
            length: cursor,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn binding(&self) -> Digest32 {
        self.binding
    }

    pub fn anchor(&self) -> Result<LedgerAnchor, WitnessError> {
        self.ready()?;
        Ok(self.anchor)
    }

    /// Persist the next exact ledger frontier. Equal retries are idempotent;
    /// skipped or conflicting frontiers fail closed.
    pub fn append_anchor(&mut self, anchor: LedgerAnchor) -> Result<(), WitnessError> {
        self.ready()?;
        if anchor == self.anchor {
            return Ok(());
        }
        if anchor.sequence != self.anchor.sequence + 1 {
            return Err(WitnessError::SequenceConflict);
        }
        if anchor.chain_digest.is_zero() {
            return Err(WitnessError::AnchorConflict);
        }
        if anchor.sequence > MAX_WITNESSES {
            return Err(WitnessError::Capacity);
        }
        let digest = digest_witness(
            self.binding,
            anchor.sequence,
            anchor.chain_digest,
            self.witness_digest,
        );
        let mut row = Vec::with_capacity(RECORD as usize);
        row.extend_from_slice(&anchor.sequence.to_be_bytes());
        row.extend_from_slice(anchor.chain_digest.as_array());
        row.extend_from_slice(self.witness_digest.as_array());
        row.extend_from_slice(digest.as_array());
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.length {
            return Err(WitnessError::Corrupt);
        }
        self.file
            .write_all(&row)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| WitnessError::Indeterminate)?;
        self.anchor = anchor;
        self.witness_digest = digest;
        self.length += RECORD;
        self.poisoned = false;
        Ok(())
    }

    fn ready(&self) -> Result<(), WitnessError> {
        if self.poisoned {
            Err(WitnessError::Poisoned)
        } else {
            Ok(())
        }
    }
}

fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn digest_witness(
    binding: Digest32,
    sequence: u64,
    chain_digest: Digest32,
    predecessor: Digest32,
) -> Digest32 {
    let mut bytes = WITNESS_DOMAIN.to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(chain_digest.as_array());
    bytes.extend_from_slice(predecessor.as_array());
    Digest32::of_bytes(&bytes)
}

fn map_lock_error(error: crate::DurableLedgerError) -> WitnessError {
    match error {
        crate::DurableLedgerError::Busy => WitnessError::Io(io::ErrorKind::WouldBlock),
        crate::DurableLedgerError::NotRegular => WitnessError::Io(io::ErrorKind::InvalidInput),
        crate::DurableLedgerError::Io(kind) => WitnessError::Io(kind),
        _ => WitnessError::Corrupt,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    fn temp_path(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "hepta-ledger-witness-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    fn file(path: &PathBuf) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .expect("file")
    }

    #[test]
    fn witness_reopens_exact_acknowledged_frontier() {
        let path = temp_path("reopen");
        let binding = Digest32::of_bytes(b"binding");
        {
            let mut witness = IndependentLedgerWitness::create(file(&path), binding)
                .expect("create witness");
            witness
                .append_anchor(LedgerAnchor {
                    sequence: 1,
                    chain_digest: Digest32::of_bytes(b"chain-1"),
                })
                .expect("anchor 1");
            witness
                .append_anchor(LedgerAnchor {
                    sequence: 2,
                    chain_digest: Digest32::of_bytes(b"chain-2"),
                })
                .expect("anchor 2");
        }
        let recovered =
            IndependentLedgerWitness::recover(file(&path), binding).expect("recover witness");
        assert_eq!(
            recovered.anchor().expect("anchor"),
            LedgerAnchor {
                sequence: 2,
                chain_digest: Digest32::of_bytes(b"chain-2"),
            }
        );
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn witness_rejects_skipped_frontier() {
        let path = temp_path("skip");
        let binding = Digest32::of_bytes(b"binding");
        let mut witness =
            IndependentLedgerWitness::create(file(&path), binding).expect("create witness");
        assert_eq!(
            witness.append_anchor(LedgerAnchor {
                sequence: 2,
                chain_digest: Digest32::of_bytes(b"chain-2"),
            }),
            Err(WitnessError::SequenceConflict)
        );
        drop(witness);
        let _ = std::fs::remove_file(path);
    }
}
