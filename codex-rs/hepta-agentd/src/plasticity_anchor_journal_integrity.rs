//! Authenticate a held anchor journal without trusting its latest footer alone.
//!
//! The retained digest vector has at most one million entries (32 MB of logical
//! digest payload, plus Vec allocation overhead). Reads use a fixed 32 KiB buffer
//! and one fixed frame rather than one file read syscall per complete frame.

use std::fs::File;
use std::io::BufReader;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

use codex_hepta_types::Digest32;

use super::AdaptiveAnchorJournalErrorV1;
use super::FRAME_BYTES;
use super::HEADER_BYTES;
use super::MAX_FILE_BYTES;
use super::MAX_FRAMES;

pub(super) fn verify_file(
    file: &mut File,
    expected_header: &[u8; HEADER_BYTES],
    trusted_frame_digests: &[Digest32],
) -> Result<(), AdaptiveAnchorJournalErrorV1> {
    if trusted_frame_digests.len() > MAX_FRAMES {
        return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
    }
    let expected_length =
        HEADER_BYTES as u64 + FRAME_BYTES as u64 * trusted_frame_digests.len() as u64;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(AdaptiveAnchorJournalErrorV1::NotRegular);
    }
    if expected_length > MAX_FILE_BYTES || metadata.len() != expected_length {
        return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
    }

    file.seek(SeekFrom::Start(0))?;
    {
        let mut reader = BufReader::with_capacity(32 * 1024, &mut *file);
        let mut actual_header = [0_u8; HEADER_BYTES];
        reader.read_exact(&mut actual_header)?;
        if &actual_header != expected_header {
            return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
        }
        let mut frame = [0_u8; FRAME_BYTES];
        for trusted_digest in trusted_frame_digests {
            reader.read_exact(&mut frame)?;
            let digest_offset = FRAME_BYTES - 32;
            if trusted_digest.as_array() != &frame[digest_offset..]
                || Digest32::of_bytes(&frame[..digest_offset]) != *trusted_digest
            {
                return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
            }
        }
        let mut extra_byte = [0_u8; 1];
        if reader.read(&mut extra_byte)? != 0 {
            return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
        }
    }
    if file.metadata()?.len() != expected_length {
        return Err(AdaptiveAnchorJournalErrorV1::Corrupt);
    }
    Ok(())
}
