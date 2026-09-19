//! Opt-in, single-generation journal over host-authorized, exclusively owned files.
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
const SUCCESSOR_MAGIC: &[u8; 8] = b"HPTNSJ02";
const SUCCESSOR_HEADER: usize = 176;
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
    base_sequence: u64,
    base_anchor: Option<JournalAnchor>,
    data_offset: usize,
    entries: Vec<(Digest32, SparseSignalReceipt)>,
    current: Option<SparseCheckpoint>,
    poisoned: bool,
}

impl SparseJournal {
    /// Bootstrap or recover the first segment without an external acknowledgement
    /// witness. This cannot detect loss of a valid suffix or empty replacement.
    pub fn open(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, JournalError> {
        Self::open_with_policy(file, config, scope, max_records, RecoveryPolicy::Unanchored)
    }

    /// Recover the first segment at least through the externally acknowledged
    /// checkpoint. Anchor validation occurs before any repair.
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
        validate_limit(max_records)?;
        if let RecoveryPolicy::Require(anchor) = policy
            && (anchor.sequence == 0
                || anchor.sequence > max_records as u64
                || anchor.checkpoint_digest.is_zero())
        {
            return Err(JournalError::InvalidAnchor);
        }
        let config_digest = config.digest().map_err(JournalError::Mechanism)?;
        validate_scope(scope)?;
        let mut file = LockedFile::acquire(file)?;
        let header = root_header(config_digest, scope);
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
            validate_exact_header(&mut file, &header, HEADER, MAGIC)?;
        }
        Self::recover_frames(
            file,
            config,
            scope,
            max_records,
            policy,
            None,
            HEADER,
        )
    }

    /// Open or create a successor segment seeded from the exact final checkpoint
    /// of the predecessor segment. The seed is part of the HPTNSJ02 header, so a
    /// valid-prefix rollback of the predecessor cannot be silently composed with
    /// this segment.
    pub fn open_successor(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        seed: &SparseCheckpoint,
    ) -> Result<Self, JournalError> {
        Self::open_successor_with_policy(
            file,
            config,
            scope,
            max_records,
            seed,
            RecoveryPolicy::Unanchored,
        )
    }

    /// Recover a successor segment while requiring at least the independently
    /// acknowledged checkpoint. Later complete frames are retained for lost-ack
    /// reconciliation exactly as for the first segment.
    pub fn open_successor_anchored(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        seed: &SparseCheckpoint,
        anchor: JournalAnchor,
    ) -> Result<Self, JournalError> {
        Self::open_successor_with_policy(
            file,
            config,
            scope,
            max_records,
            seed,
            RecoveryPolicy::Require(anchor),
        )
    }

    fn open_successor_with_policy(
        file: File,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        seed: &SparseCheckpoint,
        policy: RecoveryPolicy,
    ) -> Result<Self, JournalError> {
        validate_limit(max_records)?;
        validate_scope(scope)?;
        let config_digest = config.digest().map_err(JournalError::Mechanism)?;
        if !seed.matches_segment_context(config_digest, scope.scope_digest, scope.objective_digest) {
            return Err(JournalError::ContextMismatch);
        }
        let seed_anchor = JournalAnchor {
            sequence: seed.sequence(),
            checkpoint_digest: seed.digest(),
        };
        if let RecoveryPolicy::Require(anchor) = policy {
            if anchor.sequence == 0
                || anchor.sequence < seed_anchor.sequence
                || anchor.sequence
                    > seed_anchor
                        .sequence
                        .saturating_add(max_records as u64)
                || anchor.checkpoint_digest.is_zero()
            {
                return Err(JournalError::InvalidAnchor);
            }
            if anchor.sequence == seed_anchor.sequence
                && anchor.checkpoint_digest != seed_anchor.checkpoint_digest
            {
                return Err(JournalError::AnchorMismatch);
            }
        }

        let mut file = LockedFile::acquire(file)?;
        let header = successor_header(config_digest, scope, seed_anchor);
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            if let RecoveryPolicy::Require(anchor) = policy
                && anchor.sequence > seed_anchor.sequence
            {
                return Err(JournalError::AcknowledgedHistoryMissing);
            }
            file.write_all(&header)
                .map_err(|_| JournalError::Indeterminate)?;
            file.sync_all().map_err(|_| JournalError::Indeterminate)?;
        } else {
            validate_exact_header(
                &mut file,
                &header,
                SUCCESSOR_HEADER,
                SUCCESSOR_MAGIC,
            )?;
        }
        Self::recover_frames(
            file,
            config,
            scope,
            max_records,
            policy,
            Some(seed.clone()),
            SUCCESSOR_HEADER,
        )
    }

    fn recover_frames(
        mut file: LockedFile,
        config: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        policy: RecoveryPolicy,
        seed: Option<SparseCheckpoint>,
        data_offset: usize,
    ) -> Result<Self, JournalError> {
        let frame_len = 304 + 16 * config.width;
        let length = file.metadata()?.len();
        if length < data_offset as u64
            || length
                > (data_offset + max_records * frame_len + frame_len - 1) as u64
        {
            return Err(JournalError::Capacity);
        }
        let base_sequence = seed.as_ref().map_or(0, SparseCheckpoint::sequence);
        let base_anchor = seed.as_ref().map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        });
        let mut journal = Self {
            file,
            config,
            scope,
            max_records,
            base_sequence,
            base_anchor,
            data_offset,
            entries: Vec::new(),
            current: seed,
            poisoned: false,
        };
        let available = length.saturating_sub(data_offset as u64) as usize;
        let complete = available / frame_len;
        if complete > max_records {
            return Err(JournalError::Capacity);
        }
        journal.file.seek(SeekFrom::Start(data_offset as u64))?;
        let mut frame = vec![0; frame_len];
        for _ in 0..complete {
            journal.file.read_exact(&mut frame)?;
            if Digest32::of_bytes(&frame[..frame_len - 32]).as_array()
                != &frame[frame_len - 32..]
            {
                return Err(JournalError::Corrupt);
            }
            let tick = decode_tick(&frame[..frame_len - 128], journal.config.width)?;
            if tick.scope_digest != scope.scope_digest
                || tick.objective_digest != scope.objective_digest
            {
                return Err(JournalError::Corrupt);
            }
            let (state, receipt) =
                sparse_tick(&journal.config, &tick, journal.current.as_ref())
                    .map_err(|_| JournalError::Corrupt)?;
            if encode_frame(&tick, &receipt) != frame {
                return Err(JournalError::Corrupt);
            }
            journal
                .entries
                .push((Digest32::of_bytes(&encode_tick(&tick)), receipt));
            journal.current = Some(state);
        }

        if let RecoveryPolicy::Require(anchor) = policy {
            let actual = journal.anchor_at(anchor.sequence);
            match actual {
                None => return Err(JournalError::AcknowledgedHistoryMissing),
                Some(actual) if actual.checkpoint_digest != anchor.checkpoint_digest => {
                    return Err(JournalError::AnchorMismatch);
                }
                Some(_) => {}
            }
        }

        if !available.is_multiple_of(frame_len) {
            journal
                .file
                .set_len((data_offset + complete * frame_len) as u64)
                .map_err(|_| JournalError::Indeterminate)?;
            journal
                .file
                .sync_all()
                .map_err(|_| JournalError::Indeterminate)?;
        }
        journal
            .file
            .sync_data()
            .map_err(|_| JournalError::Indeterminate)?;
        Ok(journal)
    }

    /// Start the next bounded segment from the exact current checkpoint.
    pub fn start_successor(
        &self,
        file: File,
        max_records: usize,
    ) -> Result<Self, JournalError> {
        if self.poisoned {
            return Err(JournalError::Poisoned);
        }
        let seed = self.current.as_ref().ok_or(JournalError::InvalidAnchor)?;
        Self::open_successor(
            file,
            self.config.clone(),
            self.scope,
            max_records,
            seed,
        )
    }

    /// Recover a successor segment using this journal's exact current checkpoint
    /// as its seed and an independently retained acknowledgement witness.
    pub fn recover_successor(
        &self,
        file: File,
        max_records: usize,
        anchor: JournalAnchor,
    ) -> Result<Self, JournalError> {
        if self.poisoned {
            return Err(JournalError::Poisoned);
        }
        let seed = self.current.as_ref().ok_or(JournalError::InvalidAnchor)?;
        Self::open_successor_anchored(
            file,
            self.config.clone(),
            self.scope,
            max_records,
            seed,
            anchor,
        )
    }

    /// Compare-and-append one tick. Equal retries return the exact committed
    /// receipt, including after later ticks in the same segment.
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
            .checked_sub(self.base_sequence)
            .and_then(|relative| relative.checked_sub(1))
            .and_then(|relative| usize::try_from(relative).ok())
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
        let expected_length = (self.data_offset + self.entries.len() * frame.len()) as u64;
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

    pub fn remaining_capacity(&self) -> Result<usize, JournalError> {
        if self.poisoned {
            Err(JournalError::Poisoned)
        } else {
            Ok(self.max_records.saturating_sub(self.entries.len()))
        }
    }

    fn anchor_at(&self, sequence: u64) -> Option<JournalAnchor> {
        if sequence == self.base_sequence {
            return self.base_anchor;
        }
        let index = sequence
            .checked_sub(self.base_sequence)?
            .checked_sub(1)
            .and_then(|relative| usize::try_from(relative).ok())?;
        self.entries.get(index).map(|(_, receipt)| JournalAnchor {
            sequence,
            checkpoint_digest: receipt.checkpoint_after,
        })
    }
}

fn validate_limit(max_records: usize) -> Result<(), JournalError> {
    if !(1..=MAX_RECORDS).contains(&max_records) {
        Err(JournalError::InvalidLimit)
    } else {
        Ok(())
    }
}

fn validate_scope(scope: JournalScope) -> Result<(), JournalError> {
    if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
        Err(JournalError::ContextMismatch)
    } else {
        Ok(())
    }
}

fn root_header(config_digest: Digest32, scope: JournalScope) -> Vec<u8> {
    let mut header = MAGIC.to_vec();
    for digest in [config_digest, scope.scope_digest, scope.objective_digest] {
        header.extend_from_slice(digest.as_array());
    }
    let checksum = Digest32::of_bytes(&header);
    header.extend_from_slice(checksum.as_array());
    header
}

fn successor_header(
    config_digest: Digest32,
    scope: JournalScope,
    seed: JournalAnchor,
) -> Vec<u8> {
    let mut header = SUCCESSOR_MAGIC.to_vec();
    for digest in [config_digest, scope.scope_digest, scope.objective_digest] {
        header.extend_from_slice(digest.as_array());
    }
    header.extend_from_slice(&seed.sequence.to_be_bytes());
    header.extend_from_slice(seed.checkpoint_digest.as_array());
    let checksum = Digest32::of_bytes(&header);
    header.extend_from_slice(checksum.as_array());
    header
}

fn validate_exact_header(
    file: &mut LockedFile,
    expected: &[u8],
    header_len: usize,
    magic: &[u8; 8],
) -> Result<(), JournalError> {
    let length = file.metadata()?.len();
    if length < header_len as u64 {
        return Err(JournalError::Corrupt);
    }
    let mut actual = vec![0_u8; header_len];
    file.read_exact(&mut actual)?;
    if &actual[..8] != magic
        || Digest32::of_bytes(&actual[..header_len - 32]).as_array()
            != &actual[header_len - 32..]
    {
        return Err(JournalError::Corrupt);
    }
    if actual != expected {
        return Err(JournalError::ContextMismatch);
    }
    Ok(())
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

#[cfg(test)]
#[path = "journal_segment_tests.rs"]
mod segment_tests;
