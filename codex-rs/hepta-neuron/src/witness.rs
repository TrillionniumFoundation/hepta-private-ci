//! Crash-durable independently opened recovery witness for sparse journals.
//!
//! The witness is deliberately separate from the journal file. It closes lost-
//! acknowledgement recovery for an honest host, but is not a hostile rollback
//! oracle: a production host still authenticates this store and protects its
//! freshness outside the journal's trust domain.

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
use crate::journal_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HPTNWA01";
const RECORD_BYTES: usize = 113;

pub trait RecoveryWitnessStore {
    fn current_anchor(&self) -> Result<Option<JournalAnchor>, WitnessError>;
    fn compare_and_store(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WitnessError {
    Lock(JournalError),
    Context,
    Corrupt,
    InvalidAnchor,
    Conflict,
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

pub struct FileRecoveryWitness {
    file: LockedFile,
    context_digest: Digest32,
    anchor: Option<JournalAnchor>,
    poisoned: bool,
}

impl FileRecoveryWitness {
    pub fn open(file: File, context_digest: Digest32) -> Result<Self, WitnessError> {
        if context_digest.is_zero() {
            return Err(WitnessError::Context);
        }
        let mut file = LockedFile::acquire(file).map_err(WitnessError::Lock)?;
        let length = file.metadata()?.len();
        let anchor = if length == 0 {
            let bytes = encode(context_digest, None);
            file.seek(SeekFrom::Start(0))?;
            file.write_all(&bytes)
                .map_err(|_| WitnessError::Indeterminate)?;
            file.sync_all().map_err(|_| WitnessError::Indeterminate)?;
            None
        } else {
            if length != RECORD_BYTES as u64 {
                return Err(WitnessError::Corrupt);
            }
            let mut bytes = [0_u8; RECORD_BYTES];
            file.seek(SeekFrom::Start(0))?;
            file.read_exact(&mut bytes)?;
            decode(context_digest, &bytes)?
        };
        Ok(Self {
            file,
            context_digest,
            anchor,
            poisoned: false,
        })
    }

    pub fn context_digest(&self) -> Digest32 {
        self.context_digest
    }
}

impl RecoveryWitnessStore for FileRecoveryWitness {
    fn current_anchor(&self) -> Result<Option<JournalAnchor>, WitnessError> {
        if self.poisoned {
            Err(WitnessError::Poisoned)
        } else {
            Ok(self.anchor)
        }
    }

    fn compare_and_store(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessError> {
        if self.poisoned {
            return Err(WitnessError::Poisoned);
        }
        if next.sequence == 0 || next.checkpoint_digest.is_zero() {
            return Err(WitnessError::InvalidAnchor);
        }
        if self.anchor != expected {
            return Err(WitnessError::Conflict);
        }
        if let Some(current) = self.anchor {
            if next == current {
                return Ok(());
            }
            if current.sequence.checked_add(1) != Some(next.sequence) {
                return Err(WitnessError::Conflict);
            }
        } else if next.sequence != 1 {
            return Err(WitnessError::Conflict);
        }
        let bytes = encode(self.context_digest, Some(next));
        self.poisoned = true;
        self.file.seek(SeekFrom::Start(0))?;
        self.file
            .write_all(&bytes)
            .map_err(|_| WitnessError::Indeterminate)?;
        self.file
            .set_len(RECORD_BYTES as u64)
            .map_err(|_| WitnessError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| WitnessError::Indeterminate)?;
        self.anchor = Some(next);
        self.poisoned = false;
        Ok(())
    }
}

fn encode(context_digest: Digest32, anchor: Option<JournalAnchor>) -> [u8; RECORD_BYTES] {
    let mut bytes = Vec::with_capacity(RECORD_BYTES);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(context_digest.as_array());
    match anchor {
        Some(anchor) => {
            bytes.push(1);
            bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
            bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
        }
        None => {
            bytes.push(0);
            bytes.extend_from_slice(&0_u64.to_be_bytes());
            bytes.extend_from_slice(Digest32::ZERO.as_array());
        }
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
        .try_into()
        .unwrap_or_else(|_| unreachable!("fixed witness record size"))
}

fn decode(
    expected_context: Digest32,
    bytes: &[u8; RECORD_BYTES],
) -> Result<Option<JournalAnchor>, WitnessError> {
    if &bytes[..8] != MAGIC {
        return Err(WitnessError::Corrupt);
    }
    let context = Digest32::from_array(
        bytes[8..40]
            .try_into()
            .map_err(|_| WitnessError::Corrupt)?,
    );
    if context != expected_context {
        return Err(WitnessError::Context);
    }
    if Digest32::of_bytes(&bytes[..RECORD_BYTES - 32]).as_array()
        != &bytes[RECORD_BYTES - 32..]
    {
        return Err(WitnessError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        bytes[41..49]
            .try_into()
            .map_err(|_| WitnessError::Corrupt)?,
    );
    let checkpoint_digest = Digest32::from_array(
        bytes[49..81]
            .try_into()
            .map_err(|_| WitnessError::Corrupt)?,
    );
    match bytes[40] {
        0 if sequence == 0 && checkpoint_digest.is_zero() => Ok(None),
        1 if sequence != 0 && !checkpoint_digest.is_zero() => Ok(Some(JournalAnchor {
            sequence,
            checkpoint_digest,
        })),
        _ => Err(WitnessError::Corrupt),
    }
}
