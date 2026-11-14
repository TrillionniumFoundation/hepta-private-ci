//! Bounded transport for HIA metric-tag sanitization of valid Rust strings.
//!
//! HIA owns character mapping, trimming, fallback and truncation. The input is
//! borrowed in byte chunks that may split a UTF-8 character; HIA processes its
//! leading byte once and ignores its continuation bytes in subsequent chunks.
//! Each call retains only the bounded result and the HIA-owned streaming state.

const CHUNK_SIZE: usize = 1_048_576;
const OUTPUT_SIZE: usize = 256;
const WORKSPACE_SIZE: usize = 32;
const FINAL_CHUNK_OFFSET: usize = 24;

unsafe extern "C" {
    fn codex_hia_metric_tag(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn sanitize_metric_tag_value(value: &str) -> String {
    let mut remaining = value.as_bytes();
    let mut output = [0_u8; OUTPUT_SIZE];
    let mut workspace = [0_u8; WORKSPACE_SIZE];
    loop {
        let (chunk, rest) = remaining.split_at(remaining.len().min(CHUNK_SIZE));
        workspace[FINAL_CHUNK_OFFSET] = u8::from(rest.is_empty());
        // SAFETY: the borrowed input and the distinct output/state allocations
        // remain live for this synchronous call. All three passed extents are
        // bounded by their allocations; HIA retains no pointers. The complete
        // input is valid UTF-8 even when an individual chunk splits a character.
        let status = unsafe {
            codex_hia_metric_tag(
                chunk.as_ptr(),
                chunk.len() as u64,
                output.as_mut_ptr(),
                OUTPUT_SIZE as u64,
                workspace.as_mut_ptr(),
                WORKSPACE_SIZE as u64,
            )
        };
        if rest.is_empty() {
            let length = match usize::try_from(status) {
                Ok(length) if (1..=OUTPUT_SIZE).contains(&length) => length,
                _ => panic!("HIA metric tag returned an invalid result length"),
            };
            return match String::from_utf8(output[..length].to_vec()) {
                Ok(result) => result,
                Err(_) => panic!("HIA metric tag returned invalid UTF-8"),
            };
        }
        assert_eq!(status, 0, "HIA metric tag rejected a nonfinal chunk");
        remaining = rest;
    }
}
