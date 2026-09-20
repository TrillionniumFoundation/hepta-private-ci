//! Opt-in, single-generation journal over a host-authorized, exclusively owned file.
//! Complete frames bind the tick, checkpoint and receipt; no production authority.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::journal_lock::LockedFile;

use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseError;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::sparse_tick;

const MAGIC: &[u8; 8] = b"HPTNSJ01";
const HEADER: usize = 136;
const MAX_RECORDS: usize = 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JournalScope {
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
}

/// Minimum acknowledged history retained by a separate trusted host store.
/// The host must authenticate and scope this witness; a supplied digest is not
/// a credential. Do not reconstruct the witness from the file being recovered.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JournalAnchor {
    pub sequence: u64,
    pub checkpoint_digest: Digest32,
}

#[derive(Clone, Copy)]
enum RecoveryPolicy {
    Unanchored,
    Require(JournalAnchor),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum JournalError {
    Busy,
    InvalidLimit,
    InvalidAnchor,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    NotRegular,
    Corrupt,
    ContextMismatch,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Mechanism(SparseError),
}

impl fmt::Display for JournalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for JournalError {}
impl From<io::Error> for JournalError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// Host must supply a fresh read/write handle, not a clone of a locked handle.
/// The file and its directory must be private to this owner on a lock-capable
/// local filesystem. Locks are advisory; this is not a hostile-writer sandbox.
/// No paths are opened here. The host owns enrollment, revocation and deletion.
pub struct SparseJournal {
    file: LockedFile,
    config: SparseConfig,
    scope: JournalScope,
    max_records: usize,
    entries: Vec<(Digest32, SparseSignalReceipt)>,
    current: Option<SparseCheckpoint>,
    poisoned: bool,
}

impl SparseJournal {
    /// Bootstrap or recover without an external acknowledgement witness.
    /// This cannot detect loss of a valid suffix or replacement with an empty file.
    /// Use `open_anchored` when the host has previously acknowledged history.
    /// New-file directory durability must be established separately by the host.
    pub fn open(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, JournalError> {
        Self::open_with_policy(file, config, scope, max_records, RecoveryPolicy::Unanchored)
    }

    /// Recover at least the externally acknowledged checkpoint. A missing or
    /// different prefix rejects before any repair or initialization. Later complete
    /// valid frames remain eligible for lost-acknowledgement reconciliation.
    pub fn open_anchored(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        anchor: JournalAnchor,
    ) -> Result<Self, JournalError> {
        Self::open_with_policy(
            file,
            config,
            scope,
            max_records,
            RecoveryPolicy::Require(anchor),
        )
    }

    fn open_with_policy(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        policy: RecoveryPolicy,
    ) -> Result<Self, JournalError> {
        if !(1..=MAX_RECORDS).contains(&max_records) {
            return Err(JournalError::InvalidLimit);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && (anchor.sequence == 0
                || anchor.sequence > max_records as u64
                || anchor.checkpoint_digest.is_zero())
        {
            return Err(JournalError::InvalidAnchor);
        }
        let config_digest = config.digest().map_err(JournalError::Mechanism)?;
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(JournalError::ContextMismatch);
        }
        let mut file = LockedFile::acquire(file)?;
        let mut header = MAGIC.to_vec();
        for digest in [config_digest, scope.scope_digest, scope.objective_digest] {
            header.extend_from_slice(digest.as_array());
        }
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            if let RecoveryPolicy::Require(_) = policy {
                return Err(JournalError::AcknowledgedHistoryMissing);
            }
            file.write_all(&header)
                .map_err(|_| JournalError::Indeterminate)?;
            file.sync_all().map_err(|_| JournalError::Indeterminate)?;
        } else {
            if length < HEADER as u64 {
                return Err(JournalError::Corrupt);
            }
            let mut actual = [0; HEADER];
            file.read_exact(&mut actual)?;
            if &actual[..8] != MAGIC
                || Digest32::of_bytes(&actual[..HEADER - 32]).as_array() != &actual[HEADER - 32..]
            {
                return Err(JournalError::Corrupt);
            }
            if actual.as_slice() != header {
                return Err(JournalError::ContextMismatch);
            }
        }
        let frame_len = 304 + 16 * config.width;
        // Permit at most one incomplete tail, never an unbounded recovery scan.
        if length > (HEADER + max_records * frame_len + frame_len - 1) as u64 {
            return Err(JournalError::Capacity);
        }
        let mut journal = Self {
            file,
            config,
            scope,
            max_records,
            entries: Vec::new(),
            current: None,
            poisoned: false,
        };
        let available = length.saturating_sub(HEADER as u64) as usize;
        let complete = available / frame_len;
        if complete > max_records {
            return Err(JournalError::Capacity);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && complete < anchor.sequence as usize
        {
            return Err(JournalError::AcknowledgedHistoryMissing);
        }
        let mut frame = vec![0; frame_len];
        for _ in 0..complete {
            journal.file.read_exact(&mut frame)?;
            if Digest32::of_bytes(&frame[..frame_len - 32]).as_array() != &frame[frame_len - 32..] {
                return Err(JournalError::Corrupt);
            }
            let tick = decode_tick(&frame[..frame_len - 128], journal.config.width)?;
            if tick.scope_digest != scope.scope_digest
                || tick.objective_digest != scope.objective_digest
            {
                return Err(JournalError::Corrupt);
            }
            let (state, receipt) = sparse_tick(&journal.config, &tick, journal.current.as_ref())
                .map_err(|_| JournalError::Corrupt)?;
            if encode_frame(&tick, &receipt) != frame {
                return Err(JournalError::Corrupt);
            }
            journal
                .entries
                .push((Digest32::of_bytes(&encode_tick(&tick)), receipt));
            journal.current = Some(state);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && journal.entries[(anchor.sequence - 1) as usize]
                .1
                .checkpoint_after
                != anchor.checkpoint_digest
        {
            return Err(JournalError::AnchorMismatch);
        }
        if !available.is_multiple_of(frame_len) {
            journal
                .file
                .set_len((HEADER + complete * frame_len) as u64)
                .map_err(|_| JournalError::Indeterminate)?;
            journal
                .file
                .sync_all()
                .map_err(|_| JournalError::Indeterminate)?;
        }
        // A previous sync may have failed after writing a full frame. Reopening
        // must establish durability before returning a recovered committed receipt.
        journal
            .file
            .sync_data()
            .map_err(|_| JournalError::Indeterminate)?;
        Ok(journal)
    }

    /// Compare-and-append one tick. Equal retries return the exact committed receipt,
    /// including when later ticks exist. Changed retry content or predecessor conflicts.
    /// Any write/sync failure poisons this handle; reopen and reconcile, never blind retry.
    pub fn commit(
        &mut self,
        expected_predecessor: Digest32,
        tick: &SparseTick,
    ) -> Result<SparseSignalReceipt, JournalError> {
        if self.poisoned {
            return Err(JournalError::Poisoned);
        }
        if tick.drive_q24.len() != self.config.width
            || tick.prediction_q24.len() != self.config.width
        {
            return Err(JournalError::Mechanism(SparseError::InvalidInput));
        }
        if tick.scope_digest != self.scope.scope_digest
            || tick.objective_digest != self.scope.objective_digest
        {
            return Err(JournalError::ContextMismatch);
        }
        let tick_digest = Digest32::of_bytes(&encode_tick(tick));
        if let Some(index) = tick
            .sequence
            .checked_sub(1)
            .and_then(|n| usize::try_from(n).ok())
            && let Some((prior_digest, receipt)) = self.entries.get(index)
        {
            return if *prior_digest == tick_digest
                && receipt.checkpoint_before == expected_predecessor
            {
                Ok(receipt.clone())
            } else {
                Err(JournalError::Conflict)
            };
        }
        if self
            .current
            .as_ref()
            .map_or(Digest32::ZERO, SparseCheckpoint::digest)
            != expected_predecessor
        {
            return Err(JournalError::Conflict);
        }
        if self.entries.len() >= self.max_records {
            return Err(JournalError::Capacity);
        }
        let (state, receipt) = sparse_tick(&self.config, tick, self.current.as_ref())
            .map_err(JournalError::Mechanism)?;
        let frame = encode_frame(tick, &receipt);
        let expected_length = (HEADER + self.entries.len() * frame.len()) as u64;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(JournalError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .map_err(|_| JournalError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| JournalError::Indeterminate)?;
        self.entries.push((tick_digest, receipt.clone()));
        self.current = Some(state);
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current(&self) -> Result<Option<&SparseCheckpoint>, JournalError> {
        if self.poisoned {
            Err(JournalError::Poisoned)
        } else {
            Ok(self.current.as_ref())
        }
    }
}

fn encode_tick(tick: &SparseTick) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&tick.sequence.to_be_bytes());
    bytes.extend_from_slice(&tick.monotonic_micros.to_be_bytes());
    for digest in [
        tick.scope_digest,
        tick.objective_digest,
        tick.ndu_digest,
        tick.body_digest,
        tick.input_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in tick.drive_q24.iter().chain(&tick.prediction_q24) {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes
}

fn encode_frame(tick: &SparseTick, receipt: &SparseSignalReceipt) -> Vec<u8> {
    let mut bytes = encode_tick(tick);
    bytes.extend_from_slice(receipt.checkpoint_before.as_array());
    bytes.extend_from_slice(receipt.checkpoint_after.as_array());
    let mut signal = b"hepta.neuron.journal-receipt.v1".to_vec();
    signal.extend_from_slice(receipt.config_digest.as_array());
    signal.extend_from_slice(receipt.input_digest.as_array());
    for value in &receipt.activation_q24 {
        signal.extend_from_slice(&value.to_be_bytes());
    }
    signal.extend_from_slice(&receipt.active_fraction_ppm.to_be_bytes());
    signal.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
    signal.extend_from_slice(&receipt.projection_count.to_be_bytes());
    signal.extend_from_slice(&[
        u8::from(receipt.requires_calibration),
        u8::from(receipt.authority.grants_any()),
    ]);
    bytes.extend_from_slice(Digest32::of_bytes(&signal).as_array());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    bytes
}

fn take<const N: usize>(bytes: &mut &[u8]) -> Result<[u8; N], JournalError> {
    if bytes.len() < N {
        return Err(JournalError::Corrupt);
    }
    let (value, remaining) = bytes.split_at(N);
    *bytes = remaining;
    value.try_into().map_err(|_| JournalError::Corrupt)
}

fn decode_tick(mut bytes: &[u8], width: usize) -> Result<SparseTick, JournalError> {
    let sequence = u64::from_be_bytes(take(&mut bytes)?);
    let monotonic_micros = u64::from_be_bytes(take(&mut bytes)?);
    let scope_digest = Digest32::from_array(take(&mut bytes)?);
    let objective_digest = Digest32::from_array(take(&mut bytes)?);
    let ndu_digest = Digest32::from_array(take(&mut bytes)?);
    let body_digest = Digest32::from_array(take(&mut bytes)?);
    let input_digest = Digest32::from_array(take(&mut bytes)?);
    let mut drive_q24 = Vec::with_capacity(width);
    let mut prediction_q24 = Vec::with_capacity(width);
    for output in [&mut drive_q24, &mut prediction_q24] {
        for _ in 0..width {
            output.push(i64::from_be_bytes(take(&mut bytes)?));
        }
    }
    if !bytes.is_empty() {
        return Err(JournalError::Corrupt);
    }
    Ok(SparseTick {
        scope_digest,
        objective_digest,
        ndu_digest,
        body_digest,
        input_digest,
        sequence,
        monotonic_micros,
        drive_q24,
        prediction_q24,
    })
}

#[cfg(test)]
#[path = "journal_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "journal_anchor_tests.rs"]
mod anchor_tests;
