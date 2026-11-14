//! Borrowed-buffer ABI to the HIA-native UTF-8 boundary algorithm.
//! All scanning and boundary selection execute in HIA-produced machine code.

const SOURCE_LIMIT: usize = 1_048_576;
const HEADER_SIZE: usize = 8;
const OUTPUT_SIZE: usize = 8;

unsafe extern "C" {
    fn codex_hia_utf8_boundaries(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

/// Preserve the public borrowed `&str` result; the HIA machine code owns the decision.
/// Reject inputs outside the native profile instead of quietly using a Rust path.
#[inline]
pub fn take_bytes_at_char_boundary(s: &str, maxb: usize) -> &str {
    let wire_size = s
        .len()
        .checked_add(HEADER_SIZE)
        .expect("HIA UTF-8 wire length overflow");
    assert!(
        wire_size <= SOURCE_LIMIT,
        "HIA UTF-8 input exceeds locked 1 MiB source buffer"
    );
    let mut source = Vec::with_capacity(wire_size);
    source.extend_from_slice(&(maxb as u64).to_le_bytes());
    source.extend_from_slice(s.as_bytes());
    let mut output = [0_u8; OUTPUT_SIZE];
    let mut workspace = [0_u8; 1];
    // SAFETY: owned live disjoint buffers; lengths are bounded by the native
    // profile; no pointer is retained and zero workspace bytes are accessed.
    let status = unsafe {
        codex_hia_utf8_boundaries(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            OUTPUT_SIZE as u64,
            workspace.as_mut_ptr(),
            0,
        )
    };
    assert_eq!(
        status, OUTPUT_SIZE as u64,
        "HIA UTF-8 native ABI rejected call"
    );
    let end =
        usize::try_from(u64::from_le_bytes(output)).expect("HIA UTF-8 result is not a valid usize");
    assert!(
        end <= s.len() && end <= maxb && s.is_char_boundary(end),
        "HIA UTF-8 result violates the Rust borrowed-slice contract"
    );
    &s[..end]
}

#[cfg(test)]
#[path = "hia_native_tests.rs"]
mod tests;
