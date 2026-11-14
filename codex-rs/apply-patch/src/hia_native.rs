//! Wire-only interface to HIA seek. Unicode matching executes in HIA machine code.
use crate::ApplyPatchError;
use crate::ApplyPatchFileUpdateMode;

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

/// Encode the wire frame and propagate allocation or native ABI errors.
/// The selfhost ELF accepts the live buffer length. The compiler's 1 MiB
/// bootstrap workspace is not a limit on the file being patched.
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
    let header_size = 32usize
        .checked_add(offset_bytes)
        .ok_or_else(|| frame_error("header length overflow"))?;
    let total = lines
        .iter()
        .chain(pattern)
        .try_fold(header_size, |size, line| size.checked_add(line.len()))
        .ok_or_else(|| frame_error("input length overflow"))?;

    let mut frame = Vec::new();
    frame
        .try_reserve_exact(total)
        .map_err(|_| frame_error("cannot allocate input frame"))?;
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
    // capacities are valid; checked arithmetic and try_reserve_exact keep
    // the frame addressable. Workspace length is zero. The pinned selfhost
    // implementation does not retain pointers or assume a fixed input size.
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
    match (found, index) {
        (0, 0) => Ok(None),
        (1, index) => {
            let index =
                usize::try_from(index).map_err(|_| frame_error("native match index overflow"))?;
            let valid = if pattern.is_empty() {
                index == start
            } else {
                let ignores_start =
                    eof && matches!(update_file_mode, ApplyPatchFileUpdateMode::NormalizeToLf);
                index
                    .checked_add(pattern.len())
                    .is_some_and(|end| end <= lines.len())
                    && (ignores_start || index >= start)
            };
            if !valid {
                return Err(frame_error("native match index outside the input range"));
            }
            Ok(Some(index))
        }
        _ => Err(frame_error("invalid native result frame")),
    }
}
