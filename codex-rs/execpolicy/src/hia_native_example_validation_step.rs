//! HIA-driven continuation for execpolicy example-validation callbacks.
//! Rust retains dynamic matching, borrowed RuleMatch lifetimes, shlex rendering,
//! original rule Debug and error locations. Never precompute later callbacks.

use crate::MatchOptions;
use crate::Policy;
use crate::error::Error;
use crate::error::Result;
use crate::rule::RuleRef;
use shlex::try_join;

unsafe extern "C" {
    fn codex_hia_example_validation_step(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

#[derive(Clone, Copy)]
struct Response {
    opcode: u64,
    index: u64,
    unmatched: u64,
    append: u64,
    phase: u64,
}

fn word(data: &[u8], at: usize) -> u64 {
    let end = at
        .checked_add(8)
        .unwrap_or_else(|| panic!("HIA example-validation word offset overflow"));
    let bytes: [u8; 8] = data
        .get(at..end)
        .and_then(|value| value.try_into().ok())
        .unwrap_or_else(|| panic!("HIA example-validation response is truncated"));
    u64::from_le_bytes(bytes)
}

fn to_word(value: usize, field: &str) -> u64 {
    u64::try_from(value)
        .unwrap_or_else(|_| panic!("HIA example-validation {field} exceeds u64"))
}

fn step(
    operation: u64,
    negative: usize,
    positive: usize,
    cursor: usize,
    previously_unmatched: usize,
    observed: u64,
) -> Response {
    let mut source = [0_u8; 56];
    for (slot, value) in [
        1,
        operation,
        to_word(negative, "negative count"),
        to_word(positive, "positive count"),
        to_word(cursor, "cursor"),
        to_word(previously_unmatched, "unmatched count"),
        observed,
    ]
    .into_iter()
    .enumerate()
    {
        source[slot * 8..slot * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    let original_source = source;
    let mut output = [0xa5_u8; 40];
    let mut unused_workspace = [0_u8; 0];
    let status = unsafe {
        codex_hia_example_validation_step(
            source.as_ptr(),
            56,
            output.as_mut_ptr(),
            40,
            unused_workspace.as_mut_ptr(),
            0,
        )
    };
    if status != 0 {
        panic!("HIA example-validation returned nonzero native status {status}");
    }
    if source != original_source {
        panic!("HIA example-validation mutated its read-only request");
    }
    let response = Response {
        opcode: word(&output, 0),
        index: word(&output, 8),
        unmatched: word(&output, 16),
        append: word(&output, 24),
        phase: word(&output, 32),
    };
    let negative = to_word(negative, "negative count");
    let positive = to_word(positive, "positive count");
    match response.opcode {
        0 if response.index == 0
            && response.unmatched == 0
            && response.append == 0
            && response.phase == 0 => {}
        1 if response.index < negative
            && response.unmatched == 0
            && response.append == 0
            && response.phase == 1 => {}
        2 if response.index < positive
            && response.unmatched <= positive
            && response.append <= 1
            && response.phase == 2 => {}
        3 if response.index < negative
            && response.unmatched == 0
            && response.append == 0
            && response.phase == 0 => {}
        4 if response.index < positive
            && response.unmatched > 0
            && response.unmatched <= positive
            && response.append <= 1
            && response.phase == 0 => {}
        _ => panic!("HIA example-validation response violates its structural ABI"),
    }
    response
}

/// The HIA response determines the next permitted callback. The host keeps
/// authoritative cursor and rendered misses and rejects a contradictory step.
pub(crate) fn validate_examples(
    policy: &Policy,
    rules: &[RuleRef],
    matches: &[Vec<String>],
    not_matches: &[Vec<String>],
) -> Result<()> {
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    let mut rendered = Vec::new();
    let mut next_negative = 0_usize;
    let mut next_positive = 0_usize;
    let mut pending = step(0, not_matches.len(), matches.len(), 0, 0, 2);

    loop {
        match pending.opcode {
            0 => {
                if next_negative != not_matches.len()
                    || next_positive != matches.len()
                    || !rendered.is_empty()
                {
                    panic!("HIA example-validation completed before all effects");
                }
                return Ok(());
            }
            1 => {
                let index = usize::try_from(pending.index)
                    .unwrap_or_else(|_| panic!("HIA negative index exceeds usize"));
                if index != next_negative {
                    panic!("HIA example-validation skipped or repeated a negative callback");
                }
                let example = not_matches
                    .get(index)
                    .unwrap_or_else(|| panic!("HIA negative index is out of range"));
                let evaluated =
                    policy.matches_for_command_with_options(example, None, &options);
                let matched = evaluated.first();
                let response = step(
                    1,
                    not_matches.len(),
                    matches.len(),
                    index,
                    0,
                    u64::from(matched.is_some()),
                );
                next_negative += 1;
                if let Some(rule) = matched {
                    if response.opcode != 3 || response.index != pending.index {
                        panic!("HIA example-validation missed the first negative error");
                    }
                    return Err(Error::ExampleDidMatch {
                        rule: format!("{rule:?}"),
                        example: try_join(example.iter().map(String::as_str))
                            .unwrap_or_else(|_| "unable to render example".to_string()),
                        location: None,
                    });
                }
                if response.opcode == 3
                    || (next_negative < not_matches.len()
                        && (response.opcode != 1 || response.index != pending.index + 1))
                    || (next_negative == not_matches.len()
                        && !matches.is_empty()
                        && (response.opcode != 2 || response.index != 0))
                    || (next_negative == not_matches.len()
                        && matches.is_empty()
                        && response.opcode != 0)
                {
                    panic!("HIA example-validation negative continuation is invalid");
                }
                pending = response;
            }
            2 => {
                let index = usize::try_from(pending.index)
                    .unwrap_or_else(|_| panic!("HIA positive index exceeds usize"));
                if index != next_positive || next_negative != not_matches.len() {
                    panic!("HIA example-validation violated negative-first ordering");
                }
                let example = matches
                    .get(index)
                    .unwrap_or_else(|| panic!("HIA positive index is out of range"));
                let matched = !policy
                    .matches_for_command_with_options(example, None, &options)
                    .is_empty();
                // Match the original Rust path: render and retain a missed example
                // before invoking any continuation. Formatting can itself unwind.
                let previously_unmatched = rendered.len();
                if !matched {
                    rendered.push(
                        try_join(example.iter().map(String::as_str))
                            .unwrap_or_else(|_| "unable to render example".to_string()),
                    );
                }
                let response = step(
                    2,
                    not_matches.len(),
                    matches.len(),
                    index,
                    previously_unmatched,
                    u64::from(matched),
                );
                if !matched && response.append != 1 {
                    panic!("HIA example-validation suppressed an unmatched example");
                }
                if matched && response.append != 0 {
                    panic!("HIA example-validation rendered a matched example");
                }
                if response.opcode == 3
                    || (response.opcode != 0
                        && response.unmatched != to_word(rendered.len(), "rendered count"))
                {
                    panic!("HIA example-validation reported a mismatched positive count");
                }
                next_positive += 1;
                if next_positive < matches.len() {
                    if response.opcode != 2 || response.index != pending.index + 1 {
                        panic!("HIA example-validation skipped or repeated a positive callback");
                    }
                } else if rendered.is_empty() {
                    if response.opcode != 0 {
                        panic!("HIA example-validation fabricated a positive error");
                    }
                } else if response.opcode != 4 || response.index != pending.index {
                    panic!("HIA example-validation dropped unmatched positives");
                }
                pending = response;
            }
            4 => {
                if next_negative != not_matches.len()
                    || next_positive != matches.len()
                    || rendered.is_empty()
                    || pending.unmatched != to_word(rendered.len(), "final rendered count")
                {
                    panic!("HIA example-validation positive termination is invalid");
                }
                return Err(Error::ExampleDidNotMatch {
                    rules: rules.iter().map(|rule| format!("{rule:?}")).collect(),
                    examples: rendered,
                    location: None,
                });
            }
            _ => panic!("HIA example-validation requested an unexpected terminal transition"),
        }
    }
}
