//! Strict read-only CURRENT on the original locked Cell journal descriptor.
//!
//! This does not recover, truncate, sync, reconcile witnesses, or reopen a
//! path. It is a point-in-time check against this retained owner and witness;
//! coordinated rollback of both remains outside this local observation.

use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

use codex_hepta_types::Digest32;

use super::CellGenerationJournalV2;
use super::HEADER_BYTES;
use super::MAX_BYTES;
use super::MAX_FRAME;
use super::continuity_checkpoint;
use super::next_anchor;
use crate::AnchorWitnessStore;
use crate::CellGenerationErrorV2;
use crate::JournalAnchor;
use crate::cell_generation_state::GenerationEvent;
use crate::cell_generation_state::GenerationState;

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Validate every physical frame and the resulting state against this same
    /// retained owner. Preserve the original cursor and append lock on success
    /// and failure. An error permanently fences this instance, including its
    /// ordinary recovery method; restoring bytes cannot rearm it.
    pub fn read_current_checkpoint(&mut self) -> Result<Digest32, CellGenerationErrorV2> {
        let result = self.read_physical_current();
        if result.is_err() {
            self.physical_fenced = true;
            self.healthy = false;
        }
        result
    }

    fn read_physical_current(&mut self) -> Result<Digest32, CellGenerationErrorV2> {
        self.require_healthy()?;
        let before = self
            .witness
            .current()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if before != self.head {
            return Err(CellGenerationErrorV2::AcknowledgedHistoryMissing);
        }
        let position = self
            .file
            .stream_position()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let observed = self.read_physical_frames();
        let restored = self
            .file
            .seek(SeekFrom::Start(position))
            .map_err(|_| CellGenerationErrorV2::Unavailable);
        restored?;
        let checkpoint = observed?;
        let after = self
            .witness
            .current()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if after != before || after != self.head {
            return Err(CellGenerationErrorV2::AcknowledgedHistoryMissing);
        }
        self.require_current()?;
        Ok(checkpoint)
    }

    fn read_physical_frames(&mut self) -> Result<Digest32, CellGenerationErrorV2> {
        let length = self
            .file
            .metadata()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?
            .len();
        if length != self.length || !(HEADER_BYTES as u64..=MAX_BYTES).contains(&length) {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        self.file
            .seek(SeekFrom::Start(0))
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut bytes = Vec::with_capacity(length as usize);
        Read::take(&mut *self.file, length + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if bytes.len() as u64 != length
            || self
                .file
                .metadata()
                .map_err(|_| CellGenerationErrorV2::Unavailable)?
                .len()
                != length
        {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        if bytes[..HEADER_BYTES] != self.header {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut state = GenerationState::new(&self.config)?;
        let mut head = None;
        let mut offset = HEADER_BYTES;
        while offset < bytes.len() {
            let prefix = bytes
                .get(offset..offset + 4)
                .ok_or(CellGenerationErrorV2::Corrupt)?;
            let size = u32::from_be_bytes(
                prefix
                    .try_into()
                    .map_err(|_| CellGenerationErrorV2::Corrupt)?,
            ) as usize;
            if size == 0 || size > MAX_FRAME {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            let end = offset
                .checked_add(size + 36)
                .filter(|end| *end <= bytes.len())
                .ok_or(CellGenerationErrorV2::Corrupt)?;
            let payload = &bytes[offset + 4..end - 32];
            let (next, event) = decode_frame(
                &self.header,
                head,
                payload,
                &bytes[end - 32..end],
                self.max_records,
            )?;
            state.apply(&self.config, &event)?;
            head = Some(next);
            offset = end;
        }
        if state != self.state || head != self.head || offset as u64 != self.length {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        Ok(continuity_checkpoint(&self.header, head, offset as u64))
    }
}

/// The canonical frame validation shared by strict CURRENT and the existing
/// recovery parser. The caller chooses whether an incomplete tail is an error;
/// this function never repairs it or changes the witness.
pub(super) fn decode_frame(
    header: &[u8],
    previous: Option<JournalAnchor>,
    payload: &[u8],
    checksum: &[u8],
    max_records: u64,
) -> Result<(JournalAnchor, GenerationEvent), CellGenerationErrorV2> {
    let next = next_anchor(header, previous, payload)?;
    if next.sequence > max_records || next.checkpoint_digest.as_array() != checksum {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    let event: GenerationEvent =
        serde_json::from_slice(payload).map_err(|_| CellGenerationErrorV2::Corrupt)?;
    if serde_json::to_vec(&event).map_err(|_| CellGenerationErrorV2::Corrupt)? != payload {
        return Err(CellGenerationErrorV2::Corrupt);
    }
    Ok((next, event))
}
