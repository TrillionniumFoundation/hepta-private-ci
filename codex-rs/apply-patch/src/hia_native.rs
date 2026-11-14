//! Wire-only interface to HIA seek. Unicode matching executes in HIA machine code.
use crate::ApplyPatchError;
use crate::ApplyPatchFileUpdateMode;

const BUFFER_LIMIT: usize = 1_048_576;
const OUTPUT_SIZE: usize = 16;

unsafe extern "C" {
    fn codex_hia_seek_sequence(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

/// Encode the wire frame; propagate native errors rather than returning
/// a false "not found", particularly on exceeding the locked buffer bound.
pub(super) fn seek_sequence_checked(
    lines: &[String],
    pattern: &[String],
    start: usize,
    eof: bool,
    update_file_mode: ApplyPatchFileUpdateMode,
) -> Result<Option<usize>, ApplyPatchError> {
    fn frame_error(reason: &str) -> ApplyPatchError {
        ApplyPatchError::ComputeReplacements(format!("HIA seek_sequence: {reason}"))
    }

    let count = lines
        .len()
        .checked_add(pattern.len())
        .ok_or_else(|| frame_error("line count overflow"))?;
    let offset_bytes = count
        .checked_add(1)
        .and_then(|n| n.checked_mul(8))
        .ok_or_else(|| frame_error("offset table overflow"))?;
    let total = lines
        .iter()
        .chain(pattern)
        .try_fold(32usize.checked_add(offset_bytes), |size, line| {
            size.and_then(|n| n.checked_add(line.len()))
        })
        .ok_or_else(|| frame_error("input length overflow"))?;
    if total > BUFFER_LIMIT {
        return Err(frame_error("input exceeds locked 1 MiB source buffer"));
    }

    let mut frame = Vec::with_capacity(total);
    frame.extend_from_slice(&(lines.len() as u64).to_le_bytes());
    frame.extend_from_slice(&(pattern.len() as u64).to_le_bytes());
    frame.extend_from_slice(&(start as u64).to_le_bytes());
    let flags = u64::from(eof)
        | if matches!(
            update_file_mode,
            ApplyPatchFileUpdateMode::PreserveLineEndings
        ) {
            2
        } else {
            0
        };
    frame.extend_from_slice(&flags.to_le_bytes());
    let mut position = 0_u64;
    frame.extend_from_slice(&position.to_le_bytes());
    for line in lines.iter().chain(pattern) {
        position = position
            .checked_add(line.len() as u64)
            .ok_or_else(|| frame_error("offset overflow"))?;
        frame.extend_from_slice(&position.to_le_bytes());
    }
    for line in lines.iter().chain(pattern) {
        frame.extend_from_slice(line.as_bytes());
    }
    if frame.len() != total {
        return Err(frame_error("internal frame length mismatch"));
    }

    let mut result = [0_u8; OUTPUT_SIZE];
    // Selfhost ABI has no pointer/alias admission. The allocations are
    // disjoint and live throughout the synchronous call.
    let mut workspace = [0_u8; 1];
    // SAFETY: frame, result and workspace are independent owned buffers;
    // capacities are valid and at most 1 MiB; workspace length is zero.
    // This native f0 implementation does not retain pointers.
    let status = unsafe {
        codex_hia_seek_sequence(
            frame.as_ptr(),
            frame.len() as u64,
            result.as_mut_ptr(),
            OUTPUT_SIZE as u64,
            workspace.as_mut_ptr(),
            0,
        )
    };
    if status != OUTPUT_SIZE as u64 {
        return Err(frame_error("native ABI rejected the input or output frame"));
    }
    let found = u64::from_le_bytes(
        result[0..8]
            .try_into()
            .map_err(|_| frame_error("invalid output length"))?,
    );
    let index = u64::from_le_bytes(
        result[8..16]
            .try_into()
            .map_err(|_| frame_error("invalid index length"))?,
    );
    match found {
        0 => Ok(None),
        1 => usize::try_from(index)
            .map(Some)
            .map_err(|_| frame_error("native match index overflow")),
        _ => Err(frame_error("invalid native found flag")),
    }
}
