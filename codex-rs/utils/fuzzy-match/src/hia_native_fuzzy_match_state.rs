//! Canonical state shapes and immutable-word transitions, without matching logic.

use super::wire;
use super::wire::Error;
use super::wire::Operation;
use super::wire::Request;
use super::wire::Response;
use super::wire::State;
use super::wire::field as f;
use super::wire::require;
use super::wire::to_u64;

const HIT_FIELDS: [usize; 7] = [
    f::LAST_START,
    f::FIRST_ORIGINAL,
    f::FIRST_START,
    f::LAST_HIT,
    f::LAST_ORIGINAL,
    f::UNIQUE,
    f::FIRST_HIT,
];

pub(super) fn validate(state: State) -> Result<(), Error> {
    let s = state;
    require(s[f::PHASE] <= wire::DONE, "state phase")?;
    require(s[f::OUTCOME] <= wire::NONE, "state outcome")?;
    require(
        s[f::PREVIOUS_CASED] <= 1 && s[f::SIGMA_PENDING] <= 1,
        "state boolean",
    )?;
    require(
        s[f::PREVIOUS_CASED] == 0 || s[f::NEEDLE_ORIGINAL] > 0,
        "empty needle context",
    )?;
    require(s[f::HAY_SEEN] <= s[f::HAY_TOTAL], "hay byte frontier")?;
    require(
        s[f::NEEDLE_SEEN] <= s[f::NEEDLE_TOTAL],
        "needle byte frontier",
    )?;
    for (seen, original, lower) in [
        (s[f::HAY_SEEN], s[f::HAY_ORIGINAL], s[f::HAY_LOWER]),
        (s[f::NEEDLE_SEEN], s[f::NEEDLE_ORIGINAL], s[f::NEEDLE_LOWER]),
    ] {
        require(
            original <= seen
                && original >= seen.div_ceil(wire::UTF8_SCALAR_BYTES)
                && lower >= original
                && original >= lower.div_ceil(wire::MAPPING_SLOTS)
                && (seen == 0) == (original == 0)
                && (original == 0) == (lower == 0),
            "normalization counts",
        )?;
    }
    if s[f::SIGMA_PENDING] == 0 {
        require(s[f::SIGMA_SLOT] == 0, "absent sigma slot")?;
    } else {
        require(
            s[f::PREVIOUS_CASED] == 1
                && s[f::NEEDLE_ORIGINAL] >= 2
                && s[f::SIGMA_SLOT] > 0
                && s[f::SIGMA_SLOT] < s[f::NEEDLE_LOWER],
            "pending sigma shape",
        )?;
    }
    require(
        s[f::HAY_CURSOR] <= s[f::HAY_LOWER]
            && s[f::NEEDLE_CURSOR] <= s[f::NEEDLE_LOWER]
            && s[f::NEEDLE_CURSOR] <= s[f::HAY_CURSOR],
        "match cursors",
    )?;
    if s[f::NEEDLE_CURSOR] == 0 {
        require(HIT_FIELDS.iter().all(|index| s[*index] == 0), "absent hit")?;
    } else {
        require(
            s[f::UNIQUE] > 0
                && s[f::UNIQUE] <= s[f::NEEDLE_CURSOR]
                && s[f::FIRST_ORIGINAL] <= s[f::LAST_ORIGINAL]
                && s[f::LAST_ORIGINAL] < s[f::HAY_ORIGINAL]
                && s[f::FIRST_START] <= s[f::FIRST_HIT]
                && s[f::FIRST_HIT] <= s[f::LAST_HIT]
                && s[f::LAST_HIT] < s[f::HAY_CURSOR]
                && s[f::FIRST_START] <= s[f::LAST_START],
            "hit order",
        )?;
        for (original, start, hit) in [
            (s[f::FIRST_ORIGINAL], s[f::FIRST_START], s[f::FIRST_HIT]),
            (s[f::LAST_ORIGINAL], s[f::LAST_START], s[f::LAST_HIT]),
        ] {
            require(
                original <= start
                    && original >= start.div_ceil(wire::MAPPING_SLOTS)
                    && start <= hit
                    && hit - start < wire::MAPPING_SLOTS,
                "hit expansion bounds",
            )?;
        }
        require(
            s[f::NEEDLE_CURSOR] <= s[f::LAST_HIT] - s[f::FIRST_HIT] + 1
                && s[f::UNIQUE] <= s[f::LAST_ORIGINAL] - s[f::FIRST_ORIGINAL] + 1,
            "hit count bounds",
        )?;
        if s[f::FIRST_ORIGINAL] == s[f::LAST_ORIGINAL] {
            require(
                s[f::FIRST_START] == s[f::LAST_START] && s[f::UNIQUE] == 1,
                "single original match",
            )?;
        } else {
            require(s[f::UNIQUE] >= 2, "distinct original matches")?;
        }
        if s[f::NEEDLE_CURSOR] == 1 {
            require(
                s[f::FIRST_HIT] == s[f::LAST_HIT]
                    && s[f::FIRST_ORIGINAL] == s[f::LAST_ORIGINAL]
                    && s[f::FIRST_START] == s[f::LAST_START]
                    && s[f::UNIQUE] == 1,
                "single hit anchors",
            )?;
        }
    }
    if s[f::HAY_CURSOR] == 0 {
        require(
            s[f::SCANNED_ORIGINAL] == 0 && s[f::SCANNED_START] == 0,
            "absent scan",
        )?;
    } else {
        let last = s[f::HAY_CURSOR] - 1;
        require(
            s[f::SCANNED_ORIGINAL] < s[f::HAY_ORIGINAL]
                && s[f::SCANNED_ORIGINAL] <= s[f::SCANNED_START]
                && s[f::SCANNED_ORIGINAL] >= s[f::SCANNED_START].div_ceil(wire::MAPPING_SLOTS)
                && s[f::SCANNED_START] <= last
                && last - s[f::SCANNED_START] < wire::MAPPING_SLOTS,
            "scanned record shape",
        )?;
        if s[f::HAY_CURSOR] == s[f::HAY_LOWER] {
            require(
                s[f::SCANNED_ORIGINAL] == s[f::HAY_ORIGINAL] - 1,
                "last original scan",
            )?;
        }
    }
    if s[f::NEEDLE_CURSOR] > 0 {
        require(
            s[f::LAST_ORIGINAL] <= s[f::SCANNED_ORIGINAL]
                && s[f::LAST_START] <= s[f::SCANNED_START],
            "hit scan order",
        )?;
        if s[f::LAST_ORIGINAL] == s[f::SCANNED_ORIGINAL] {
            require(s[f::LAST_START] == s[f::SCANNED_START], "hit scan identity")?;
        }
    }
    for index in [
        f::SCORE,
        f::OVERFLOW_LHS,
        f::OVERFLOW_RHS,
        f::R1,
        f::R2,
        f::R3,
    ] {
        require(s[index] <= u64::from(u32::MAX), "i32 word width")?;
    }
    require(
        s[f::OVERFLOW_OP] <= 3 && s[f::OVERFLOW_MASK] <= 7,
        "overflow descriptor",
    )?;
    let no_result = s.0[f::SCORE..=f::R3].iter().all(|word| *word == 0) && s[f::OVERFLOW_MASK] == 0;
    match s[f::PHASE] {
        wire::FRESH => require(s == State::INITIAL, "fresh state")?,
        wire::HAYSTACK | wire::NEEDLE => {
            require(
                s[f::NEEDLE_TOTAL] > 0 && s[f::OUTCOME] == wire::CONTINUE,
                "normalizing phase",
            )?;
            require(
                s.0[f::HAY_CURSOR..].iter().all(|word| *word == 0),
                "early match state",
            )?;
            if s[f::PHASE] == wire::HAYSTACK {
                require(
                    s[f::HAY_SEEN] < s[f::HAY_TOTAL] || s[f::HAY_TOTAL] == 0,
                    "hay phase frontier",
                )?;
                require(
                    [f::NEEDLE_SEEN, f::NEEDLE_ORIGINAL, f::NEEDLE_LOWER]
                        .iter()
                        .all(|index| s[*index] == 0)
                        && s.0[f::PREVIOUS_CASED..=f::SIGMA_SLOT]
                            .iter()
                            .all(|word| *word == 0),
                    "hay precedes needle",
                )?;
            } else {
                require(
                    s[f::HAY_SEEN] == s[f::HAY_TOTAL] && s[f::NEEDLE_SEEN] < s[f::NEEDLE_TOTAL],
                    "needle phase frontier",
                )?;
            }
        }
        wire::MATCHING | wire::DONE => {
            if s[f::NEEDLE_TOTAL] == 0 {
                let mut empty = State::INITIAL;
                empty.0[f::PHASE] = wire::DONE;
                empty.0[f::HAY_TOTAL] = s[f::HAY_TOTAL];
                empty.0[f::OUTCOME] = wire::SOME;
                empty.0[f::SCORE] = i32::MAX as u64;
                return require(s == empty, "empty result shape");
            }
            require(
                s[f::HAY_SEEN] == s[f::HAY_TOTAL]
                    && s[f::NEEDLE_SEEN] == s[f::NEEDLE_TOTAL]
                    && s[f::NEEDLE_LOWER] > 0
                    && s.0[f::PREVIOUS_CASED..=f::SIGMA_SLOT]
                        .iter()
                        .all(|word| *word == 0),
                "completed normalization",
            )?;
            match s[f::OUTCOME] {
                wire::CONTINUE => require(
                    s[f::PHASE] == wire::MATCHING
                        && s[f::NEEDLE_CURSOR] < s[f::NEEDLE_LOWER]
                        && no_result,
                    "continue shape",
                )?,
                wire::SOME => require(
                    s[f::PHASE] == wire::DONE
                        && s[f::NEEDLE_CURSOR] == s[f::NEEDLE_LOWER]
                        && s[f::HAY_CURSOR] > 0
                        && s[f::HAY_CURSOR] - 1 == s[f::LAST_HIT]
                        && s[f::SCANNED_ORIGINAL] == s[f::LAST_ORIGINAL]
                        && s[f::SCANNED_START] == s[f::LAST_START],
                    "some shape",
                )?,
                wire::NONE => require(
                    s[f::PHASE] == wire::DONE
                        && s[f::HAY_CURSOR] == s[f::HAY_LOWER]
                        && s[f::NEEDLE_CURSOR] < s[f::NEEDLE_LOWER]
                        && no_result,
                    "none shape",
                )?,
                _ => return Err("state outcome"),
            }
        }
        _ => return Err("state phase"),
    }
    Ok(())
}

pub(super) fn validate_request(request: &Request<'_>, totals: (u64, u64)) -> Result<(), Error> {
    validate(request.state)?;
    let s = request.state;
    require(
        request.payload.len() <= wire::FRAME_BYTES,
        "request payload bound",
    )?;
    if request.operation == Operation::Begin {
        return require(
            s == State::INITIAL
                && request.flags == 0
                && request.payload.is_empty()
                && (request.argument_a, request.argument_b) == totals,
            "begin input",
        );
    }
    require(
        (s[f::HAY_TOTAL], s[f::NEEDLE_TOTAL]) == totals,
        "original byte totals",
    )?;
    match request.operation {
        Operation::LowerHaystack | Operation::LowerNeedle => {
            let (phase, total, seen) = if request.operation == Operation::LowerHaystack {
                (wire::HAYSTACK, s[f::HAY_TOTAL], s[f::HAY_SEEN])
            } else {
                (wire::NEEDLE, s[f::NEEDLE_TOTAL], s[f::NEEDLE_SEEN])
            };
            let count = to_u64(request.payload.len())?;
            require(
                s[f::PHASE] == phase && count <= total - seen,
                "normalization input phase",
            )?;
            require(
                count > 0 || (phase == wire::HAYSTACK && total == 0),
                "empty normalization frame",
            )?;
            require(
                request.argument_a == 0 && request.argument_b == 0,
                "normalization arguments",
            )?;
            let end = if count == total - seen { wire::END } else { 0 };
            require(request.flags == end, "normalization end flag")?;
            std::str::from_utf8(request.payload).map_err(|_| "input UTF8")?;
        }
        Operation::Match => {
            require(
                s[f::PHASE] == wire::MATCHING && request.flags == 0,
                "match input phase",
            )?;
            let limit = to_u64(wire::WINDOW_RECORDS)?;
            let hay = (s[f::HAY_LOWER] - s[f::HAY_CURSOR]).min(limit);
            let needle = (s[f::NEEDLE_LOWER] - s[f::NEEDLE_CURSOR]).min(limit);
            require(
                request.argument_a == hay
                    && request.argument_b == needle
                    && to_u64(request.payload.len())? == hay * 24 + needle * 8,
                "match input windows",
            )?;
        }
        Operation::Begin => return Err("begin state"),
    }
    Ok(())
}

pub(super) fn validate_transition(request: &Request<'_>, response: &Response) -> Result<(), Error> {
    let old = request.state;
    let next = response.state;
    validate(next)?;
    let mutable: &[usize] = match request.operation {
        Operation::Begin => &[0, 1, 2, 20, 21],
        Operation::LowerHaystack => &[0, 3, 5, 6],
        Operation::LowerNeedle => &[0, 4, 7, 8, 9, 10, 11],
        Operation::Match => &[
            0, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
        ],
    };
    for (index, (before, after)) in old.0.iter().zip(next.0.iter()).enumerate() {
        require(
            mutable.contains(&index) || before == after,
            "immutable state word",
        )?;
    }
    match request.operation {
        Operation::Begin => {
            let mut expected = State::INITIAL;
            expected.0[f::HAY_TOTAL] = request.argument_a;
            expected.0[f::NEEDLE_TOTAL] = request.argument_b;
            expected.0[f::PHASE] = wire::HAYSTACK;
            if request.argument_b == 0 {
                expected.0[f::PHASE] = wire::DONE;
                expected.0[f::OUTCOME] = wire::SOME;
                expected.0[f::SCORE] = i32::MAX as u64;
            }
            require(next == expected, "begin transition")?;
            require(
                response.advance_a == 0 && response.advance_b == 0,
                "begin advance",
            )?;
        }
        Operation::LowerHaystack | Operation::LowerNeedle => {
            let count = to_u64(request.payload.len())?;
            require(
                response.advance_a == count && response.advance_b == 0,
                "normalization advance",
            )?;
            let (seen, current_phase, final_phase) =
                if request.operation == Operation::LowerHaystack {
                    (f::HAY_SEEN, wire::HAYSTACK, wire::NEEDLE)
                } else {
                    (f::NEEDLE_SEEN, wire::NEEDLE, wire::MATCHING)
                };
            require(
                next[seen]
                    == old[seen]
                        .checked_add(count)
                        .ok_or("byte frontier overflow")?,
                "byte advance",
            )?;
            let phase = if request.flags == wire::END {
                final_phase
            } else {
                current_phase
            };
            require(next[f::PHASE] == phase, "normalization next phase")?;
        }
        Operation::Match => {
            require(
                response.advance_a <= request.argument_a
                    && response.advance_b <= request.argument_b
                    && response.advance_b <= response.advance_a
                    && next[f::HAY_CURSOR].checked_sub(old[f::HAY_CURSOR])
                        == Some(response.advance_a)
                    && next[f::NEEDLE_CURSOR].checked_sub(old[f::NEEDLE_CURSOR])
                        == Some(response.advance_b),
                "match advance",
            )?;
            if response.advance_a == 0 {
                require(
                    next[f::SCANNED_ORIGINAL] == old[f::SCANNED_ORIGINAL]
                        && next[f::SCANNED_START] == old[f::SCANNED_START],
                    "unchanged scan",
                )?;
            }
            if response.advance_b == 0 {
                require(
                    HIT_FIELDS.iter().all(|index| next[*index] == old[*index]),
                    "unchanged hits",
                )?;
            } else {
                require(
                    next[f::LAST_HIT] >= old[f::HAY_CURSOR]
                        && next[f::LAST_HIT] < next[f::HAY_CURSOR],
                    "new last hit",
                )?;
                if old[f::NEEDLE_CURSOR] == 0 {
                    require(
                        next[f::FIRST_HIT] >= old[f::HAY_CURSOR]
                            && next[f::FIRST_HIT] < next[f::HAY_CURSOR],
                        "new first hit",
                    )?;
                } else {
                    require(next[f::LAST_HIT] > old[f::LAST_HIT], "advancing last hit")?;
                }
            }
            if old[f::NEEDLE_CURSOR] > 0 {
                require(
                    [f::FIRST_ORIGINAL, f::FIRST_START, f::FIRST_HIT]
                        .iter()
                        .all(|index| next[*index] == old[*index]),
                    "established first hit",
                )?;
            }
            if next[f::OUTCOME] == wire::CONTINUE {
                require(
                    response.advance_a > 0
                        && (response.advance_a == request.argument_a
                            || response.advance_b == request.argument_b),
                    "match progress",
                )?;
            }
        }
    }
    Ok(())
}
