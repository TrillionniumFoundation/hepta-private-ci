//! Checked transport for the complete HIA RuleMatch result reduction.
//!
//! HIA selects the strictest decision and whether any match is explicit.
//! Rust retains every original RuleMatch and the caller's empty-result contract.

use crate::Decision;
use crate::RuleMatch;
use std::io::Write;

pub(crate) struct Summary {
    pub(crate) decision: Option<Decision>,
    pub(crate) has_explicit_match: bool,
}

unsafe extern "C" {
    fn codex_hia_policy_summary(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

pub(crate) fn summarize(matches: &[RuleMatch]) -> Summary {
    let capacity = matches
        .len()
        .checked_mul(16)
        .and_then(|bytes| bytes.checked_add(8))
        .unwrap_or_else(|| panic!("HIA policy summary frame length overflow"));
    if capacity <= 512 {
        let mut source = [0_u8; 512];
        let mut remaining = &mut source[..capacity];
        encode(&mut remaining, matches);
        assert!(
            remaining.is_empty(),
            "HIA policy summary frame size mismatch"
        );
        invoke(&source[..capacity])
    } else {
        let mut source = Vec::new();
        source
            .try_reserve_exact(capacity)
            .unwrap_or_else(|error| panic!("HIA policy summary allocation failed: {error}"));
        encode(&mut source, matches);
        assert_eq!(
            source.len(),
            capacity,
            "HIA policy summary frame size mismatch"
        );
        invoke(&source)
    }
}

fn append_word(output: &mut impl Write, value: u64) {
    output
        .write_all(&value.to_le_bytes())
        .unwrap_or_else(|error| panic!("HIA policy summary encoding failed: {error}"));
}

fn encode(output: &mut impl Write, matches: &[RuleMatch]) {
    append_word(output, matches.len() as u64);
    for matched in matches {
        let (kind, decision) = match matched {
            RuleMatch::PrefixRuleMatch { decision, .. } => (0, decision),
            RuleMatch::HeuristicsRuleMatch { decision, .. } => (1, decision),
        };
        let tag = match decision {
            Decision::Allow => 0,
            Decision::Prompt => 1,
            Decision::Forbidden => 2,
        };
        append_word(output, kind);
        append_word(output, tag);
    }
}

fn invoke(source: &[u8]) -> Summary {
    let mut output = [u64::MAX; 3];
    let mut workspace = [];
    // SAFETY: the three disjoint buffers stay live for the synchronous call.
    // HIA receives their exact extents and cannot retain their addresses.
    let status = unsafe {
        codex_hia_policy_summary(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr().cast(),
            std::mem::size_of_val(&output) as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 24, "HIA policy summary rejected the native frame");
    let [present, tag, explicit] = output.map(u64::from_le);
    let has_explicit_match = match explicit {
        0 => false,
        1 => true,
        _ => panic!("HIA policy summary returned an invalid match flag"),
    };
    let decision = match present {
        0 => {
            assert_eq!(
                tag, 0,
                "HIA policy summary returned a nonempty empty result"
            );
            assert!(
                !has_explicit_match,
                "HIA policy summary returned an empty explicit match"
            );
            None
        }
        1 => Some(match tag {
            0 => Decision::Allow,
            1 => Decision::Prompt,
            2 => Decision::Forbidden,
            _ => panic!("HIA policy summary returned an invalid decision"),
        }),
        _ => panic!("HIA policy summary returned an invalid presence flag"),
    };
    Summary {
        decision,
        has_explicit_match,
    }
}
