//! Checked transport for HIA's command-prefix rule matcher.
//!
//! HIA owns token counts, alternative traversal, byte comparisons and the
//! match decision. This adapter asks HIA to admit the token counts before
//! serializing a complete frame on the stack when it fits, then borrows the
//! buffers and clones the selected prefix.
//! A native contract failure must not become `None`: that would enable the
//! policy layer's unmatched-command heuristics.

use crate::rule::PrefixPattern;
use std::io::Write;

unsafe extern "C" {
    fn codex_hia_prefix_admission(command_count: u64, pattern_count: u64) -> u64;
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
    // SAFETY: the closed scalar ABI accepts two u64 values, retains no state
    // and accesses no caller memory. HIA decides whether a full frame is needed.
    match unsafe { codex_hia_prefix_admission(command.len() as u64, pattern_len as u64) } {
        0 => return None,
        1 => {}
        status => panic!("HIA prefix count admission returned an invalid status: {status}"),
    }
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
    let matched = if capacity <= 512 {
        let mut source = [0_u8; 512];
        let mut remaining = &mut source[..capacity];
        encode_frame(
            &mut remaining,
            pattern,
            commands,
            command.len(),
            pattern_len,
        );
        assert!(remaining.is_empty(), "HIA prefix frame size mismatch");
        match_frame(&source[..capacity])
    } else {
        let mut source = Vec::new();
        source
            .try_reserve_exact(capacity)
            .unwrap_or_else(|error| panic!("HIA prefix frame allocation failed: {error}"));
        encode_frame(&mut source, pattern, commands, command.len(), pattern_len);
        assert_eq!(source.len(), capacity, "HIA prefix frame size mismatch");
        match_frame(&source)
    };
    if matched == 0 {
        return None;
    }
    assert_eq!(matched, pattern_len as u64, "HIA prefix result is invalid");
    let prefix = command
        .get(..pattern_len)
        .unwrap_or_else(|| panic!("HIA prefix matcher returned an out-of-range prefix"));
    Some(prefix.to_vec())
}

fn append_bytes(output: &mut impl Write, bytes: &[u8]) {
    output
        .write_all(bytes)
        .unwrap_or_else(|error| panic!("HIA prefix frame encoding failed: {error}"));
}

fn append_u64(output: &mut impl Write, value: u64) {
    append_bytes(output, &value.to_le_bytes());
}

fn encode_frame(
    output: &mut impl Write,
    pattern: &PrefixPattern,
    commands: &[String],
    command_count: usize,
    pattern_len: usize,
) {
    append_u64(output, command_count as u64);
    append_u64(output, pattern_len as u64);
    append_u64(output, /*value*/ 1);
    append_u64(output, pattern.first.len() as u64);
    append_bytes(output, pattern.first.as_bytes());
    for token in pattern.rest.iter() {
        let alternatives = token.alternatives();
        append_u64(output, alternatives.len() as u64);
        for alternative in alternatives {
            append_u64(output, alternative.len() as u64);
            append_bytes(output, alternative.as_bytes());
        }
    }
    for token in commands {
        append_u64(output, token.len() as u64);
        append_bytes(output, token.as_bytes());
    }
}

fn match_frame(source: &[u8]) -> u64 {
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
    u64::from_le_bytes(output)
}
