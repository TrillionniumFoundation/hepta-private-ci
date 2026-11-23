//! HIA continuation decisions for rule example validation.
//!
//! HIA owns the next-event and counter transition. Rust continues to own
//! fallible policy callbacks, the original error objects, and their drop order.
//! An invalid native transition is a hard failure, never an implicit match.

use crate::MatchOptions;
use crate::Policy;
use crate::RuleRef;
use crate::error::Error;
use crate::error::Result;
use shlex::try_join;

const INPUT_BYTES: usize = 48;
const OUTPUT_BYTES: usize = 32;
const NEGATIVE: u64 = 0;
const POSITIVE: u64 = 1;
const DONE: u64 = 0;
const NEXT: u64 = 1;
const MISSING: u64 = 2;
const LAST_MISSING: u64 = 3;
const NEGATIVE_MATCH: u64 = 4;
const POSITIVE_FINISHED_WITH_MISSES: u64 = 5;

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

#[derive(Clone, Copy)]
struct Transition {
    event: u64,
    next: usize,
    misses: usize,
}

// Validate the request before passing any borrowed region to the native ABI.
// Keep this same contract in the standalone response checker used by tests.
fn validate_request(mode: u64, total: usize, index: usize, misses: usize, hit: bool) {
    assert!(
        mode == NEGATIVE || mode == POSITIVE,
        "HIA example-validation input mode is invalid"
    );
    if total == 0 {
        assert!(
            index == 0 && misses == 0 && !hit,
            "HIA empty-example input state is invalid"
        );
    } else {
        assert!(
            index < total && misses <= index && (mode != NEGATIVE || misses == 0),
            "HIA example-validation input state is invalid"
        );
    }
}

fn step(mode: u64, total: usize, index: usize, misses: usize, hit: bool) -> Transition {
    validate_request(mode, total, index, misses, hit);
    let total_word =
        u64::try_from(total).unwrap_or_else(|_| panic!("example-validation count exceeds u64"));
    let index_word =
        u64::try_from(index).unwrap_or_else(|_| panic!("example-validation index exceeds u64"));
    let misses_word =
        u64::try_from(misses).unwrap_or_else(|_| panic!("example-validation misses exceed u64"));
    let mut source = [0u8; INPUT_BYTES];
    for (i, word) in [
        1u64,
        mode,
        total_word,
        index_word,
        misses_word,
        if hit { 1 } else { 0 },
    ]
    .into_iter()
    .enumerate()
    {
        source[i * 8..(i + 1) * 8].copy_from_slice(&word.to_le_bytes());
    }
    let original_source = source;
    // Zero is the valid DONE frame for an empty example list. Poison the output
    // so a callee that falsely reports success without writing a response
    // cannot be mistaken for that legitimate empty result.
    let mut output = [0xA5u8; OUTPUT_BYTES];
    let mut workspace: [u8; 0] = [];
    // Borrowed regions are disjoint and carry exact lengths. HIA never sees
    // policy objects, arbitrary callback pointers, or error strings.
    let status = unsafe {
        codex_hia_example_validation_continuation(
            source.as_ptr(),
            INPUT_BYTES as u64,
            output.as_mut_ptr(),
            OUTPUT_BYTES as u64,
            workspace.as_mut_ptr(),
            0,
        )
    };
    assert_eq!(
        status, 0,
        "HIA example-validation transition rejected a valid input"
    );
    assert_eq!(
        source, original_source,
        "HIA wrote to the read-only example frame"
    );
    validate_response(mode, total, index, misses, hit, &output)
}

fn validate_response(
    mode: u64,
    total: usize,
    index: usize,
    misses: usize,
    hit: bool,
    output: &[u8; OUTPUT_BYTES],
) -> Transition {
    validate_request(mode, total, index, misses, hit);
    let word = |offset: usize| {
        u64::from_le_bytes(
            output[offset..offset + 8]
                .try_into()
                .unwrap_or_else(|_| panic!("example-validation response word width")),
        )
    };
    let event = word(0);
    let next = usize::try_from(word(8))
        .unwrap_or_else(|_| panic!("example-validation next index overflow"));
    let new_misses =
        usize::try_from(word(16)).unwrap_or_else(|_| panic!("example-validation misses overflow"));
    assert_eq!(
        word(24),
        0,
        "HIA example-validation reserved response is nonzero"
    );
    assert!(
        new_misses <= total && next <= total,
        "HIA response exceeded example bounds"
    );
    if total == 0 {
        assert!(
            event == DONE && next == 0 && new_misses == 0,
            "HIA returned an invalid empty-example transition"
        );
    } else if event == NEGATIVE_MATCH {
        assert!(
            mode == NEGATIVE && next == index && new_misses == 0,
            "HIA negative-match response violates the stop contract"
        );
    } else {
        let successor = index
            .checked_add(1)
            .unwrap_or_else(|| panic!("example-validation index overflow"));
        assert_eq!(
            next, successor,
            "HIA continuation did not advance one example"
        );
        assert!(
            matches!(
                event,
                DONE | NEXT | MISSING | LAST_MISSING | POSITIVE_FINISHED_WITH_MISSES
            ),
            "HIA returned an unknown continuation event"
        );
        assert!(
            event != NEXT || next < total,
            "HIA next event violated the terminal boundary"
        );
        assert!(
            mode == POSITIVE
                || !matches!(
                    event,
                    MISSING | LAST_MISSING | POSITIVE_FINISHED_WITH_MISSES
                ),
            "HIA emitted a positive-only event for negative examples"
        );
        assert!(
            event != MISSING || next < total,
            "HIA returned a nonterminal miss at the last example"
        );
        assert!(
            !matches!(event, DONE | LAST_MISSING | POSITIVE_FINISHED_WITH_MISSES) || next == total,
            "HIA returned a terminal event before the final example"
        );
    }
    if total != 0 {
        // A well-formed native response must still agree with the actual Rust
        // policy callback. Fail closed instead of accepting a plausible event
        // that silently skips a miss or fabricates a negative match.
        let positive_miss = mode == POSITIVE && !hit;
        assert_eq!(
            matches!(event, MISSING | LAST_MISSING),
            positive_miss,
            "HIA example-validation miss event disagrees with the policy callback"
        );
        assert_eq!(
            event == NEGATIVE_MATCH,
            mode == NEGATIVE && hit,
            "HIA example-validation negative event disagrees with the policy callback"
        );
        let expected_misses = misses
            .checked_add(usize::from(positive_miss))
            .unwrap_or_else(|| panic!("example-validation miss count overflow"));
        assert_eq!(
            new_misses, expected_misses,
            "HIA example-validation miss count disagrees with callback results"
        );
        if mode == POSITIVE && hit && next == total {
            assert_eq!(
                event == DONE,
                misses == 0,
                "HIA example-validation final event ignored earlier misses"
            );
        }
    }
    Transition {
        event,
        next,
        misses: new_misses,
    }
}

fn rendered(example: &[String]) -> String {
    try_join(example.iter().map(String::as_str))
        .unwrap_or_else(|_| "unable to render example".to_string())
}

pub(crate) fn validate_positive(
    policy: &Policy,
    rules: &[RuleRef],
    matches: &[Vec<String>],
) -> Result<()> {
    let total = matches.len();
    if total == 0 {
        let result = step(POSITIVE, 0, 0, 0, false);
        assert_eq!(result.event, DONE);
        return Ok(());
    }
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    let mut unmatched_examples = Vec::new();
    let mut index = 0;
    let mut misses = 0;
    loop {
        let example = &matches[index];
        let matched = !policy
            .matches_for_command_with_options(example, /*heuristics_fallback*/ None, &options)
            .is_empty();
        let transition = step(POSITIVE, total, index, misses, matched);
        if matches!(transition.event, MISSING | LAST_MISSING) {
            unmatched_examples.push(rendered(example));
        }
        assert_eq!(
            transition.misses,
            unmatched_examples.len(),
            "HIA example miss count differs from retained examples"
        );
        misses = transition.misses;
        match transition.event {
            NEXT | MISSING => index = transition.next,
            DONE | LAST_MISSING | POSITIVE_FINISHED_WITH_MISSES => break,
            other => panic!("invalid positive-example HIA event {other}"),
        }
    }
    if unmatched_examples.is_empty() {
        Ok(())
    } else {
        Err(Error::ExampleDidNotMatch {
            rules: rules.iter().map(|rule| format!("{rule:?}")).collect(),
            examples: unmatched_examples,
            location: None,
        })
    }
}

pub(crate) fn validate_negative(policy: &Policy, not_matches: &[Vec<String>]) -> Result<()> {
    let total = not_matches.len();
    if total == 0 {
        let result = step(NEGATIVE, 0, 0, 0, false);
        assert_eq!(result.event, DONE);
        return Ok(());
    }
    let options = MatchOptions {
        resolve_host_executables: true,
    };
    let mut index = 0;
    loop {
        let example = &not_matches[index];
        let matches = policy
            .matches_for_command_with_options(example, /*heuristics_fallback*/ None, &options);
        let transition = step(NEGATIVE, total, index, 0, !matches.is_empty());
        match transition.event {
            NEXT => index = transition.next,
            DONE => return Ok(()),
            NEGATIVE_MATCH => {
                let rule = matches
                    .first()
                    .unwrap_or_else(|| panic!("HIA selected an absent negative rule"));
                return Err(Error::ExampleDidMatch {
                    rule: format!("{rule:?}"),
                    example: rendered(example),
                    location: None,
                });
            }
            other => panic!("invalid negative-example HIA event {other}"),
        }
    }
}

#[cfg(test)]
#[path = "hia_native_example_validation_tests.rs"]
mod tests;
