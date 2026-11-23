//! Inject forged native response words into the production fail-closed checker.
//!
//! This checks the Rust response guard itself, not the Hepta compiler or FFI
//! implementation. Exact-tree native/installed qualification remains separate.

use super::DONE;
use super::LAST_MISSING;
use super::MISSING;
use super::NEGATIVE;
use super::NEGATIVE_MATCH;
use super::NEXT;
use super::OUTPUT_BYTES;
use super::POSITIVE;
use super::POSITIVE_FINISHED_WITH_MISSES;
use super::validate_response;

fn frame(words: [u64; 4]) -> [u8; OUTPUT_BYTES] {
    let mut bytes = [0; OUTPUT_BYTES];
    for (index, word) in words.into_iter().enumerate() {
        bytes[index * 8..(index + 1) * 8].copy_from_slice(&word.to_le_bytes());
    }
    bytes
}

#[test]
fn accepts_all_314_reachable_small_callback_transitions() {
    let mut accepted = 0;
    for mode in [NEGATIVE, POSITIVE] {
        let empty = validate_response(mode, 0, 0, 0, false, &frame([DONE, 0, 0, 0]));
        assert_eq!((empty.event, empty.next, empty.misses), (DONE, 0, 0));
        accepted += 1;

        for total in 1usize..=8 {
            for index in 0..total {
                for prior_misses in 0..=index {
                    if mode == NEGATIVE && prior_misses != 0 {
                        continue;
                    }
                    for hit in [false, true] {
                        let successor = index + 1;
                        let (event, next, new_misses) = if mode == NEGATIVE {
                            if hit {
                                (NEGATIVE_MATCH, index, 0)
                            } else {
                                (if successor == total { DONE } else { NEXT }, successor, 0)
                            }
                        } else {
                            let count = prior_misses + usize::from(!hit);
                            let event = if hit {
                                if successor != total {
                                    NEXT
                                } else if count == 0 {
                                    DONE
                                } else {
                                    POSITIVE_FINISHED_WITH_MISSES
                                }
                            } else if successor == total {
                                LAST_MISSING
                            } else {
                                MISSING
                            };
                            (event, successor, count)
                        };
                        let observed = validate_response(
                            mode,
                            total,
                            index,
                            prior_misses,
                            hit,
                            &frame([event, next as u64, new_misses as u64, 0]),
                        );
                        assert_eq!(
                            (observed.event, observed.next, observed.misses),
                            (event, next, new_misses)
                        );
                        accepted += 1;
                    }
                }
            }
        }
    }
    assert_eq!(accepted, 314);
}

#[test]
#[should_panic(expected = "miss event disagrees with the policy callback")]
fn positive_callback_hit_cannot_be_forged_as_missing() {
    let _ = validate_response(POSITIVE, 2, 0, 0, true, &frame([MISSING, 1, 1, 0]));
}

#[test]
#[should_panic(expected = "miss event disagrees with the policy callback")]
fn positive_callback_miss_cannot_be_forged_as_next() {
    let _ = validate_response(POSITIVE, 2, 0, 0, false, &frame([NEXT, 1, 0, 0]));
}

#[test]
#[should_panic(expected = "negative event disagrees with the policy callback")]
fn negative_callback_hit_cannot_be_forged_as_next() {
    let _ = validate_response(NEGATIVE, 2, 0, 0, true, &frame([NEXT, 1, 0, 0]));
}

#[test]
#[should_panic(expected = "negative event disagrees with the policy callback")]
fn negative_callback_miss_cannot_be_forged_as_match() {
    let _ = validate_response(NEGATIVE, 2, 0, 0, false, &frame([NEGATIVE_MATCH, 0, 0, 0]));
}

#[test]
#[should_panic(expected = "miss count disagrees with callback results")]
fn previous_positive_misses_cannot_be_erased() {
    let _ = validate_response(POSITIVE, 3, 1, 1, true, &frame([NEXT, 2, 0, 0]));
}

#[test]
#[should_panic(expected = "final event ignored earlier misses")]
fn terminal_positive_hit_cannot_hide_earlier_misses() {
    let _ = validate_response(POSITIVE, 3, 2, 1, true, &frame([DONE, 3, 1, 0]));
}

#[test]
#[should_panic(expected = "nonterminal miss at the last example")]
fn last_positive_miss_cannot_request_another_step() {
    let _ = validate_response(POSITIVE, 2, 1, 0, false, &frame([MISSING, 2, 1, 0]));
}

#[test]
#[should_panic(expected = "reserved response is nonzero")]
fn empty_result_rejects_nonzero_reserved_word() {
    let _ = validate_response(POSITIVE, 0, 0, 0, false, &frame([DONE, 0, 0, 1]));
}

#[test]
#[should_panic(expected = "reserved response is nonzero")]
fn unwritten_empty_response_cannot_masquerade_as_done() {
    let _ = validate_response(POSITIVE, 0, 0, 0, false, &[0xA5; OUTPUT_BYTES]);
}

#[test]
#[should_panic(expected = "terminal event before the final example")]
fn negative_unmatched_event_cannot_finish_early() {
    let _ = validate_response(NEGATIVE, 2, 0, 0, false, &frame([DONE, 1, 0, 0]));
}

#[test]
#[should_panic(expected = "input mode is invalid")]
fn rejects_unrecognized_mode_even_on_empty_examples() {
    let _ = validate_response(2, 0, 0, 0, false, &frame([DONE, 0, 0, 0]));
}

#[test]
#[should_panic(expected = "empty-example input state is invalid")]
fn rejects_noncanonical_empty_example_input() {
    let _ = validate_response(POSITIVE, 0, 1, 0, false, &frame([DONE, 0, 0, 0]));
}

#[test]
#[should_panic(expected = "input state is invalid")]
fn rejects_positive_misses_exceeding_completed_examples() {
    let _ = validate_response(POSITIVE, 2, 0, 1, true, &frame([NEXT, 1, 1, 0]));
}

#[test]
#[should_panic(expected = "input state is invalid")]
fn rejects_negative_mode_with_prior_misses() {
    let _ = validate_response(NEGATIVE, 2, 0, 1, false, &frame([NEXT, 1, 0, 0]));
}
