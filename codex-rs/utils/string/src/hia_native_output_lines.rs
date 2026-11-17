//! Fixed-size, allocation-free transport for the HIA line-count state machine.
//!
//! The complete input is a valid Rust string. Raw byte chunks may split UTF-8
//! scalars or CRLF pairs; HIA carries the LF count and final-byte state.

const HEADER_SIZE: usize = 32;
const STATE_SIZE: usize = 24;
const OUTPUT_SIZE: usize = 32;
const CHUNK_SIZE: usize = 4096;

unsafe extern "C" {
    fn codex_hia_output_lines(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn count_lines(s: &str) -> usize {
    let input = s.as_bytes();
    let mut frame = [0_u8; HEADER_SIZE + CHUNK_SIZE];
    frame[..8].copy_from_slice(&1_u64.to_le_bytes());
    let mut result = [0_u8; OUTPUT_SIZE];
    let mut workspace = [0_u8; 1];
    let mut offset = 0;
    loop {
        let end = offset + (input.len() - offset).min(CHUNK_SIZE);
        let chunk = &input[offset..end];
        frame[HEADER_SIZE..HEADER_SIZE + chunk.len()].copy_from_slice(chunk);
        // SAFETY: the distinct stack buffers remain live for the synchronous
        // call. The advertised input is at most 4128 bytes, output is 32 bytes,
        // and workspace is empty. The entry retains no caller pointers.
        let status = unsafe {
            codex_hia_output_lines(
                frame.as_ptr(),
                (HEADER_SIZE + chunk.len()) as u64,
                result.as_mut_ptr(),
                OUTPUT_SIZE as u64,
                workspace.as_mut_ptr(),
                /*workspace_len*/ 0,
            )
        };
        assert_eq!(status, OUTPUT_SIZE as u64, "HIA line-count call failed");
        offset = end;
        let lf_count = read_word(&result[..8]);
        let seen = read_word(&result[8..16]);
        let last_is_lf = read_word(&result[16..24]);
        let total = read_word(&result[24..]);
        assert!(
            seen == u64::from(offset != 0)
                && last_is_lf <= 1
                && lf_count <= offset as u64
                && total <= offset as u64,
            "HIA line-count returned invalid state"
        );
        assert!(
            (last_is_lf == 0 || lf_count != 0) && (lf_count == 0 || seen != 0),
            "HIA line-count returned inconsistent flags"
        );
        // Validate the returned state without scanning or correcting input.
        // The result used by the caller is the native count, never a fallback.
        let unfinished_line = u64::from(seen == 1 && last_is_lf == 0);
        assert_eq!(
            lf_count.checked_add(unfinished_line),
            Some(total),
            "HIA line-count returned an inconsistent total"
        );
        if offset == input.len() {
            return usize::try_from(total)
                .unwrap_or_else(|_| panic!("HIA line-count exceeds usize"));
        }
        frame[8..HEADER_SIZE].copy_from_slice(&result[..STATE_SIZE]);
    }
}

fn read_word(bytes: &[u8]) -> u64 {
    u64::from_le_bytes(
        bytes
            .try_into()
            .unwrap_or_else(|_| panic!("HIA line-count word length")),
    )
}
