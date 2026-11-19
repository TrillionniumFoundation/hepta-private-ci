use super::Event;
use super::Mode;
use super::Reply;
use super::step;
use std::cell::Cell;
use std::panic::AssertUnwindSafe;

fn native_reply(event: u64, next: u64, misses: u64, reserved: u64) -> [u8; 32] {
    let mut result = [0_u8; 32];
    for (index, value) in [event, next, misses, reserved].into_iter().enumerate() {
        result[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    result
}

fn observed(
    mode: Mode,
    total: u64,
    index: u64,
    misses: u64,
    matched: bool,
    reply: [u8; 32],
) -> Reply {
    step(mode, total, index, misses, matched, |input, output, workspace| {
        assert_eq!(input.len(), 48);
        assert_eq!(workspace.len(), 0);
        assert_eq!(u64::from_le_bytes(input[0..8].try_into().unwrap()), 1);
        assert_eq!(u64::from_le_bytes(input[16..24].try_into().unwrap()), total);
        assert_eq!(u64::from_le_bytes(input[24..32].try_into().unwrap()), index);
        output[..32].copy_from_slice(&reply);
        0
    })
}

#[test]
fn empty_examples_complete_without_callback() {
    assert_eq!(
        observed(Mode::Positive, 0, 0, 0, false, native_reply(0, 0, 0, 0)),
        Reply { event: Event::Done, next: 0, misses: 0 }
    );
    assert_eq!(
        observed(Mode::Negative, 0, 0, 0, false, native_reply(0, 0, 0, 0)),
        Reply { event: Event::Done, next: 0, misses: 0 }
    );
}

#[test]
fn positive_example_events_have_distinct_terminal_shapes() {
    assert_eq!(
        observed(Mode::Positive, 3, 0, 0, false, native_reply(2, 1, 1, 0)).event,
        Event::Render
    );
    assert_eq!(
        observed(Mode::Positive, 3, 2, 1, false, native_reply(3, 3, 2, 0)).event,
        Event::RenderLast
    );
    assert_eq!(
        observed(Mode::Positive, 3, 2, 1, true, native_reply(5, 3, 1, 0)).event,
        Event::PositiveError
    );
    assert_eq!(
        observed(Mode::Positive, 3, 2, 0, true, native_reply(0, 3, 0, 0)).event,
        Event::Done
    );
}

#[test]
fn negative_first_match_preserves_original_cursor() {
    assert_eq!(
        observed(Mode::Negative, 2, 0, 0, true, native_reply(4, 0, 0, 0)),
        Reply { event: Event::NegativeMatch, next: 0, misses: 0 }
    );
    assert_eq!(
        observed(Mode::Negative, 2, 0, 0, false, native_reply(1, 1, 0, 0)).event,
        Event::Continue
    );
    assert_eq!(
        observed(Mode::Negative, 2, 1, 0, false, native_reply(0, 2, 0, 0)).event,
        Event::Done
    );
}

#[test]
fn impossible_input_never_calls_native_code() {
    let called = Cell::new(false);
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
        step(Mode::Positive, 0, 0, 0, true, |_, _, _| {
            called.set(true);
            0
        });
    }));
    assert!(result.is_err());
    assert!(!called.get());
}

#[test]
fn invalid_status_and_partial_output_are_not_silent_success() {
    for status in [u64::from(u32::MAX), u64::from(u32::MAX - 1), 7] {
        let result = std::panic::catch_unwind(|| {
            step(Mode::Positive, 1, 0, 0, true, |_, output, _| {
                output[..32].copy_from_slice(&native_reply(0, 1, 0, 0));
                status
            });
        });
        assert!(result.is_err());
    }
    let result = std::panic::catch_unwind(|| {
        step(Mode::Positive, 1, 0, 0, true, |_, _, _| 0);
    });
    assert!(result.is_err());
}

#[test]
fn malformed_responses_fail_closed_before_public_effects() {
    // event, next, misses, reserved: unknown event, altered reserved,
    // invalid cursor, incomplete response, wrong terminal state, wrong mode.
    for (mode, total, index, misses, hit, reply) in [
        (Mode::Positive, 1, 0, 0, true, native_reply(99, 1, 0, 0)),
        (Mode::Positive, 1, 0, 0, true, native_reply(0, 1, 0, 1)),
        (Mode::Positive, 1, 0, 0, true, native_reply(0, 2, 0, 0)),
        (Mode::Positive, 2, 0, 0, true, native_reply(1, 0, 0, 0)),
        (Mode::Positive, 2, 0, 0, true, native_reply(0, 1, 0, 0)),
        (Mode::Negative, 2, 0, 0, true, native_reply(2, 1, 1, 0)),
        (Mode::Negative, 2, 0, 0, true, native_reply(4, 1, 0, 0)),
        (Mode::Positive, 2, 1, 1, true, native_reply(0, 2, 0, 0)),
    ] {
        let result = std::panic::catch_unwind(|| {
            observed(mode, total, index, misses, hit, reply);
        });
        assert!(result.is_err());
    }
}

#[test]
fn output_tail_must_remain_untouched() {
    let result = std::panic::catch_unwind(|| {
        step(Mode::Positive, 1, 0, 0, true, |_, output, _| {
            output[..32].copy_from_slice(&native_reply(0, 1, 0, 0));
            output[32] = 0;
            0
        });
    });
    assert!(result.is_err());
}
