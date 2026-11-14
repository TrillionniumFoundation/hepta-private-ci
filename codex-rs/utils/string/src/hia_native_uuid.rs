//! Borrowed-window transport for HIA's leftmost, non-overlapping UUID matcher.
//!
//! HIA selects candidate positions, checks the exact ASCII pattern, emits the
//! original 36 bytes, and chooses how many source bytes the next call consumes.
//! The return value packs a result tag in the high 16 bits and a consumed byte
//! count in the low 16 bits. Tags are match (1), exhausted (2), and more (3).
//! The workspace's only byte indicates whether this is the final input window.
//! Output and workspace are unchanged for every returned error or non-match.

const CHUNK_SIZE: usize = 4096;
const MATCH_BYTES: usize = 36;

unsafe extern "C" {
    fn codex_hia_uuid_matches(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn find_uuids(source: &str) -> Vec<String> {
    let mut remaining = source.as_bytes();
    let mut output = [0_u8; MATCH_BYTES];
    let mut workspace = [0_u8; 1];
    let mut matches = Vec::new();
    loop {
        let chunk = &remaining[..remaining.len().min(CHUNK_SIZE)];
        let final_window = chunk.len() == remaining.len();
        workspace[0] = u8::from(final_window);
        // SAFETY: the three distinct buffers remain live for the synchronous
        // call. HIA borrows at most CHUNK_SIZE bytes, retains no pointers, and
        // writes MATCH_BYTES ASCII bytes only after validating a complete match.
        let status = unsafe {
            codex_hia_uuid_matches(
                chunk.as_ptr(),
                chunk.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                workspace.as_mut_ptr(),
                workspace.len() as u64,
            )
        };
        let consumed = (status & 0xffff) as usize;
        match status >> 16 {
            1 if (MATCH_BYTES..=chunk.len()).contains(&consumed) => {
                matches.push(
                    String::from_utf8(output.to_vec())
                        .unwrap_or_else(|_| panic!("HIA UUID matcher returned invalid UTF-8")),
                );
            }
            2 if final_window && consumed == chunk.len() => return matches,
            3 if !final_window && consumed > 0 && consumed <= chunk.len() => {}
            _ => panic!("HIA UUID matcher returned an invalid window result"),
        }
        remaining = &remaining[consumed..];
    }
}
