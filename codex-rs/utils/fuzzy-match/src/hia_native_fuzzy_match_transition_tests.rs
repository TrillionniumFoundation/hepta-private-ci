use super::matching;
use super::normalize;
use super::overflow;
use super::state;
use super::wire;
use super::wire::Error;
use super::wire::HayRecord;
use super::wire::Operation;
use super::wire::Request;
use super::wire::Response;
use super::wire::State;
use super::wire::field as f;

fn apply_needle(
    request: &Request<'_>,
    response: &Response,
    values: &mut Vec<u32>,
) -> Result<(), Error> {
    let old = request.state;
    state::validate_request(request, (old[f::HAY_TOTAL], old[f::NEEDLE_TOTAL]))?;
    state::validate_transition(request, response)?;
    let commands = normalize::decode_needle(request, response, values)?;
    normalize::apply_needle(commands, values);
    Ok(())
}

fn sigma_frames() -> (State, Response) {
    let mut old = State::INITIAL;
    old.0[f::PHASE] = wire::NEEDLE;
    old.0[f::NEEDLE_TOTAL] = 4;
    old.0[f::NEEDLE_SEEN] = 3;
    old.0[f::NEEDLE_ORIGINAL] = 2;
    old.0[f::NEEDLE_LOWER] = 2;
    old.0[f::PREVIOUS_CASED] = 1;
    old.0[f::SIGMA_PENDING] = 1;
    old.0[f::SIGMA_SLOT] = 1;
    let mut next = old;
    next.0[f::PHASE] = wire::MATCHING;
    next.0[f::NEEDLE_SEEN] = 4;
    next.0[f::NEEDLE_ORIGINAL] = 3;
    next.0[f::NEEDLE_LOWER] = 3;
    next.0[f::PREVIOUS_CASED] = 0;
    next.0[f::SIGMA_PENDING] = 0;
    next.0[f::SIGMA_SLOT] = 0;
    (
        old,
        Response {
            state: next,
            advance_a: 1,
            advance_b: 0,
            record_count: 2,
            records: vec![1, 1, 962, 0, 2, 33],
        },
    )
}

#[test]
fn sigma_replacements_can_target_an_old_slot_or_an_earlier_frame_append() -> Result<(), Error> {
    let (old, response) = sigma_frames();
    let request = Request {
        operation: Operation::LowerNeedle,
        flags: wire::END,
        state: old,
        argument_a: 0,
        argument_b: 0,
        payload: b"!",
    };
    let mut values = vec![97, 963];
    apply_needle(&request, &response, &mut values)?;
    assert_eq!(values, vec![97, 962, 33]);

    let mut fresh = State::INITIAL;
    fresh.0[f::PHASE] = wire::NEEDLE;
    fresh.0[f::NEEDLE_TOTAL] = 4;
    let request = Request {
        state: fresh,
        payload: "AΣ!".as_bytes(),
        ..request
    };
    let response = Response {
        advance_a: 4,
        record_count: 4,
        records: vec![0, 0, 97, 0, 1, 963, 1, 1, 962, 0, 2, 33],
        ..response
    };
    let mut values = Vec::new();
    apply_needle(&request, &response, &mut values)?;
    assert_eq!(values, vec![97, 962, 33]);
    Ok(())
}

#[test]
fn a_late_invalid_sigma_command_cannot_leave_an_earlier_patch() {
    let (old, response) = sigma_frames();
    let request = Request {
        operation: Operation::LowerNeedle,
        flags: wire::END,
        state: old,
        argument_a: 0,
        argument_b: 0,
        payload: b"!",
    };
    for (records, count, error) in [
        (vec![1, 1, 962, 0, 3, 33], 2, "needle append frontier"),
        (vec![1, 1, 962, 1, 1, 962, 0, 2, 33], 3, "replacement order"),
        (vec![1, 0, 962, 0, 2, 33], 2, "old sigma replacement"),
        (vec![1, 1, 963, 0, 2, 33], 2, "replacement scalar"),
        (vec![1, 1, 962, 0, 2, 0x110000], 2, "Unicode scalar"),
    ] {
        let bad = Response {
            records,
            record_count: count,
            ..response.clone()
        };
        let mut values = vec![97, 963];
        assert_eq!(apply_needle(&request, &bad, &mut values), Err(error));
        assert_eq!(values, vec![97, 963]);
    }
}

#[test]
fn normalization_retains_nul_and_rejects_a_late_wrong_original_index() -> Result<(), Error> {
    let mut old = State::INITIAL;
    old.0[f::PHASE] = wire::HAYSTACK;
    old.0[f::HAY_TOTAL] = 2;
    old.0[f::NEEDLE_TOTAL] = 1;
    let request = Request {
        operation: Operation::LowerHaystack,
        flags: wire::END,
        state: old,
        argument_a: 0,
        argument_b: 0,
        payload: b"\0A",
    };
    let mut next = old;
    next.0[f::PHASE] = wire::NEEDLE;
    next.0[f::HAY_SEEN] = 2;
    next.0[f::HAY_ORIGINAL] = 2;
    next.0[f::HAY_LOWER] = 2;
    let response = Response {
        state: next,
        advance_a: 2,
        advance_b: 0,
        record_count: 2,
        records: vec![0, 0, 0, 97, 1, 1],
    };
    state::validate_transition(&request, &response)?;
    assert_eq!(
        normalize::decode_hay(&request, &response, &[])?,
        vec![
            HayRecord {
                scalar: 0,
                original: 0,
                start: 0,
            },
            HayRecord {
                scalar: 97,
                original: 1,
                start: 1,
            },
        ]
    );
    let bad = Response {
        records: vec![0, 0, 0, 97, 0, 1],
        ..response
    };
    assert_eq!(
        normalize::decode_hay(&request, &bad, &[]),
        Err("expansion start")
    );
    Ok(())
}

fn match_payload(hay: &[HayRecord], needle: &[u32]) -> Vec<u8> {
    let mut bytes = Vec::new();
    for record in hay {
        for word in [u64::from(record.scalar), record.original, record.start] {
            bytes.extend_from_slice(&word.to_le_bytes());
        }
    }
    for value in needle {
        bytes.extend_from_slice(&u64::from(*value).to_le_bytes());
    }
    bytes
}

fn checked_match(
    request: &Request<'_>,
    response: &Response,
    hay: &[HayRecord],
    needle: &[u32],
    indices: &[usize],
) -> Result<matching::Frame, Error> {
    let old = request.state;
    state::validate_request(request, (old[f::HAY_TOTAL], old[f::NEEDLE_TOTAL]))?;
    state::validate_transition(request, response)?;
    matching::decode(request, response, hay, needle, indices)
}

fn expansion_state() -> State {
    let mut state = State::INITIAL;
    state.0[f::PHASE] = wire::MATCHING;
    state.0[f::HAY_TOTAL] = 2;
    state.0[f::HAY_SEEN] = 2;
    state.0[f::HAY_ORIGINAL] = 1;
    state.0[f::HAY_LOWER] = 2;
    state.0[f::NEEDLE_TOTAL] = 2;
    state.0[f::NEEDLE_SEEN] = 2;
    state.0[f::NEEDLE_ORIGINAL] = 1;
    state.0[f::NEEDLE_LOWER] = 1;
    state
}

#[test]
fn actual_hit_and_original_lower_start_are_bound_separately() -> Result<(), Error> {
    let hay = [
        HayRecord {
            scalar: 105,
            original: 0,
            start: 0,
        },
        HayRecord {
            scalar: 775,
            original: 0,
            start: 0,
        },
    ];
    let needle = [775];
    let payload = match_payload(&hay, &needle);
    let request = Request {
        operation: Operation::Match,
        flags: 0,
        state: expansion_state(),
        argument_a: 2,
        argument_b: 1,
        payload: &payload,
    };
    let mut next = request.state;
    next.0[f::PHASE] = wire::DONE;
    next.0[f::HAY_CURSOR] = 2;
    next.0[f::NEEDLE_CURSOR] = 1;
    next.0[f::FIRST_HIT] = 1;
    next.0[f::LAST_HIT] = 1;
    next.0[f::UNIQUE] = 1;
    next.0[f::OUTCOME] = wire::SOME;
    next.0[f::SCORE] = 0xffffff9d;
    next.0[f::R1] = 1;
    next.0[f::R2] = 2;
    next.0[f::R3] = 1;
    let response = Response {
        state: next,
        advance_a: 2,
        advance_b: 1,
        record_count: 1,
        records: vec![0],
    };
    assert_eq!(
        checked_match(&request, &response, &hay, &needle, &[])?,
        matching::Frame {
            indices: vec![0],
            terminal: Some((-99, overflow::Witness::None)),
        }
    );
    let mut bad = response;
    bad.advance_a = 1;
    bad.state.0[f::HAY_CURSOR] = 1;
    bad.state.0[f::FIRST_HIT] = 0;
    bad.state.0[f::LAST_HIT] = 0;
    assert_eq!(
        checked_match(&request, &bad, &hay, &needle, &[]),
        Err("first anchor identity")
    );
    Ok(())
}

#[test]
fn none_discards_prefix_indices_and_no_hit_cannot_change_prior_anchors() -> Result<(), Error> {
    let hay = [
        HayRecord {
            scalar: 105,
            original: 0,
            start: 0,
        },
        HayRecord {
            scalar: 775,
            original: 0,
            start: 0,
        },
        HayRecord {
            scalar: 98,
            original: 1,
            start: 2,
        },
    ];
    let needle = [105, 120];
    let mut old = expansion_state();
    old.0[f::HAY_TOTAL] = 3;
    old.0[f::HAY_SEEN] = 3;
    old.0[f::HAY_ORIGINAL] = 2;
    old.0[f::HAY_LOWER] = 3;
    old.0[f::NEEDLE_ORIGINAL] = 2;
    old.0[f::NEEDLE_LOWER] = 2;
    old.0[f::HAY_CURSOR] = 1;
    old.0[f::NEEDLE_CURSOR] = 1;
    old.0[f::UNIQUE] = 1;
    let payload = match_payload(&hay[1..], &needle[1..]);
    let request = Request {
        operation: Operation::Match,
        flags: 0,
        state: old,
        argument_a: 2,
        argument_b: 1,
        payload: &payload,
    };
    let mut next = old;
    next.0[f::PHASE] = wire::DONE;
    next.0[f::HAY_CURSOR] = 3;
    next.0[f::SCANNED_ORIGINAL] = 1;
    next.0[f::SCANNED_START] = 2;
    next.0[f::OUTCOME] = wire::NONE;
    let response = Response {
        state: next,
        advance_a: 2,
        advance_b: 0,
        record_count: 0,
        records: Vec::new(),
    };
    assert_eq!(
        checked_match(&request, &response, &hay, &needle, &[0])?,
        matching::Frame {
            indices: Vec::new(),
            terminal: None,
        }
    );
    let mut bad = response;
    bad.state.0[f::FIRST_HIT] = 1;
    bad.state.0[f::LAST_HIT] = 1;
    state::validate(bad.state)?;
    assert_eq!(
        checked_match(&request, &bad, &hay, &needle, &[0]),
        Err("unchanged hits")
    );
    Ok(())
}

#[test]
fn match_window_expansion_preserves_anchors_and_deduplicates() -> Result<(), Error> {
    let mut hay: Vec<HayRecord> = (0..129)
        .map(|index| HayRecord {
            scalar: 97,
            original: index,
            start: index,
        })
        .collect();
    hay[127].scalar = 105;
    hay[128] = HayRecord {
        scalar: 775,
        original: 127,
        start: 127,
    };
    let needle = [105, 775];
    let mut old = expansion_state();
    old.0[f::HAY_TOTAL] = 129;
    old.0[f::HAY_SEEN] = 129;
    old.0[f::HAY_ORIGINAL] = 128;
    old.0[f::HAY_LOWER] = 129;
    old.0[f::NEEDLE_TOTAL] = 3;
    old.0[f::NEEDLE_SEEN] = 3;
    old.0[f::NEEDLE_ORIGINAL] = 2;
    old.0[f::NEEDLE_LOWER] = 2;
    old.0[f::HAY_CURSOR] = 128;
    old.0[f::NEEDLE_CURSOR] = 1;
    old.0[f::UNIQUE] = 1;
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
        old.0[index] = 127;
    }
    let payload = match_payload(&hay[128..], &needle[1..]);
    let request = Request {
        operation: Operation::Match,
        flags: 0,
        state: old,
        argument_a: 1,
        argument_b: 1,
        payload: &payload,
    };
    let mut next = old;
    next.0[f::PHASE] = wire::DONE;
    next.0[f::HAY_CURSOR] = 129;
    next.0[f::NEEDLE_CURSOR] = 2;
    next.0[f::LAST_HIT] = 128;
    next.0[f::OUTCOME] = wire::SOME;
    next.0[f::R1] = 1;
    next.0[f::R2] = 2;
    let response = Response {
        state: next,
        advance_a: 1,
        advance_b: 1,
        record_count: 0,
        records: Vec::new(),
    };
    assert_eq!(
        checked_match(&request, &response, &hay, &needle, &[127])?,
        matching::Frame {
            indices: Vec::new(),
            terminal: Some((0, overflow::Witness::None)),
        }
    );
    let mut bad = response;
    bad.state.0[f::FIRST_ORIGINAL] = 126;
    bad.state.0[f::FIRST_START] = 126;
    bad.state.0[f::FIRST_HIT] = 126;
    bad.state.0[f::UNIQUE] = 2;
    state::validate(bad.state)?;
    assert_eq!(
        checked_match(&request, &bad, &hay, &needle, &[127]),
        Err("established first hit")
    );
    Ok(())
}
