//! Same-owner checkpoint segments. The independently retained witness chooses
//! the current segment; a prepared file alone can never replace acknowledged
//! history. Old segment bytes remain with the host for its archive policy.

use serde::Deserialize;
use serde::Serialize;

use super::*;

const CHECKPOINT_MAGIC: &[u8; 8] = b"HPTACG03";
const MAX_CHECKPOINT: usize = 32 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationCheckpointReceiptV2 {
    pub archived_digest: [u8; 32],
    pub archived_bytes: u64,
    pub archived_records: u64,
    pub checkpoint_sequence: u64,
    pub checkpoint_digest: [u8; 32],
    pub retained_bytes: u64,
}

/// Observations of this owner, not measured model throughput or an admission
/// grant. Recovery duration measures only the last successful local replay.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationJournalMetricsV2 {
    pub retained_bytes: u64,
    pub byte_limit: u64,
    pub segment_records: u64,
    pub lifetime_sequence: u64,
    pub record_limit: u64,
    pub reserved_records: u64,
    pub retained_receipts: usize,
    pub outbox_bytes: usize,
    pub pending_age_micros: Option<u64>,
    pub queue_age_micros: Option<u64>,
    pub dispatch_observed: bool,
    pub cancelled: bool,
    pub draining: bool,
    pub replay_records: u64,
    pub replay_elapsed_micros: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct GenerationCheckpoint {
    owner_header_digest: [u8; 32],
    predecessor: Option<(u64, [u8; 32])>,
    archived_digest: [u8; 32],
    state: GenerationState,
}

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Compact into a fresh host-retained file while holding the same witness.
    /// The old file is left byte-for-byte intact; its lock is released only
    /// after the successor is synced and witnessed. The host must durably
    /// retain the successor pathname before calling and reopen it after an
    /// uncertain switch; a File handle alone cannot sync its parent directory.
    ///
    /// All operation receipts, costs, pending admissions and undelivered output
    /// survive. This reclaims segment records/replay work, not the independent
    /// receipt, prefix, cost or witness limits. It never resubmits computation.
    pub fn checkpoint_to(
        &mut self,
        successor: File,
    ) -> Result<CellGenerationCheckpointReceiptV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        // Validate the exact archived cut before replacing full replay with its
        // state. A checkpoint must not hide corruption in acknowledged history.
        self.recover()?;
        self.install_checkpoint(successor, self.config.clone(), self.state.clone())
    }

    pub(super) fn install_checkpoint(
        &mut self,
        successor: File,
        config: CellGenerationConfigV2,
        state: GenerationState,
    ) -> Result<CellGenerationCheckpointReceiptV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        let header = owner_header(&config, self.max_records)?;
        let reserved = state.reserved_records();
        let mut successor =
            LockedFile::acquire(successor).map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if successor
            .metadata()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?
            .len()
            != 0
        {
            return Err(CellGenerationErrorV2::Conflict);
        }
        let mut archived = vec![0; self.length as usize];
        self.file
            .seek(SeekFrom::Start(0))
            .and_then(|_| self.file.read_exact(&mut archived))
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let archived_digest = Digest32::of_bytes(&archived).into_array();
        let checkpoint = GenerationCheckpoint {
            owner_header_digest: Digest32::of_bytes(&header).into_array(),
            predecessor: self
                .head
                .map(|anchor| (anchor.sequence, anchor.checkpoint_digest.into_array())),
            archived_digest,
            state,
        };
        let payload =
            serde_json::to_vec(&checkpoint).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let next = next_anchor(&header, self.head, &payload)?;
        let length = HEADER_BYTES as u64 + payload.len() as u64 + 36;
        if payload.len() > MAX_CHECKPOINT
            || reserved > self.max_records
            || length + reserved * (MAX_FRAME as u64 + 36) > MAX_BYTES
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let mut bytes = header.clone();
        bytes[..8].copy_from_slice(CHECKPOINT_MAGIC);
        bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&payload);
        bytes.extend_from_slice(next.checkpoint_digest.as_array());
        successor
            .seek(SeekFrom::Start(0))
            .and_then(|_| successor.write_all(&bytes))
            .and_then(|_| successor.sync_all())
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        let receipt = CellGenerationCheckpointReceiptV2 {
            archived_digest,
            archived_bytes: self.length,
            archived_records: self.head.map_or(0, |anchor| anchor.sequence) - self.base_sequence,
            checkpoint_sequence: next.sequence,
            checkpoint_digest: next.checkpoint_digest.into_array(),
            retained_bytes: length,
        };
        self.healthy = false;
        self.witness
            .compare_and_swap(self.head, next)
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        self.file = successor;
        self.config = config;
        self.state = checkpoint.state;
        self.header = header;
        self.head = Some(next);
        self.base_sequence = next.sequence;
        self.length = length;
        self.healthy = true;
        Ok(receipt)
    }

    /// Inspect the original admitted request through its existing worker port.
    /// Missing or errored readback keeps the admission and reserved capacity.
    /// A known proposal settles through the normal cancellation/deadline and
    /// cost checks using a post-read clock sample. Clock rollback retains the
    /// admission. This never calls execute or invents a failed result.
    pub fn reconcile_pending(
        &mut self,
        control: &mut impl CellGenerationControlPortV2,
        mut clock: impl FnMut() -> u64,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        let Some(request) = self.state.pending.as_ref() else {
            return Ok(None);
        };
        let request_digest = request.digest()?;
        let before_read = clock();
        if before_read < self.state.last_observed_micros {
            return Err(CellGenerationErrorV2::Deadline);
        }
        let proposal = control.read_generation(request);
        let after_read = clock();
        if after_read < before_read {
            return Err(CellGenerationErrorV2::Deadline);
        }
        let Some(proposal) = proposal? else {
            return Ok(None);
        };
        if proposal.request_digest != request_digest {
            return Err(CellGenerationErrorV2::Conflict);
        }
        self.commit(proposal, after_read).map(Some)
    }

    pub fn journal_metrics(
        &self,
        now_micros: u64,
    ) -> Result<CellGenerationJournalMetricsV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        if now_micros < self.state.last_observed_micros {
            return Err(CellGenerationErrorV2::Deadline);
        }
        let pending_age_micros = self
            .state
            .pending
            .as_ref()
            .map(|request| now_micros - request.admitted_at_micros);
        let lifetime_sequence = self.head.map_or(0, |anchor| anchor.sequence);
        Ok(CellGenerationJournalMetricsV2 {
            retained_bytes: self.length,
            byte_limit: MAX_BYTES,
            segment_records: lifetime_sequence - self.base_sequence,
            lifetime_sequence,
            record_limit: self.max_records,
            reserved_records: self.state.reserved_records(),
            retained_receipts: self.state.receipts.len(),
            outbox_bytes: self
                .state
                .outbox
                .as_ref()
                .map_or(0, |chunk| chunk.bytes.len()),
            pending_age_micros,
            queue_age_micros: if self.state.dispatch_observed {
                None
            } else {
                pending_age_micros
            },
            dispatch_observed: self.state.dispatch_observed,
            cancelled: self.state.cancelled,
            draining: self.state.draining,
            replay_records: self.replay_records,
            replay_elapsed_micros: self.replay_elapsed_micros,
        })
    }
}

pub(super) fn recover_checkpoint(
    bytes: &[u8],
    header: &[u8],
    config: &CellGenerationConfigV2,
) -> Result<(GenerationState, usize, Option<JournalAnchor>), CellGenerationErrorV2> {
    if bytes[..HEADER_BYTES] == *header {
        return Ok((GenerationState::new(config)?, HEADER_BYTES, None));
    }
    if &bytes[..8] != CHECKPOINT_MAGIC || bytes[8..HEADER_BYTES] != header[8..] {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    if bytes.len() < HEADER_BYTES + 4 {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let size = u32::from_be_bytes(
        bytes[HEADER_BYTES..HEADER_BYTES + 4]
            .try_into()
            .map_err(|_| CellGenerationErrorV2::Corrupt)?,
    ) as usize;
    let end = HEADER_BYTES + size + 36;
    if size == 0 || size > MAX_CHECKPOINT || end > bytes.len() {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let payload = &bytes[HEADER_BYTES + 4..end - 32];
    let checkpoint: GenerationCheckpoint =
        serde_json::from_slice(payload).map_err(|_| CellGenerationErrorV2::Corrupt)?;
    if checkpoint.owner_header_digest != Digest32::of_bytes(header).into_array()
        || serde_json::to_vec(&checkpoint).map_err(|_| CellGenerationErrorV2::Corrupt)? != payload
    {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let previous = checkpoint
        .predecessor
        .map(|(sequence, checkpoint_digest)| JournalAnchor {
            sequence,
            checkpoint_digest: Digest32::from_array(checkpoint_digest),
        });
    let anchor = next_anchor(header, previous, payload)?;
    if anchor.checkpoint_digest.as_array() != &bytes[end - 32..end] {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    checkpoint.state.snapshot.digest()?;
    checkpoint
        .state
        .cost
        .validate()
        .map_err(|_| CellGenerationErrorV2::Corrupt)?;
    if checkpoint.state.snapshot.manifest_digest != config.manifest.digest()?
        || checkpoint.state.snapshot.scope != config.initial.scope
        || checkpoint.state.snapshot.generation != config.initial.generation
        || checkpoint.state.snapshot.writer_epoch != config.initial.writer_epoch
        || checkpoint.state.cost.identity().task_digest != config.task_digest
        || checkpoint.state.cost.identity().source_digest != config.manifest.source_digest
        || checkpoint.state.receipts.len() > 256
        || checkpoint.state.acknowledgements.len() > 256
        || checkpoint.state.intents.len() != checkpoint.state.receipts.len()
    {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    // Compaction replaces event replay, which normally derives these facts
    // together. Retain the same receipt/intent order and first adopted input;
    // cancelled or failed work cannot become initialization evidence on reopen.
    let mut first_advance_input_digest = None;
    for (receipt, intent) in checkpoint
        .state
        .receipts
        .iter()
        .zip(&checkpoint.state.intents)
    {
        if intent.operation_id != receipt.operation_id
            || intent.task_digest != config.task_digest
            || intent.source_frontier != config.source_frontier
        {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        if matches!(
            receipt.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ) {
            first_advance_input_digest.get_or_insert(intent.input_digest);
        }
    }
    if checkpoint.state.first_advance_input_digest != first_advance_input_digest {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    Ok((checkpoint.state, end, Some(anchor)))
}

#[cfg(test)]
#[path = "cell_generation_lifecycle_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "cell_generation_checkpoint_recovery_tests.rs"]
mod checkpoint_recovery_tests;
