//! Fail-closed Rust transport candidate for the HIA example-validation continuation.
//!
//! This test-only module does not register a native symbol, replace either public
//! validator or change the default policy path. A later source-bound stage must
//! supply the verified HIA entrypoint and independently qualify its behavior.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Mode {
    Negative,
    Positive,
}

impl Mode {
    fn word(self) -> u64 {
        match self {
            Self::Negative => 0,
            Self::Positive => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Event {
    Done,
    Continue,
    Render,
    RenderLast,
    NegativeMatch,
    PositiveError,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct Reply {
    pub(super) event: Event,
    pub(super) next: u64,
    pub(super) misses: u64,
}

fn word(bytes: &[u8]) -> u64 {
    u64::from_le_bytes(
        bytes
            .try_into()
            .unwrap_or_else(|_| panic!("HIA example-validation response word has wrong width")),
    )
}

/// Validate one complete six-word HIA request and its four-word native reply.
///
/// The injected step is deliberately not a fallback or a second algorithm.
/// Only the structural wire contract is checked here. A semantically incorrect
/// but well-formed native result still requires an independent original oracle.
pub(super) fn step<F>(
    mode: Mode,
    total: u64,
    index: u64,
    misses: u64,
    matched: bool,
    native_step: F,
) -> Reply
where
    F: FnOnce(&[u8], &mut [u8], &mut [u8]) -> u64,
{
    if total == 0 {
        assert!(
            index == 0 && misses == 0 && !matched,
            "HIA example-validation impossible empty input state"
        );
    } else {
        assert!(
            index < total && misses <= index,
            "HIA example-validation input cursor is out of range"
        );
    }
    if mode == Mode::Negative {
        assert_eq!(misses, 0, "HIA negative example input has positive misses");
    }

    let mut source = [0_u8; 48];
    for (offset, value) in [
        1_u64,
        mode.word(),
        total,
        index,
        misses,
        u64::from(matched),
    ]
    .into_iter()
    .enumerate()
    {
        source[offset * 8..offset * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    let original_source = source;
    let mut output = [0xa5_u8; 40];
    let mut workspace = [];

    // The production stage will inject the actual, separately qualified
    // synchronous FFI entrypoint. No borrowed pointer escapes this call.
    let status = native_step(&source, &mut output, &mut workspace);
    assert_eq!(source, original_source, "HIA mutated read-only example input");
    assert_eq!(status, 0, "HIA rejected example-validation transition");
    assert_eq!(
        &output[32..],
        &[0xa5_u8; 8],
        "HIA wrote past the 32-byte example response"
    );
    let event = match word(&output[0..8]) {
        0 => Event::Done,
        1 => Event::Continue,
        2 => Event::Render,
        3 => Event::RenderLast,
        4 => Event::NegativeMatch,
        5 => Event::PositiveError,
        other => panic!("HIA returned unknown example-validation event {other}"),
    };
    let next = word(&output[8..16]);
    let returned_misses = word(&output[16..24]);
    assert_eq!(
        word(&output[24..32]),
        0,
        "HIA example-validation reserved field is not zero"
    );
    assert!(
        next <= total && returned_misses <= next,
        "HIA example-validation returned an out-of-range cursor"
    );
    if mode == Mode::Negative {
        assert_eq!(
            returned_misses, 0,
            "HIA negative example response retained unmatched positives"
        );
    } else {
        assert!(
            returned_misses >= misses,
            "HIA positive example response lost earlier misses"
        );
    }

    if total == 0 {
        assert_eq!(event, Event::Done, "HIA nonterminal empty examples");
    } else if event == Event::NegativeMatch {
        assert_eq!(mode, Mode::Negative, "HIA negative stop in positive mode");
        assert_eq!(next, index, "HIA negative stop advanced the cursor");
    } else {
        assert_eq!(
            next,
            index + 1,
            "HIA example-validation transition did not advance once"
        );
    }
    match event {
        Event::Done => {
            assert_eq!(next, total, "HIA prematurely completed examples");
            assert_eq!(returned_misses, 0, "HIA completed with unmatched positives");
        }
        Event::Continue => {
            assert!(next < total, "HIA continued beyond last example");
        }
        Event::Render => {
            assert_eq!(mode, Mode::Positive, "HIA rendered a negative example");
            assert!(next < total && returned_misses > 0);
        }
        Event::RenderLast | Event::PositiveError => {
            assert_eq!(mode, Mode::Positive, "HIA signalled positive error in negative mode");
            assert!(next == total && returned_misses > 0);
        }
        Event::NegativeMatch => {
            assert_eq!(mode, Mode::Negative);
        }
    }
    Reply {
        event,
        next,
        misses: returned_misses,
    }
}

#[cfg(test)]
#[path = "hia_native_example_validation_candidate_tests.rs"]
mod tests;
