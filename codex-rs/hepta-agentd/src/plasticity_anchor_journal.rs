//! Crash-safe append-only host journal for adaptive proposal registry fences and anchors.
//!
//! This journal is deliberately separate from parameter/topology proposal registries.
//! A host must place it in an independent rollback domain. Complete frames are never
//! rewritten; an incomplete crash tail may be truncated only after every complete
//! predecessor frame has validated.

use std::error::Error as StdError;
use std::fmt;
use std::fs::{File, TryLockError};
use std::io::{Read, Seek, SeekFrom, Write};

use codex_hepta_types::Digest32;

const HEADER_BYTES: usize = 8 + 32 + 32;
const FRAME_BYTES: usize = 1 + 8 + 8 + 32 + 32;
const TAG_FENCE: u8 = 0;
const TAG_ANCHOR: u8 = 1;
const MAX_FRAMES: usize = 1_000_000;
const MAX_FILE_BYTES: u64 = HEADER_BYTES as u64 + (FRAME_BYTES as u64 * MAX_FRAMES as u64);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct AdaptiveAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct AdaptiveAnchorJournalStateV1 {
    pub writer_fence: u64,
    pub anchor: Option<AdaptiveAnchorV1>,
    /// Last committed predecessor retained across a new-generation fence.
    pub previous_anchor: Option<AdaptiveAnchorV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum AdaptiveAnchorJournalErrorV1 {
    Busy,
    NotRegular,
    InvalidScope,
    ScopeMismatch,
    Corrupt,
    FenceOverflow,
    GenerationPending,
    Capacity,
    Io(std::io::ErrorKind),
}
impl fmt::Display for AdaptiveAnchorJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AdaptiveAnchorJournalErrorV1 {}
impl From<std::io::Error> for AdaptiveAnchorJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, AdaptiveAnchorJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(AdaptiveAnchorJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(AdaptiveAnchorJournalErrorV1::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub(crate) struct AdaptiveAnchorJournalV1 {
    file: LockedFile,
    scope: Digest32,
    state: AdaptiveAnchorJournalStateV1,
}

impl AdaptiveAnchorJournalV1 {
    pub(crate) fn open(
        file: File,
        scope: Digest32,
        magic: [u8; 8],
    ) -> Result<Self, AdaptiveAnchorJournalErrorV1> {
        if scope.is_zero() {
            return Err(AdaptiveAnchorJournalErrorV1::InvalidScope);
        }
        let expected_header = encode_header(magic, scope);
        let mut file = LockedFile::acquire(file)?;
        let length = file.0.metadata()?.len();
        if length > MAX_FILE_BYTES {
            return Err(AdaptiveAnchorJournalErrorV1::Capacity);
        }
        if length == 0 {
            file.0.write_all(&expected_header)?;
            file.0.sync_all()?;
        } else {
            if length < HEADER_BYTES as u64 {
                return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
            }
            file.0.seek(SeekFrom::Start(0))?;
            let mut actual = vec![0_u8; HEADER_BYTES];
            file.0.read_exact(&mut actual)?;
            if actual[..8] != magic {
                return Err(AdaptiveAnchorJournalErrorV1::ScopeMismatch);
            }
            if actual != expected_header {
                return Err(AdaptiveAnchorJournalErrorV1::ScopeMismatch);
            }
        }

        let mut state = AdaptiveAnchorJournalStateV1 {
            writer_fence: 0,
            anchor: None,
            previous_anchor: None,
        };
        let physical_len = file.0.metadata()?.len();
        let mut offset = HEADER_BYTES as u64;
        let mut frames = 0_usize;
        while physical_len.saturating_sub(offset) >= FRAME_BYTES as u64 {
            if frames >= MAX_FRAMES {
                return Err(AdaptiveAnchorJournalErrorV1::Capacity);
            }
            file.0.seek(SeekFrom::Start(offset))?;
            let mut frame = [0_u8; FRAME_BYTES];
            file.0.read_exact(&mut frame)?;
            apply_frame(&frame, &mut state)?;
            offset = offset
                .checked_add(FRAME_BYTES as u64)
                .ok_or(AdaptiveAnchorJournalErrorV1::Capacity)?;
            frames += 1;
        }

        // Only an incomplete final frame is repairable. A complete invalid frame
        // has already failed above and remains byte-for-byte available for recovery.
        if offset != physical_len {
            file.0.set_len(offset)?;
            file.0.sync_all()?;
        }
        file.0.sync_data()?;
        Ok(Self { file, scope, state })
    }

    pub(crate) const fn state(&self) -> AdaptiveAnchorJournalStateV1 {
        self.state
    }

    /// Start a new registry generation. Repeated fence issuance while a generation
    /// is still unacknowledged fails closed instead of skipping fence numbers.
    pub(crate) fn issue_new_registry_fence(
        &mut self,
    ) -> Result<u64, AdaptiveAnchorJournalErrorV1> {
        if self.state.writer_fence != 0 && self.state.anchor.is_none() {
            return Err(AdaptiveAnchorJournalErrorV1::GenerationPending);
        }
        let next = self
            .state
            .writer_fence
            .checked_add(1)
            .filter(|value| *value != 0)
            .ok_or(AdaptiveAnchorJournalErrorV1::FenceOverflow)?;
        let frame = encode_frame(TAG_FENCE, next, None);
        append_frame(&mut self.file.0, &frame)?;
        self.state.previous_anchor = self.state.anchor.or(self.state.previous_anchor);
        self.state.writer_fence = next;
        self.state.anchor = None;
        Ok(next)
    }

    pub(crate) fn persist_anchor(
        &mut self,
        scope: Digest32,
        writer_fence: u64,
        anchor: AdaptiveAnchorV1,
    ) -> Result<(), AdaptiveAnchorJournalErrorV1> {
        if scope != self.scope
            || writer_fence == 0
            || writer_fence != self.state.writer_fence
            || anchor.sequence == 0
            || anchor.frame_digest.is_zero()
        {
            return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
        }
        if let Some(current) = self.state.anchor {
            if anchor.sequence < current.sequence
                || (anchor.sequence == current.sequence && anchor != current)
            {
                return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
            }
            if anchor == current {
                return Ok(());
            }
        }
        let frame = encode_frame(TAG_ANCHOR, writer_fence, Some(anchor));
        append_frame(&mut self.file.0, &frame)?;
        self.state.anchor = Some(anchor);
        Ok(())
    }
}

fn encode_header(magic: [u8; 8], scope: Digest32) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(&magic);
    bytes.extend_from_slice(scope.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
}

fn encode_frame(
    tag: u8,
    writer_fence: u64,
    anchor: Option<AdaptiveAnchorV1>,
) -> [u8; FRAME_BYTES] {
    let mut frame = [0_u8; FRAME_BYTES];
    frame[0] = tag;
    frame[1..9].copy_from_slice(&writer_fence.to_be_bytes());
    if let Some(anchor) = anchor {
        frame[9..17].copy_from_slice(&anchor.sequence.to_be_bytes());
        frame[17..49].copy_from_slice(anchor.frame_digest.as_array());
    }
    let checksum = Digest32::of_bytes(&frame[..49]);
    frame[49..81].copy_from_slice(checksum.as_array());
    frame
}

fn apply_frame(
    frame: &[u8; FRAME_BYTES],
    state: &mut AdaptiveAnchorJournalStateV1,
) -> Result<(), AdaptiveAnchorJournalErrorV1> {
    if Digest32::of_bytes(&frame[..49]).as_array() != &frame[49..81] {
        return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
    }
    let fence = u64::from_be_bytes(
        frame[1..9]
            .try_into()
            .map_err(|_| AdaptiveAnchorJournalErrorV1::Corrupt)?,
    );
    let sequence = u64::from_be_bytes(
        frame[9..17]
            .try_into()
            .map_err(|_| AdaptiveAnchorJournalErrorV1::Corrupt)?,
    );
    let digest = Digest32::from_array(
        frame[17..49]
            .try_into()
            .map_err(|_| AdaptiveAnchorJournalErrorV1::Corrupt)?,
    );
    match frame[0] {
        TAG_FENCE => {
            let expected = state
                .writer_fence
                .checked_add(1)
                .filter(|value| *value != 0)
                .ok_or(AdaptiveAnchorJournalErrorV1::FenceOverflow)?;
            if fence != expected || sequence != 0 || !digest.is_zero() {
                return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
            }
            state.previous_anchor = state.anchor.or(state.previous_anchor);
            state.writer_fence = fence;
            state.anchor = None;
        }
        TAG_ANCHOR => {
            if fence == 0
                || fence != state.writer_fence
                || sequence == 0
                || digest.is_zero()
            {
                return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
            }
            let next = AdaptiveAnchorV1 {
                sequence,
                frame_digest: digest,
            };
            if let Some(current) = state.anchor {
                if next.sequence < current.sequence
                    || (next.sequence == current.sequence && next != current)
                {
                    return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
                }
            }
            state.anchor = Some(next);
        }
        _ => return Err(AdaptiveAnchorJournalErrorV1::Corrupt),
    }
    Ok(())
}

fn append_frame(
    file: &mut File,
    frame: &[u8; FRAME_BYTES],
) -> Result<(), AdaptiveAnchorJournalErrorV1> {
    let length = file.metadata()?.len();
    if length
        .checked_add(FRAME_BYTES as u64)
        .is_none_or(|next| next > MAX_FILE_BYTES)
    {
        return Err(AdaptiveAnchorJournalErrorV1::Capacity);
    }
    file.seek(SeekFrom::End(0))?;
    file.write_all(frame)?;
    file.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use tempfile::tempfile;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn journal_preserves_committed_anchor_across_reopen_and_generation_rollover() {
        let file = tempfile().expect("journal");
        let scope = digest(b"scope");
        let magic = *b"HPAJ0001";
        let first = AdaptiveAnchorV1 {
            sequence: 3,
            frame_digest: digest(b"frame:3"),
        };
        {
            let mut journal =
                AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
                    .expect("open");
            assert_eq!(journal.issue_new_registry_fence().expect("fence"), 1);
            journal.persist_anchor(scope, 1, first).expect("anchor");
        }
        {
            let mut journal =
                AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
                    .expect("reopen");
            assert_eq!(journal.state().anchor, Some(first));
            assert_eq!(journal.issue_new_registry_fence().expect("rollover"), 2);
            assert_eq!(journal.state().anchor, None);
            assert_eq!(journal.state().previous_anchor, Some(first));
            assert_eq!(
                journal.issue_new_registry_fence(),
                Err(AdaptiveAnchorJournalErrorV1::GenerationPending)
            );
        }
        let reopened = AdaptiveAnchorJournalV1::open(file, scope, magic).expect("reopen pending");
        assert_eq!(reopened.state().writer_fence, 2);
        assert_eq!(reopened.state().anchor, None);
        assert_eq!(reopened.state().previous_anchor, Some(first));
    }

    #[test]
    fn journal_repairs_only_an_incomplete_crash_tail() {
        let file = tempfile().expect("journal");
        let scope = digest(b"scope");
        let magic = *b"HPAJ0002";
        let anchor = AdaptiveAnchorV1 {
            sequence: 1,
            frame_digest: digest(b"frame"),
        };
        {
            let mut journal =
                AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
                    .expect("open");
            journal.issue_new_registry_fence().expect("fence");
            journal.persist_anchor(scope, 1, anchor).expect("anchor");
        }
        let valid_len = file.metadata().expect("metadata").len();
        {
            let mut append = OpenOptions::new()
                .append(true)
                .open(format!("/proc/self/fd/{}", std::os::fd::AsRawFd::as_raw_fd(&file)))
                .or_else(|_| file.try_clone())
                .expect("append handle");
            append.seek(SeekFrom::End(0)).expect("seek");
            append.write_all(&[TAG_ANCHOR, 0, 0, 0]).expect("tail");
            append.sync_all().expect("sync");
        }
        let reopened = AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
            .expect("reopen");
        assert_eq!(reopened.state().anchor, Some(anchor));
        drop(reopened);
        assert_eq!(file.metadata().expect("metadata").len(), valid_len);
    }

    #[test]
    fn journal_never_discards_a_complete_invalid_frame() {
        let file = tempfile().expect("journal");
        let scope = digest(b"scope");
        let magic = *b"HPAJ0003";
        {
            let journal =
                AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
                    .expect("open");
            drop(journal);
        }
        let mut append = file.try_clone().expect("clone");
        append.seek(SeekFrom::End(0)).expect("seek");
        append.write_all(&[0_u8; FRAME_BYTES]).expect("corrupt frame");
        append.sync_all().expect("sync");
        let length = file.metadata().expect("metadata").len();
        assert_eq!(
            AdaptiveAnchorJournalV1::open(file.try_clone().expect("clone"), scope, magic)
                .err(),
            Some(AdaptiveAnchorJournalErrorV1::Corrupt)
        );
        assert_eq!(file.metadata().expect("metadata").len(), length);
    }
}
