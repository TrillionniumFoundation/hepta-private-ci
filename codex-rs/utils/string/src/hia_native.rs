//! Constant-size transport for HIA UTF-8 prefix selection on valid Rust strings.
//!
//! Rust's `&str` already guarantees UTF-8. At most three continuation bytes
//! precede the requested boundary, so the HIA owner only needs a four-byte
//! window. This preserves the borrowed API without allocating or imposing the
//! development byte-frame profile's 1 MiB limit on the original string.

const HEADER_SIZE: usize = 24;
const MAX_WINDOW_SIZE: usize = 4;
const OUTPUT_SIZE: usize = 8;

unsafe extern "C" {
    fn codex_hia_utf8_prefix(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn take_bytes_at_char_boundary(s: &str, maxb: usize) -> &str {
    // Select raw bytes for transport; HIA owns the budget and boundary result.
    let position = maxb.min(s.len());
    let window_start = position.saturating_sub(3);
    let window_end = position.saturating_add(1).min(s.len());
    let window = &s.as_bytes()[window_start..window_end];
    let mut frame = [0_u8; HEADER_SIZE + MAX_WINDOW_SIZE];
    frame[..8].copy_from_slice(&(s.len() as u64).to_le_bytes());
    frame[8..16].copy_from_slice(&(maxb as u64).to_le_bytes());
    frame[16..24].copy_from_slice(&(window_start as u64).to_le_bytes());
    frame[HEADER_SIZE..HEADER_SIZE + window.len()].copy_from_slice(window);
    let mut result = [0_u8; OUTPUT_SIZE];
    let mut workspace = [0_u8; 1];
    // SAFETY: these distinct stack allocations remain live throughout the
    // synchronous call. The frame is at most 28 bytes, result is eight bytes,
    // and workspace length is zero. The HIA entry retains no caller pointers.
    let status = unsafe {
        codex_hia_utf8_prefix(
            frame.as_ptr(),
            (HEADER_SIZE + window.len()) as u64,
            result.as_mut_ptr(),
            OUTPUT_SIZE as u64,
            workspace.as_mut_ptr(),
            /*workspace_len*/ 0,
        )
    };
    assert_eq!(status, OUTPUT_SIZE as u64, "HIA UTF-8 prefix call failed");
    let offset = match usize::try_from(u64::from_le_bytes(result)) {
        Ok(offset) if offset <= position && position - offset <= 3 => offset,
        _ => panic!("HIA UTF-8 prefix returned an invalid byte offset"),
    };
    match s.get(..offset) {
        Some(prefix) => prefix,
        None => panic!("HIA UTF-8 prefix returned an invalid string boundary"),
    }
}
