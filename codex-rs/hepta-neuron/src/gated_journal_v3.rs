//! V3-only, bounded, file-backed shadow journal. The separate HPTNGV03 wire
//! format cannot be parsed as V1 or V2; this module never opens a V1 journal.
//!
//! The host supplies a fresh authenticated read/write file and protects the
//! directory. Locking is advisory and no signature, Artifact CAS, or production
//! route authority is acquired by this journal. An independent witness must
//! anchor every acknowledged checkpoint and is NOT reconstructed from this file.

use std::error::Error;
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
use crate::gated_sparse_v3::GatedSparseCheckpointV3;
use crate::gated_sparse_v3::GatedSparseConfigV3;
use crate::gated_sparse_v3::GatedSparseErrorV3;
use crate::gated_sparse_v3::GatedSparseSignalReceiptV3;
use crate::gated_sparse_v3::gated_sparse_tick_v3;
use crate::journal_lock::LockedFile;
use crate::population_v2::PopulationSparseTickV2;

const MAGIC: &[u8; 8] = b"HPTNGV03";
const HEADER_BYTES: usize = 136;
const FIXED_TICK_BYTES: usize = 176;
const FRAME_EXTRA_BYTES: usize = 160;
const MAX_RECORDS: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GatedJournalErrorV3 {
    BusyOrInvalidFile(JournalError),
    InvalidLimit,
    InvalidAnchor,
    ExistingJournalRequiresAnchor,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    ContextMismatch,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Mechanism(GatedSparseErrorV3),
}

impl fmt::Display for GatedJournalErrorV3 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for GatedJournalErrorV3 {}

impl From<io::Error> for GatedJournalErrorV3 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

pub struct GatedSparseJournalV3 {
    file: LockedFile,
    config: GatedSparseConfigV3,
    scope: JournalScope,
    limit: usize,
    // 32 bytes per historical tick, independent of temporal/activation widths.
    // Historical receipts are rebuilt on the rare idempotent retry instead of
    // retaining up to 1024 full activation/gate vectors per Cell.
    entries: Vec<Digest32>,
    current: Option<GatedSparseCheckpointV3>,
    poisoned: bool,
}

impl GatedSparseJournalV3 {
    /// Bootstrap a new, empty shadow-generation file. Existing files never
    /// reopen without an independently retained checkpoint witness.
    pub fn open(
        file: File,
        config: GatedSparseConfigV3,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, GatedJournalErrorV3> {
        Self::open_with_anchor(file, config, scope, max_records, None)
    }

    /// Requires the exact independently durable acknowledged checkpoint.
    /// Complete valid but unacknowledged suffixes are replayed/reconciled;
    /// a missing, changed or partially lost acknowledged frame is rejected.
    pub fn open_anchored(
        file: File,
        config: GatedSparseConfigV3,
        scope: JournalScope,
        max_records: usize,
        anchor: JournalAnchor,
    ) -> Result<Self, GatedJournalErrorV3> {
        Self::open_with_anchor(file, config, scope, max_records, Some(anchor))
    }

    fn open_with_anchor(
        file: File,
        config: GatedSparseConfigV3,
        scope: JournalScope,
        max_records: usize,
        anchor: Option<JournalAnchor>,
    ) -> Result<Self, GatedJournalErrorV3> {
        if !(1..=MAX_RECORDS).contains(&max_records) {
            return Err(GatedJournalErrorV3::InvalidLimit);
        }
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(GatedJournalErrorV3::ContextMismatch);
        }
        if anchor.is_some_and(|a| {
            a.sequence == 0 || a.sequence > max_records as u64 || a.checkpoint_digest.is_zero()
        }) {
            return Err(GatedJournalErrorV3::InvalidAnchor);
        }
        let digest = config.digest().map_err(GatedJournalErrorV3::Mechanism)?;
        let header = encode_header(digest, scope);
        let mut file = LockedFile::acquire(file).map_err(GatedJournalErrorV3::BusyOrInvalidFile)?;
        let length = file.metadata()?.len();
        if length == 0 {
            if anchor.is_some() {
                return Err(GatedJournalErrorV3::AcknowledgedHistoryMissing);
            }
            file.seek(SeekFrom::Start(0))?;
            file.write_all(&header)
                .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
            file.sync_all()
                .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        } else {
            if anchor.is_none() {
                return Err(GatedJournalErrorV3::ExistingJournalRequiresAnchor);
            }
            if length < HEADER_BYTES as u64 {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            let mut observed = [0_u8; HEADER_BYTES];
            file.seek(SeekFrom::Start(0))?;
            file.read_exact(&mut observed)?;
            if observed.as_slice() != header.as_slice() {
                return Err(GatedJournalErrorV3::Corrupt);
            }
        }

        let frame_len = frame_length(&config);
        let length = file.metadata()?.len();
        let available = length
            .checked_sub(HEADER_BYTES as u64)
            .ok_or(GatedJournalErrorV3::Corrupt)?;
        let frame_len_u64 = frame_len as u64;
        // An interrupted extra append may leave an incomplete final frame.
        if available > (max_records as u64) * frame_len_u64 + frame_len_u64 - 1 {
            return Err(GatedJournalErrorV3::Capacity);
        }
        let complete = (available / frame_len_u64) as usize;
        if complete > max_records {
            return Err(GatedJournalErrorV3::Capacity);
        }
        let mut result = Self {
            file,
            config,
            scope,
            limit: max_records,
            entries: Vec::with_capacity(complete),
            current: None,
            poisoned: false,
        };
        result.file.seek(SeekFrom::Start(HEADER_BYTES as u64))?;
        let mut frame = vec![0_u8; frame_len];
        for _ in 0..complete {
            result.file.read_exact(&mut frame)?;
            let checksum = Digest32::of_bytes(&frame[..frame_len - 32]);
            if checksum.as_array() != &frame[frame_len - 32..] {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            let tick = decode_tick(
                &frame[..frame_len - FRAME_EXTRA_BYTES],
                result.config.base.temporal_width,
                result.config.base.activation_width,
            )?;
            if tick.scope_digest != scope.scope_digest
                || tick.objective_digest != scope.objective_digest
            {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            let (next, receipt) =
                gated_sparse_tick_v3(&result.config, &tick, result.current.as_ref())
                    .map_err(|_| GatedJournalErrorV3::Corrupt)?;
            if encode_frame(&tick, &receipt) != frame {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            result.entries.push(receipt.checkpoint_after);
            result.current = Some(next);
        }

        if let Some(anchor) = anchor {
            match result.anchor_at(anchor.sequence) {
                None => return Err(GatedJournalErrorV3::AcknowledgedHistoryMissing),
                Some(found) if found != anchor => return Err(GatedJournalErrorV3::AnchorMismatch),
                Some(_) => {}
            }
        }
        if available % frame_len_u64 != 0 {
            result
                .file
                .set_len(HEADER_BYTES as u64 + (complete as u64) * frame_len_u64)
                .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
            result
                .file
                .sync_all()
                .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        }
        // Recovered complete unacknowledged frames might follow failed sync.
        result
            .file
            .sync_data()
            .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        Ok(result)
    }

    /// One-writer exact compare-and-append. Returning success means sync_data
    /// has returned successfully. After any uncertainty, this handle is
    /// poisoned and must be reopened with external witness reconciliation.
    pub fn commit(
        &mut self,
        expected_predecessor: Digest32,
        tick: &PopulationSparseTickV2,
    ) -> Result<GatedSparseSignalReceiptV3, GatedJournalErrorV3> {
        if self.poisoned {
            return Err(GatedJournalErrorV3::Poisoned);
        }
        if tick.scope_digest != self.scope.scope_digest
            || tick.objective_digest != self.scope.objective_digest
        {
            return Err(GatedJournalErrorV3::ContextMismatch);
        }
        if tick.temporal_drive_q24.len() != self.config.base.temporal_width
            || tick.prediction_q24.len() != self.config.base.activation_width
        {
            return Err(GatedJournalErrorV3::Mechanism(
                GatedSparseErrorV3::InvalidInput,
            ));
        }
        if let Some(index) = tick
            .sequence
            .checked_sub(1)
            .and_then(|seq| usize::try_from(seq).ok())
            && index < self.entries.len()
        {
            let historical_predecessor = if index == 0 {
                Digest32::ZERO
            } else {
                self.entries[index - 1]
            };
            if historical_predecessor != expected_predecessor {
                // Early O(1) rejection for a stale/wrong expected checkpoint.
                // The expensive bounded replay is reserved for a predecessor
                // that could actually identify the submitted historical tick.
                return Err(GatedJournalErrorV3::Conflict);
            }
            // Exact duplicate retries after later commits still return the
            // originally committed receipt. Re-read and re-execute every
            // historical prefix tick, checking every complete frame and
            // checkpoint digest. No unverified digest-only acknowledgement.
            let (stored_tick_digest, receipt) = self.replay_receipt_at(index)?;
            return if stored_tick_digest == Digest32::of_bytes(&encode_tick(tick))
                && receipt.checkpoint_before == expected_predecessor
            {
                Ok(receipt)
            } else {
                Err(GatedJournalErrorV3::Conflict)
            };
        }
        let before = self
            .current
            .as_ref()
            .map_or(Digest32::ZERO, GatedSparseCheckpointV3::digest);
        if before != expected_predecessor {
            return Err(GatedJournalErrorV3::Conflict);
        }
        if self.entries.len() == self.limit {
            return Err(GatedJournalErrorV3::Capacity);
        }
        let (next, receipt) = gated_sparse_tick_v3(&self.config, tick, self.current.as_ref())
            .map_err(GatedJournalErrorV3::Mechanism)?;
        let frame = encode_frame(tick, &receipt);
        let expected_length =
            HEADER_BYTES as u64 + (self.entries.len() as u64) * (frame.len() as u64);
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(GatedJournalErrorV3::Corrupt);
        }
        self.file
            .write_all(&frame)
            .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        self.entries.push(receipt.checkpoint_after);
        self.current = Some(next);
        self.poisoned = false;
        Ok(receipt)
    }

    /// Algorithmic bytes used by the journal's in-memory history digest index.
    /// This excludes Vec capacity, the current checkpoint, OS page cache, and
    /// file-backed storage. It is not a measured process RSS.
    pub fn retained_history_digest_bytes(&self) -> Result<usize, GatedJournalErrorV3> {
        if self.poisoned {
            return Err(GatedJournalErrorV3::Poisoned);
        }
        Ok(self.entries.len() * std::mem::size_of::<Digest32>())
    }

    /// Reconstruct a historical receipt under the owner-held journal lock.
    /// Any I/O/replay inconsistency leaves the owner poisoned. A successful
    /// read unpoisons it, and the public caller still checks exact input and
    /// expected predecessor before acknowledging a duplicate submission.
    fn replay_receipt_at(
        &mut self,
        index: usize,
    ) -> Result<(Digest32, GatedSparseSignalReceiptV3), GatedJournalErrorV3> {
        if index >= self.entries.len() || self.poisoned {
            return Err(GatedJournalErrorV3::Poisoned);
        }
        self.poisoned = true;
        let frame_len = frame_length(&self.config);
        self.file
            .seek(SeekFrom::Start(HEADER_BYTES as u64))
            .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
        let mut bytes = vec![0_u8; frame_len];
        let mut previous = None;
        for frame_index in 0..=index {
            self.file
                .read_exact(&mut bytes)
                .map_err(|_| GatedJournalErrorV3::Indeterminate)?;
            let tick = decode_tick(
                &bytes[..frame_len - FRAME_EXTRA_BYTES],
                self.config.base.temporal_width,
                self.config.base.activation_width,
            )?;
            if tick.scope_digest != self.scope.scope_digest
                || tick.objective_digest != self.scope.objective_digest
            {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            let (next, receipt) = gated_sparse_tick_v3(&self.config, &tick, previous.as_ref())
                .map_err(|_| GatedJournalErrorV3::Corrupt)?;
            if receipt.checkpoint_after != self.entries[frame_index]
                || encode_frame(&tick, &receipt) != bytes
            {
                return Err(GatedJournalErrorV3::Corrupt);
            }
            if frame_index == index {
                self.poisoned = false;
                return Ok((Digest32::of_bytes(&encode_tick(&tick)), receipt));
            }
            previous = Some(next);
        }
        Err(GatedJournalErrorV3::Corrupt)
    }

    pub fn current(&self) -> Result<Option<&GatedSparseCheckpointV3>, GatedJournalErrorV3> {
        if self.poisoned {
            Err(GatedJournalErrorV3::Poisoned)
        } else {
            Ok(self.current.as_ref())
        }
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, GatedJournalErrorV3> {
        if self.poisoned {
            return Err(GatedJournalErrorV3::Poisoned);
        }
        Ok(self.current.as_ref().map(|current| JournalAnchor {
            sequence: current.sequence(),
            checkpoint_digest: current.digest(),
        }))
    }

    pub fn contains_anchor(&self, anchor: JournalAnchor) -> Result<bool, GatedJournalErrorV3> {
        if self.poisoned {
            return Err(GatedJournalErrorV3::Poisoned);
        }
        Ok(self.anchor_at(anchor.sequence) == Some(anchor))
    }

    pub fn remaining_capacity(&self) -> Result<usize, GatedJournalErrorV3> {
        if self.poisoned {
            Err(GatedJournalErrorV3::Poisoned)
        } else {
            Ok(self.limit - self.entries.len())
        }
    }

    fn anchor_at(&self, sequence: u64) -> Option<JournalAnchor> {
        let index = sequence
            .checked_sub(1)
            .and_then(|n| usize::try_from(n).ok())?;
        let checkpoint_digest = *self.entries.get(index)?;
        Some(JournalAnchor {
            sequence,
            checkpoint_digest,
        })
    }
}

fn frame_length(config: &GatedSparseConfigV3) -> usize {
    FIXED_TICK_BYTES
        + 8 * (config.base.temporal_width + config.base.activation_width)
        + FRAME_EXTRA_BYTES
}

fn encode_header(digest: Digest32, scope: JournalScope) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    for value in [digest, scope.scope_digest, scope.objective_digest] {
        bytes.extend_from_slice(value.as_array());
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
}

fn encode_tick(tick: &PopulationSparseTickV2) -> Vec<u8> {
    let mut bytes = Vec::new();
    for digest in [
        tick.scope_digest,
        tick.objective_digest,
        tick.ndu_digest,
        tick.body_digest,
        tick.input_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&tick.sequence.to_be_bytes());
    bytes.extend_from_slice(&tick.monotonic_micros.to_be_bytes());
    for value in tick.temporal_drive_q24.iter().chain(&tick.prediction_q24) {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes
}

fn signal_digest(receipt: &GatedSparseSignalReceiptV3) -> Digest32 {
    let mut bytes = b"hepta.neuron.gated-sparse-journal-signal.q24.v3".to_vec();
    for digest in [
        receipt.config_digest,
        receipt.original_input_digest,
        receipt.checkpoint_before,
        receipt.checkpoint_after,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for values in [&receipt.gate_q24, &receipt.activation_q24] {
        bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    bytes.extend_from_slice(&(receipt.population_candidate_counts.len() as u64).to_be_bytes());
    for count in &receipt.population_candidate_counts {
        bytes.extend_from_slice(&count.to_be_bytes());
    }
    for value in [
        receipt.gate_saturation_count,
        receipt.active_fraction_ppm,
        receipt.projection_count,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
    bytes.push(u8::from(receipt.requires_calibration));
    // This profile MUST deny all authority, unlike future independent owners.
    Digest32::of_bytes(&bytes)
}

fn encode_frame(tick: &PopulationSparseTickV2, receipt: &GatedSparseSignalReceiptV3) -> Vec<u8> {
    let mut bytes = encode_tick(tick);
    for value in [
        receipt.checkpoint_before,
        receipt.checkpoint_after,
        receipt.original_input_digest,
        signal_digest(receipt),
    ] {
        bytes.extend_from_slice(value.as_array());
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
}

fn decode_tick(
    bytes: &[u8],
    temporal_width: usize,
    activation_width: usize,
) -> Result<PopulationSparseTickV2, GatedJournalErrorV3> {
    if bytes.len() != FIXED_TICK_BYTES + 8 * (temporal_width + activation_width) {
        return Err(GatedJournalErrorV3::Corrupt);
    }
    let mut cursor = 0;
    // Scope the decoder closure so its mutable cursor borrow ends before
    // the next decoder; no dummy drop or lint suppression is necessary.
    let (scope_digest, objective_digest, ndu_digest, body_digest, input_digest) = {
        let mut digest = || {
            let mut arr = [0_u8; 32];
            arr.copy_from_slice(&bytes[cursor..cursor + 32]);
            cursor += 32;
            Digest32::from_array(arr)
        };
        (digest(), digest(), digest(), digest(), digest())
    };
    let mut number = || {
        let mut arr = [0_u8; 8];
        arr.copy_from_slice(&bytes[cursor..cursor + 8]);
        cursor += 8;
        u64::from_be_bytes(arr)
    };
    let sequence = number();
    let monotonic_micros = number();
    let temporal_drive_q24 = (0..temporal_width)
        .map(|_| number() as i64)
        .collect::<Vec<_>>();
    let prediction_q24 = (0..activation_width)
        .map(|_| number() as i64)
        .collect::<Vec<_>>();
    Ok(PopulationSparseTickV2 {
        scope_digest,
        objective_digest,
        ndu_digest,
        body_digest,
        input_digest,
        sequence,
        monotonic_micros,
        temporal_drive_q24,
        prediction_q24,
    })
}

#[cfg(test)]
#[path = "gated_journal_v3_tests.rs"]
mod tests;
