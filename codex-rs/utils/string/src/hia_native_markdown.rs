//! Bounded transport for HIA's markdown location suffix state machine.
//!
//! The input is a valid Rust string, borrowed in byte frames that may split a
//! Unicode scalar. HIA owns marker recognition, replacement, and rejection;
//! Rust gathers emitted bytes and checks UTF-8 only after the whole result.
//! Workspace byte 0 is HIA-owned phase (0 initially, 7 after final success).
//! Byte 1 requests finalization. A success returns this frame's output length,
//! including zero for an empty final frame; errors leave output/state unchanged.

const CHUNK_SIZE: usize = 4096;
const INVALID_FORMAT: u64 = 0xffff_fffd;

unsafe extern "C" {
    fn codex_hia_markdown_location(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn normalize_markdown_hash_location_suffix(suffix: &str) -> Option<String> {
    let mut remaining = suffix.as_bytes();
    let mut output = [0_u8; CHUNK_SIZE];
    let mut workspace = [0_u8; 2];
    let mut result = Vec::new();
    loop {
        let (chunk, rest) = remaining.split_at(remaining.len().min(CHUNK_SIZE));
        workspace[1] = u8::from(rest.is_empty());
        // SAFETY: all three buffers are distinct and live for this synchronous
        // call. The input is borrowed without copying, the output has room for
        // every input byte, and the complete string is valid UTF-8. HIA retains
        // no pointers and commits output/state only after validating the frame.
        let status = unsafe {
            codex_hia_markdown_location(
                chunk.as_ptr(),
                chunk.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                workspace.as_mut_ptr(),
                workspace.len() as u64,
            )
        };
        if status == INVALID_FORMAT {
            return None;
        }
        let length = match usize::try_from(status) {
            Ok(length) if length <= chunk.len() => length,
            _ => panic!("HIA markdown location returned an invalid result length"),
        };
        result.extend_from_slice(&output[..length]);
        if rest.is_empty() {
            return Some(
                String::from_utf8(result)
                    .unwrap_or_else(|_| panic!("HIA markdown location returned invalid UTF-8")),
            );
        }
        remaining = rest;
    }
}
