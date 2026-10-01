//! Verify a live registry against the exact bytes accepted by its owner.
//!
//! The retained frame digests authenticate every historical body; a valid but
//! substituted frame, recomputed checksum, partial image or extra suffix cannot
//! turn a cached receipt into a positive durability observation. Verification
//! streams history with fixed scratch space and never decodes or clones it.
//! Hosts retain the exclusive file-description contract: unrelated concurrent
//! seeking/mutation, path enrollment and storage-domain isolation are external.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::sync::Mutex;

use codex_hepta_types::Digest32;

const MIN_FRAME_BYTES: usize = 8 + 32 + 4 + 32;

pub(crate) enum LiveRegistryIntegrityError {
    Corrupt,
    Poisoned,
    Io(io::ErrorKind),
}

impl From<io::Error> for LiveRegistryIntegrityError {
    fn from(value: io::Error) -> Self {
        if value.kind() == io::ErrorKind::UnexpectedEof {
            Self::Corrupt
        } else {
            Self::Io(value.kind())
        }
    }
}

pub(crate) struct LiveRegistryIntegrity {
    // try_clone shares the original file cursor. The mutex serializes all
    // shared queries; the owning writer requires &mut self and cannot overlap.
    reader: Mutex<File>,
    expected_header: Vec<u8>,
    maximum_frame_bytes: usize,
}

impl LiveRegistryIntegrity {
    pub(crate) fn new(
        file: &File,
        expected_header: Vec<u8>,
        maximum_frame_bytes: usize,
    ) -> io::Result<Self> {
        Ok(Self {
            reader: Mutex::new(file.try_clone()?),
            expected_header,
            maximum_frame_bytes,
        })
    }

    pub(crate) fn verify(
        &self,
        expected_frame_digests: &[Digest32],
        expected_file_bytes: u64,
    ) -> Result<(), LiveRegistryIntegrityError> {
        let mut reader = self
            .reader
            .lock()
            .map_err(|_| LiveRegistryIntegrityError::Poisoned)?;
        if reader.metadata()?.len() != expected_file_bytes {
            return Err(LiveRegistryIntegrityError::Corrupt);
        }
        reader.seek(SeekFrom::Start(0))?;
        let mut header = vec![0_u8; self.expected_header.len()];
        reader.read_exact(&mut header)?;
        if header != self.expected_header {
            return Err(LiveRegistryIntegrityError::Corrupt);
        }
        let mut offset = header.len() as u64;
        for expected_digest in expected_frame_digests {
            let mut length_bytes = [0_u8; 4];
            reader.read_exact(&mut length_bytes)?;
            let frame_bytes = u32::from_be_bytes(length_bytes) as usize;
            if !(MIN_FRAME_BYTES..=self.maximum_frame_bytes).contains(&frame_bytes) {
                return Err(LiveRegistryIntegrityError::Corrupt);
            }
            offset = offset
                .checked_add(4 + frame_bytes as u64)
                .filter(|value| *value <= expected_file_bytes)
                .ok_or(LiveRegistryIntegrityError::Corrupt)?;
            let body_bytes = (frame_bytes - 32) as u64;
            let mut body = (&mut *reader).take(body_bytes);
            let actual_digest = Digest32::of_reader(&mut body, body_bytes)?;
            if body.limit() != 0 || actual_digest != *expected_digest {
                return Err(LiveRegistryIntegrityError::Corrupt);
            }
            let mut footer = [0_u8; 32];
            reader.read_exact(&mut footer)?;
            if footer != expected_digest.into_array() {
                return Err(LiveRegistryIntegrityError::Corrupt);
            }
        }
        let mut extra = [0_u8; 1];
        if offset != expected_file_bytes
            || reader.read(&mut extra)? != 0
            || reader.metadata()?.len() != expected_file_bytes
        {
            return Err(LiveRegistryIntegrityError::Corrupt);
        }
        Ok(())
    }
}
