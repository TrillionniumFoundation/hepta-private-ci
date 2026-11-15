//! Checked transport for HIA's command-prefix rule matcher.
//!
//! HIA owns token counts, alternative traversal, byte comparisons and the
//! match decision. This adapter only serializes the existing pattern, borrows
//! the buffers for one native call and clones the selected command prefix.
//! A native contract failure must not become `None`: that would enable the
//! policy layer's unmatched-command heuristics.

use crate::rule::PrefixPattern;

unsafe extern "C" {
    fn codex_hia_prefix_match(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(crate) fn matches_prefix(pattern: &PrefixPattern, command: &[String]) -> Option<Vec<String>> {
    let pattern_len = pattern
        .rest
        .len()
        .checked_add(1)
        .unwrap_or_else(|| panic!("HIA prefix pattern length overflow"));
    let commands = &command[..command.len().min(pattern_len)];
    // The first token is Arc<str>, while later alternatives are Strings. Size
    // the exact wire layout without comparing or interpreting any token bytes.
    let mut capacity = 32_usize
        .checked_add(pattern.first.len())
        .unwrap_or_else(|| panic!("HIA prefix frame length overflow"));
    for token in pattern.rest.iter() {
        capacity = capacity
            .checked_add(8)
            .unwrap_or_else(|| panic!("HIA prefix frame length overflow"));
        for alternative in token.alternatives() {
            capacity = capacity
                .checked_add(8)
                .and_then(|size| size.checked_add(alternative.len()))
                .unwrap_or_else(|| panic!("HIA prefix frame length overflow"));
        }
    }
    for token in commands {
        capacity = capacity
            .checked_add(8)
            .and_then(|size| size.checked_add(token.len()))
            .unwrap_or_else(|| panic!("HIA prefix frame length overflow"));
    }
    let mut source = Vec::new();
    source
        .try_reserve_exact(capacity)
        .unwrap_or_else(|error| panic!("HIA prefix frame allocation failed: {error}"));
    source.extend_from_slice(&(command.len() as u64).to_le_bytes());
    source.extend_from_slice(&(pattern_len as u64).to_le_bytes());
    source.extend_from_slice(&1_u64.to_le_bytes());
    source.extend_from_slice(&(pattern.first.len() as u64).to_le_bytes());
    source.extend_from_slice(pattern.first.as_bytes());
    for token in pattern.rest.iter() {
        let alternatives = token.alternatives();
        source.extend_from_slice(&(alternatives.len() as u64).to_le_bytes());
        for alternative in alternatives {
            source.extend_from_slice(&(alternative.len() as u64).to_le_bytes());
            source.extend_from_slice(alternative.as_bytes());
        }
    }
    for token in commands {
        source.extend_from_slice(&(token.len() as u64).to_le_bytes());
        source.extend_from_slice(token.as_bytes());
    }
    assert_eq!(source.len(), capacity, "HIA prefix frame size mismatch");
    let mut output = [0xff_u8; 8];
    let mut workspace = [];
    // SAFETY: all three distinct buffers remain live for the synchronous call;
    // their exact lengths are supplied. The checked HIA program validates the
    // complete frame before writing eight output bytes and retains no pointers.
    let status = unsafe {
        codex_hia_prefix_match(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 8, "HIA prefix matcher rejected the native frame");
    let matched = u64::from_le_bytes(output);
    if matched == 0 {
        return None;
    }
    assert_eq!(matched, pattern_len as u64, "HIA prefix result is invalid");
    let prefix = command
        .get(..pattern_len)
        .unwrap_or_else(|| panic!("HIA prefix matcher returned an out-of-range prefix"));
    Some(prefix.to_vec())
}
