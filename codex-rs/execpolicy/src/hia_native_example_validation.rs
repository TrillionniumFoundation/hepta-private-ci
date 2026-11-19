//! Checked continuation transport for positive and negative policy examples.
//!
//! Rust owns rule callbacks, diagnostics, shell quoting and error construction.
//! HIA owns the state transition, termination and error-continuation decision.

use crate::error::Error;
use crate::error::Result;
use crate::policy::MatchOptions;
use crate::policy::Policy;
use crate::rule::RuleRef;
use shlex::try_join;

unsafe extern "C" {
    fn codex_hia_example_validation_continuation(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

struct Transition {
    event: u64,
    next: u64,
    misses: u64,
}

fn advance(mode: u64, total: u64, index: u64, misses: u64, matched: bool) -> Transition {
    let mut source = [0_u8; 48];
    for (slot, value) in [1, mode, total, index, misses, u64::from(matched)]
        .into_iter()
        .enumerate()
    {
        source[slot * 8..(slot + 1) * 8].copy_from_slice(&value.to_le_bytes());
    }
    let original_source = source;
    let mut output = [0_u8; 32];
    let mut workspace: [u8; 0] = [];
    let status = unsafe {
        codex_hia_example_validation_continuation(
            source.as_ptr(),
            48,
            output.as_mut_ptr(),
            32,
            workspace.as_mut_ptr(),
            0,
        )
    };
    if status != 0 || source != original_source {
        panic!("HIA example-validation native call failed or changed its input: {status}");
    }
    let mut words = [0_u64; 4];
    for (value, bytes) in words.iter_mut().zip(output.chunks_exact(8)) {
        *value = u64::from_le_bytes(
            bytes
                .try_into()
                .unwrap_or_else(|_| panic!("HIA response word width")),
        );
    }
    let [event, next, new_misses, reserved] = words;
    let expected_next = if total == 0 && event == 0 {
        0
    } else if event == 4 {
        index
    } else {
        index
            .checked_add(1)
            .unwrap_or_else(|| panic!("HIA example index overflow"))
    };
    if reserved != 0 || event > 5 || next != expected_next || next > total || new_misses > next {
        panic!("HIA example-validation response violates the structural contract");
    }
    Transition {
        event,
        next,
        misses: new_misses,
    }
}

pub(crate) fn validate_match_examples(
    policy: &Policy,
    rules: &[RuleRef],
    matches: &[Vec<String>],
) -> Result<()> {
    let total =
        u64::try_from(matches.len()).unwrap_or_else(|_| panic!("example count exceeds u64"));
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    let mut missing = Vec::new();
    let mut misses = 0_u64;
    if total == 0 {
        let result = advance(1, 0, 0, 0, false);
        assert_eq!((result.event, result.next, result.misses), (0, 0, 0));
        return Ok(());
    }
    for (index, example) in matches.iter().enumerate() {
        let matched = !policy
            .matches_for_command_with_options(example, /*heuristics_fallback*/ None, &options)
            .is_empty();
        let result = advance(
            1,
            total,
            u64::try_from(index).unwrap_or_else(|_| panic!("example index exceeds u64")),
            misses,
            matched,
        );
        misses = result.misses;
        if result.event == 2 || result.event == 3 {
            missing.push(
                try_join(example.iter().map(String::as_str))
                    .unwrap_or_else(|_| "unable to render example".to_string()),
            );
        }
        match result.event {
            0 => return Ok(()),
            1 | 2 => continue,
            3 | 5 => {
                return Err(Error::ExampleDidNotMatch {
                    rules: rules.iter().map(|rule| format!("{rule:?}")).collect(),
                    examples: missing,
                    location: None,
                });
            }
            _ => panic!("HIA positive example returned an unexpected continuation event"),
        }
    }
    panic!("HIA positive example sequence has no terminal transition")
}

pub(crate) fn validate_not_match_examples(
    policy: &Policy,
    _rules: &[RuleRef],
    not_matches: &[Vec<String>],
) -> Result<()> {
    let total =
        u64::try_from(not_matches.len()).unwrap_or_else(|_| panic!("example count exceeds u64"));
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    if total == 0 {
        let result = advance(0, 0, 0, 0, false);
        assert_eq!((result.event, result.next, result.misses), (0, 0, 0));
        return Ok(());
    }
    for (index, example) in not_matches.iter().enumerate() {
        let matched = policy
            .matches_for_command_with_options(example, /*heuristics_fallback*/ None, &options);
        let result = advance(
            0,
            total,
            u64::try_from(index).unwrap_or_else(|_| panic!("example index exceeds u64")),
            0,
            !matched.is_empty(),
        );
        match result.event {
            0 => return Ok(()),
            1 => continue,
            4 => {
                let first = matched
                    .first()
                    .unwrap_or_else(|| panic!("HIA negative stop without a matching rule"));
                return Err(Error::ExampleDidMatch {
                    rule: format!("{first:?}"),
                    example: try_join(example.iter().map(String::as_str))
                        .unwrap_or_else(|_| "unable to render example".to_string()),
                    location: None,
                });
            }
            _ => panic!("HIA negative example returned an unexpected continuation event"),
        }
    }
    panic!("HIA negative example sequence has no terminal transition")
}
