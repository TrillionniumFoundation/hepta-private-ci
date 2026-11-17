use super::overflow;
use super::state;
use super::wire;
use super::wire::Error;
use super::wire::Operation;
use super::wire::Request;
use super::wire::Response;
use super::wire::State;
use super::wire::field as f;

fn output(request: &Request<'_>, response: &Response) -> Result<Vec<u8>, Error> {
    let record_bytes = response.records.len() * wire::WORD_BYTES;
    let header = [
        wire::VERSION,
        request.operation as u64,
        response.state[f::OUTCOME],
        request.operation as u64,
        response.advance_a,
        response.advance_b,
        wire::to_u64(response.record_count)?,
        wire::to_u64(record_bytes)?,
        wire::to_u64(wire::OUTPUT_PREFIX + record_bytes)?,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ];
    let mut bytes = vec![0; request.capacity()?];
    for (index, word) in header
        .into_iter()
        .chain(response.state.0)
        .chain(response.records.iter().copied())
        .enumerate()
    {
        let start = index * wire::WORD_BYTES;
        bytes[start..start + wire::WORD_BYTES].copy_from_slice(&word.to_le_bytes());
    }
    Ok(bytes)
}

fn begin() -> (Request<'static>, Response) {
    let request = Request {
        operation: Operation::Begin,
        flags: 0,
        state: State::INITIAL,
        argument_a: 7,
        argument_b: 0,
        payload: &[],
    };
    let mut next = State::INITIAL;
    next.0[f::PHASE] = wire::DONE;
    next.0[f::HAY_TOTAL] = 7;
    next.0[f::OUTCOME] = wire::SOME;
    next.0[f::SCORE] = i32::MAX as u64;
    let response = Response {
        state: next,
        advance_a: 0,
        advance_b: 0,
        record_count: 0,
        records: Vec::new(),
    };
    (request, response)
}

fn one_hay() -> (Request<'static>, Response) {
    let mut old = State::INITIAL;
    old.0[f::PHASE] = wire::HAYSTACK;
    old.0[f::HAY_TOTAL] = 1;
    old.0[f::NEEDLE_TOTAL] = 1;
    let request = Request {
        operation: Operation::LowerHaystack,
        flags: wire::END,
        state: old,
        argument_a: 0,
        argument_b: 0,
        payload: b"A",
    };
    let mut next = old;
    next.0[f::PHASE] = wire::NEEDLE;
    next.0[f::HAY_SEEN] = 1;
    next.0[f::HAY_ORIGINAL] = 1;
    next.0[f::HAY_LOWER] = 1;
    let response = Response {
        state: next,
        advance_a: 1,
        advance_b: 0,
        record_count: 1,
        records: vec![97, 0, 0],
    };
    (request, response)
}

#[test]
fn full_wrapper_status_is_checked_before_accepting_a_valid_empty_result() -> Result<(), Error> {
    let (request, expected) = begin();
    let bytes = output(&request, &expected)?;
    let actual = wire::decode(&request, /*returned*/ 0, &bytes)?;
    state::validate_request(&request, (7, 0))?;
    state::validate_transition(&request, &actual)?;
    assert_eq!(actual, expected);
    for (returned, error) in [
        (1_u64 << 32, "wrapper status"),
        (u64::MAX, "wrapper status"),
        (1, "native invalid input"),
        (2, "native short output"),
        (3, "native counter overflow"),
        (4, "unknown native status"),
    ] {
        assert_eq!(wire::decode(&request, returned, &bytes), Err(error));
    }
    Ok(())
}

#[test]
fn complete_header_extents_and_unused_output_tail_are_checked() -> Result<(), Error> {
    let (request, expected) = one_hay();
    let bytes = output(&request, &expected)?;
    assert_eq!(wire::decode(&request, /*returned*/ 0, &bytes)?, expected);
    for (word, value, error) in [
        (0, 2_u64, "output version"),
        (1, 2, "output operation"),
        (2, 1, "output outcome"),
        (3, 2, "record kind"),
        (7, 23, "record byte count"),
        (8, 409, "defined output size"),
        (9, 1, "reserved output"),
    ] {
        let mut bad = bytes.clone();
        let start = word * wire::WORD_BYTES;
        bad[start..start + wire::WORD_BYTES].copy_from_slice(&value.to_le_bytes());
        assert_eq!(wire::decode(&request, /*returned*/ 0, &bad), Err(error));
    }
    let mut tail = bytes.clone();
    let last = tail.len() - 1;
    tail[last] = 1;
    assert_eq!(
        wire::decode(&request, /*returned*/ 0, &tail),
        Err("output tail")
    );
    assert_eq!(
        wire::decode(&request, /*returned*/ 0, &bytes[..bytes.len() - 1]),
        Err("output reservation")
    );
    Ok(())
}

#[test]
fn request_validation_binds_original_lengths_end_and_complete_utf8() -> Result<(), Error> {
    let (mut request, _) = one_hay();
    request.state.0[f::HAY_TOTAL] = 2;
    request.flags = 0;
    state::validate_request(&request, (2, 1))?;
    assert_eq!(
        state::validate_request(&request, (0x1_0000_0002, 1)),
        Err("original byte totals")
    );
    request.flags = wire::END;
    assert_eq!(
        state::validate_request(&request, (2, 1)),
        Err("normalization end flag")
    );
    request.payload = b"\xf0\x9f";
    assert_eq!(state::validate_request(&request, (2, 1)), Err("input UTF8"));
    request.payload = b"\0\0";
    state::validate_request(&request, (2, 1))?;
    request.argument_a = 1;
    assert_eq!(
        state::validate_request(&request, (2, 1)),
        Err("normalization arguments")
    );
    Ok(())
}

#[test]
fn qualified_sigma_bounds_and_empty_context_are_rejected_before_transport() -> Result<(), Error> {
    let mut state = State::INITIAL;
    state.0[f::PHASE] = wire::NEEDLE;
    state.0[f::NEEDLE_TOTAL] = 6;
    state.0[f::NEEDLE_SEEN] = 3;
    state.0[f::NEEDLE_ORIGINAL] = 2;
    state.0[f::NEEDLE_LOWER] = 2;
    state.0[f::PREVIOUS_CASED] = 1;
    state.0[f::SIGMA_PENDING] = 1;
    state.0[f::SIGMA_SLOT] = 1;
    state::validate(state)?;
    for (index, value) in [(f::SIGMA_SLOT, 0), (f::NEEDLE_ORIGINAL, 1)] {
        let mut bad = state;
        bad.0[index] = value;
        assert_eq!(state::validate(bad), Err("pending sigma shape"));
    }
    let mut empty = State::INITIAL;
    empty.0[f::PHASE] = wire::NEEDLE;
    empty.0[f::NEEDLE_TOTAL] = 4;
    empty.0[f::PREVIOUS_CASED] = 1;
    let request = Request {
        operation: Operation::LowerNeedle,
        flags: 0,
        state: empty,
        argument_a: 0,
        argument_b: 0,
        payload: "Σ".as_bytes(),
    };
    assert_eq!(
        state::validate_request(&request, (0, 4)),
        Err("empty needle context")
    );
    let mut request = request;
    request.state.0[f::PREVIOUS_CASED] = 0;
    state::validate_request(&request, (0, 4))?;
    let forged = Response {
        state: empty,
        advance_a: 2,
        advance_b: 0,
        record_count: 1,
        records: vec![0, 0, 963],
    };
    let bytes = output(&request, &forged)?;
    let decoded = wire::decode(&request, /*returned*/ 0, &bytes)?;
    assert_eq!(
        state::validate_transition(&request, &decoded),
        Err("empty needle context")
    );
    Ok(())
}

#[test]
fn a_shape_valid_changed_original_total_is_still_an_invalid_transition() -> Result<(), Error> {
    let (request, expected) = one_hay();
    state::validate_request(&request, (1, 1))?;
    state::validate_transition(&request, &expected)?;
    let mut bad = expected;
    bad.state.0[f::HAY_TOTAL] = 2;
    bad.state.0[f::PHASE] = wire::HAYSTACK;
    state::validate(bad.state)?;
    assert_eq!(
        state::validate_transition(&request, &bad),
        Err("immutable state word")
    );
    Ok(())
}

#[test]
fn first_hit_and_last_start_keep_full_width_positions() -> Result<(), Error> {
    let mut state = State::INITIAL;
    state.0[f::PHASE] = wire::DONE;
    state.0[f::HAY_TOTAL] = 0x1_0000_0001;
    state.0[f::HAY_SEEN] = 0x1_0000_0001;
    state.0[f::HAY_ORIGINAL] = 0x1_0000_0001;
    state.0[f::HAY_LOWER] = 0x1_0000_0001;
    state.0[f::NEEDLE_TOTAL] = 1;
    state.0[f::NEEDLE_SEEN] = 1;
    state.0[f::NEEDLE_ORIGINAL] = 1;
    state.0[f::NEEDLE_LOWER] = 1;
    state.0[f::HAY_CURSOR] = 0x1_0000_0001;
    state.0[f::NEEDLE_CURSOR] = 1;
    for index in [
        f::LAST_START,
        f::FIRST_ORIGINAL,
        f::FIRST_START,
        f::LAST_HIT,
        f::LAST_ORIGINAL,
        f::SCANNED_ORIGINAL,
        f::SCANNED_START,
        f::FIRST_HIT,
    ] {
        state.0[index] = 0x1_0000_0000;
    }
    state.0[f::UNIQUE] = 1;
    state.0[f::OUTCOME] = wire::SOME;
    state.0[f::R2] = 1;
    state::validate(state)?;
    let mut bad = state;
    bad.0[f::FIRST_HIT] = 0;
    assert_eq!(state::validate(bad), Err("hit order"));
    Ok(())
}

#[test]
fn first_overflow_replays_the_actual_crate_policy_without_recomputing_score() -> Result<(), Error> {
    for (first, last, length, trace, score) in [
        (
            2147483647_u64,
            2147483648_u64,
            2_usize,
            [1, 2, 0, 1, 1, 0x80000000, 0x7fffffff],
            0,
        ),
        (
            0,
            2147483647,
            2,
            [0x7fffffff, 0x80000000, 0x7ffffffe, 6, 2, 0x7fffffff, 1],
            0x7fffff9a,
        ),
        (
            0,
            4294967295,
            2147483648,
            [0xffffffff, 0, 0x80000000, 4, 3, 0, 0x80000000],
            0xffffff9c,
        ),
        (4294967296, 4294967297, 2, [1, 2, 0, 0, 0, 0, 0], 0),
    ] {
        let mut state = State::INITIAL;
        state.0[f::FIRST_START] = first;
        state.0[f::LAST_HIT] = last;
        state.0[f::NEEDLE_LOWER] = wire::to_u64(length)?;
        for (index, value) in [
            f::R1,
            f::R2,
            f::R3,
            f::OVERFLOW_MASK,
            f::OVERFLOW_OP,
            f::OVERFLOW_LHS,
            f::OVERFLOW_RHS,
        ]
        .into_iter()
        .zip(trace)
        {
            state.0[index] = value;
        }
        state.0[f::SCORE] = score;
        let (returned_score, witness) = overflow::validate(state, length)?;
        assert_eq!(
            returned_score,
            i32::from_le_bytes((score as u32).to_le_bytes())
        );
        let original =
            std::panic::catch_unwind(|| (last as i32 - first as i32 + 1) - length as i32);
        let bridge = std::panic::catch_unwind(|| overflow::replay(witness));
        assert_eq!(bridge.is_err(), original.is_err());
        state.0[f::OVERFLOW_RHS] ^= 1;
        assert_eq!(overflow::validate(state, length), Err("overflow operands"));
    }
    Ok(())
}
