//! Physical observation of an existing original RunStart descriptor.
//!
//! The anchor, profile and optional prefix are external data commitments. This
//! view neither establishes an independent acknowledgement nor authenticates a
//! signature or grants authority. The original owners must do those checks.
//! Complete validated tails may follow the anchor; incomplete tails never pass.
//! Refusal is sticky for this handle, not a persistent or joint-rollback fence.

use std::fs::File;
use std::io;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::sync::Mutex;

use rustix::fs::OFlags;
use rustix::fs::fcntl_getfl;

use super::frames::ReplayedRunStartFrames;
use super::frames::replay_reader;
use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartReadOnlyPublicationV1 {
    pub record: RunStartRecordV1,
    pub publication: RunStartPublication,
}

/// Exact byte positions from the shared parser, including legacy frame sizes.
/// These coordinates and bytes carry no acknowledgement or writer capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartReadOnlyFrameV1 {
    pub observed: RunStartReadOnlyPublicationV1,
    pub frame_start: u64,
    pub frame_end: u64,
    pub observed_length: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileStamp {
    device: u64,
    inode: u64,
    length: u64,
    links: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

#[derive(Default)]
struct ObservationState {
    prefix: Option<(usize, Digest32)>,
    poisoned: bool,
}

enum OriginalPrefix {
    Unspecified,
    Exact { length: u64, digest: Digest32 },
}

/// Data-only Unix reader. It consumes an already existing O_RDONLY descriptor
/// without taking the original writer's flock. It has no create, append,
/// truncate, recovery, repair, signing or writer-trait implementation.
/// Descriptor identity does not prove that a pathname still names this inode.
pub struct ReadOnlyRunStartViewV1 {
    file: File,
    identity: (u64, u64),
    binding: Digest32,
    profile: Digest32,
    max_records: usize,
    anchor: RunStartAnchor,
    state: Mutex<ObservationState>,
}

impl ReadOnlyRunStartViewV1 {
    pub fn open(
        file: File,
        journal_binding: Digest32,
        original_profile_digest: Digest32,
        max_records: usize,
        expected_anchor: RunStartAnchor,
    ) -> Result<Self, RunStartStoreError> {
        validate_domain(journal_binding, max_records)?;
        validate_recovery(RunStartRecovery::Acknowledged(expected_anchor), max_records)?;
        if original_profile_digest.is_zero() {
            return Err(RunStartStoreError::InvalidBinding);
        }
        let stamp = file_stamp(&file)?;
        let view = Self {
            file,
            identity: (stamp.device, stamp.inode),
            binding: journal_binding,
            profile: original_profile_digest,
            max_records,
            anchor: expected_anchor,
            state: Mutex::new(ObservationState::default()),
        };
        view.with_observation(|_, _| Ok(()))?;
        Ok(view)
    }

    /// Absence is not an acknowledgement or proof that admission never occurred.
    pub fn read(
        &self,
        run_id: &StableId,
    ) -> Result<Option<RunStartReadOnlyPublicationV1>, RunStartStoreError> {
        Ok(self.read_with_frame(run_id)?.map(|frame| frame.observed))
    }

    pub fn read_with_frame(
        &self,
        run_id: &StableId,
    ) -> Result<Option<RunStartReadOnlyFrameV1>, RunStartStoreError> {
        self.read_frame(run_id, OriginalPrefix::Unspecified)
    }

    /// Verify the owner's retained prefix and locate the record in the same
    /// physically read image. The owner must separately require a fresh frame
    /// after its actual baseline and retain the original append/sync receipt.
    pub fn read_with_frame_at_original_prefix(
        &self,
        run_id: &StableId,
        prefix_length: u64,
        prefix_digest: Digest32,
    ) -> Result<Option<RunStartReadOnlyFrameV1>, RunStartStoreError> {
        self.read_frame(
            run_id,
            OriginalPrefix::Exact {
                length: prefix_length,
                digest: prefix_digest,
            },
        )
    }

    fn read_frame(
        &self,
        run_id: &StableId,
        prefix: OriginalPrefix,
    ) -> Result<Option<RunStartReadOnlyFrameV1>, RunStartStoreError> {
        self.with_observation(|bytes, replay| {
            if let OriginalPrefix::Exact { length, digest } = prefix {
                let length = usize::try_from(length).map_err(|_| RunStartStoreError::Capacity)?;
                let original = bytes
                    .get(..length)
                    .ok_or(RunStartStoreError::AnchorMismatch)?;
                if Digest32::of_bytes(original) != digest {
                    return Err(RunStartStoreError::AnchorMismatch);
                }
            }
            let Some(index) = replay.by_run.get(run_id).copied() else {
                return Ok(None);
            };
            let stored = replay
                .records
                .get(index)
                .ok_or(RunStartStoreError::Corrupt)?;
            if stored.sequence > self.anchor.sequence {
                return Ok(None);
            }
            if record_profile(&stored.record) != self.profile {
                return Err(RunStartStoreError::BindingMismatch);
            }
            let StoredRunStartRecord::Run(record) = &stored.record else {
                return Ok(None);
            };
            let (frame_start, frame_end) = replay
                .frame_ranges
                .get(index)
                .copied()
                .ok_or(RunStartStoreError::Corrupt)?;
            Ok(Some(RunStartReadOnlyFrameV1 {
                observed: RunStartReadOnlyPublicationV1 {
                    record: record.clone(),
                    publication: RunStartPublication {
                        sequence: stored.sequence,
                        record_digest: stored.record_digest,
                        chain_digest: stored.chain_digest,
                    },
                },
                frame_start,
                frame_end,
                observed_length: replay.observed_length,
            }))
        })
    }

    fn with_observation<T>(
        &self,
        observe: impl FnOnce(&[u8], &ReplayedRunStartFrames) -> Result<T, RunStartStoreError>,
    ) -> Result<T, RunStartStoreError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| RunStartStoreError::Poisoned)?;
        if state.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        let result = (|| {
            let (before, bytes) = self.read_image()?;
            if let Some((length, digest)) = state.prefix
                && bytes.get(..length).map(Digest32::of_bytes) != Some(digest)
            {
                return Err(RunStartStoreError::Indeterminate);
            }
            let replay = replay_reader(
                &mut io::Cursor::new(&bytes),
                self.binding,
                self.max_records,
                before.length,
            )?;
            if replay.valid_length != replay.observed_length {
                return Err(RunStartStoreError::Indeterminate);
            }
            let index = usize::try_from(self.anchor.sequence - 1)
                .map_err(|_| RunStartStoreError::InvalidAnchor)?;
            let anchor = replay
                .records
                .get(index)
                .ok_or(RunStartStoreError::AcknowledgedHistoryMissing)?;
            if anchor.chain_digest != self.anchor.chain_digest {
                return Err(RunStartStoreError::AnchorMismatch);
            }
            if record_profile(&anchor.record) != self.profile {
                return Err(RunStartStoreError::BindingMismatch);
            }
            let value = observe(&bytes, &replay)?;
            let (after, confirmed) = self.read_image()?;
            if before != after || bytes != confirmed {
                return Err(RunStartStoreError::Indeterminate);
            }
            state.prefix = Some((bytes.len(), Digest32::of_bytes(&bytes)));
            Ok(value)
        })();
        if result.is_err() {
            state.poisoned = true;
        }
        result
    }

    fn read_image(&self) -> Result<(FileStamp, Vec<u8>), RunStartStoreError> {
        let before = file_stamp(&self.file)?;
        if (before.device, before.inode) != self.identity {
            return Err(RunStartStoreError::Indeterminate);
        }
        if before.length > MAX_FILE_BYTES {
            return Err(RunStartStoreError::Capacity);
        }
        let length = usize::try_from(before.length).map_err(|_| RunStartStoreError::Capacity)?;
        let mut bytes = vec![0_u8; length];
        self.file
            .read_exact_at(&mut bytes, /*offset*/ 0)
            .map_err(|_| RunStartStoreError::Indeterminate)?;
        if file_stamp(&self.file)? != before {
            return Err(RunStartStoreError::Indeterminate);
        }
        Ok((before, bytes))
    }
}

fn record_profile(record: &StoredRunStartRecord) -> Digest32 {
    match record {
        StoredRunStartRecord::Run(record) => record.admission.profile_digest,
        StoredRunStartRecord::Conflict(record) => record.admission.profile_digest,
    }
}

fn file_stamp(file: &File) -> Result<FileStamp, RunStartStoreError> {
    let flags = fcntl_getfl(file).map_err(io::Error::from)?;
    if flags & OFlags::ACCMODE != OFlags::RDONLY {
        return Err(RunStartStoreError::InvalidSnapshot(
            "existing O_RDONLY descriptor required",
        ));
    }
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(RunStartStoreError::NotRegular);
    }
    Ok(FileStamp {
        device: metadata.dev(),
        inode: metadata.ino(),
        length: metadata.len(),
        links: metadata.nlink(),
        modified: (metadata.mtime(), metadata.mtime_nsec()),
        changed: (metadata.ctime(), metadata.ctime_nsec()),
    })
}
