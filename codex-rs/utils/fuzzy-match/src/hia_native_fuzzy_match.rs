//! Container ownership and bounded transport for the complete HIA fuzzy matcher.

#[path = "hia_native_fuzzy_match_matching.rs"]
mod matching;
#[path = "hia_native_fuzzy_match_normalize.rs"]
mod normalize;
#[path = "hia_native_fuzzy_match_overflow.rs"]
mod overflow;
#[path = "hia_native_fuzzy_match_state.rs"]
mod state;
#[path = "hia_native_fuzzy_match_wire.rs"]
mod wire;

use wire::Error;
use wire::Operation;
use wire::Request;
use wire::Response;
use wire::State;
use wire::field as f;
use wire::require;
use wire::to_u64;
use wire::to_usize;

unsafe extern "C" {
    fn codex_hia_fuzzy_match(
        source: *const u8,
        source_len: usize,
        output: *mut u8,
        output_len: usize,
        workspace: *mut u8,
        workspace_len: usize,
    ) -> u64;
}

pub fn fuzzy_match(haystack: &str, needle: &str) -> Option<(Vec<usize>, i32)> {
    match run(haystack, needle) {
        Ok(result) => result,
        Err(error) => panic!("HIA fuzzy matcher: {error}"),
    }
}

fn run(haystack: &str, needle: &str) -> Result<Option<(Vec<usize>, i32)>, Error> {
    let totals = (to_u64(haystack.len())?, to_u64(needle.len())?);
    let request = Request {
        operation: Operation::Begin,
        flags: 0,
        state: State::INITIAL,
        argument_a: totals.0,
        argument_b: totals.1,
        payload: &[],
    };
    let begin = invoke(&request, totals)?;
    if begin.state[f::PHASE] == wire::DONE {
        let score = i32::try_from(begin.state[f::SCORE]).map_err(|_| "empty score")?;
        return Ok(Some((Vec::new(), score)));
    }

    // Empty was decided by HIA before any normalization traversal or container growth.
    let mut current = begin.state;
    let mut hay = Vec::new();
    let mut lowered_needle = Vec::new();
    while current[f::PHASE] == wire::HAYSTACK {
        let request = normalization_request(Operation::LowerHaystack, current, haystack)?;
        let response = invoke(&request, totals)?;
        let records = normalize::decode_hay(&request, &response, &hay)?;
        hay.extend(records);
        current = response.state;
    }
    while current[f::PHASE] == wire::NEEDLE {
        let request = normalization_request(Operation::LowerNeedle, current, needle)?;
        let response = invoke(&request, totals)?;
        let commands = normalize::decode_needle(&request, &response, &lowered_needle)?;
        normalize::apply_needle(commands, &mut lowered_needle);
        current = response.state;
    }
    let mut indices = Vec::new();
    while current[f::PHASE] == wire::MATCHING {
        let hay_remaining = hay
            .get(to_usize(current[f::HAY_CURSOR])?..)
            .ok_or("hay cursor range")?;
        let needle_remaining = lowered_needle
            .get(to_usize(current[f::NEEDLE_CURSOR])?..)
            .ok_or("needle cursor range")?;
        let hay_window = &hay_remaining[..hay_remaining.len().min(wire::WINDOW_RECORDS)];
        let needle_window = &needle_remaining[..needle_remaining.len().min(wire::WINDOW_RECORDS)];
        let mut payload = Vec::with_capacity(
            hay_window.len() * wire::HAY_RECORD_BYTES + needle_window.len() * wire::WORD_BYTES,
        );
        for record in hay_window {
            for word in [u64::from(record.scalar), record.original, record.start] {
                payload.extend_from_slice(&word.to_le_bytes());
            }
        }
        for scalar in needle_window {
            payload.extend_from_slice(&u64::from(*scalar).to_le_bytes());
        }
        let request = Request {
            operation: Operation::Match,
            flags: 0,
            state: current,
            argument_a: to_u64(hay_window.len())?,
            argument_b: to_u64(needle_window.len())?,
            payload: &payload,
        };
        let response = invoke(&request, totals)?;
        let frame = matching::decode(&request, &response, &hay, &lowered_needle, &indices)?;
        match response.state[f::OUTCOME] {
            wire::NONE => return Ok(None),
            wire::SOME => {
                let (score, witness) = frame.terminal.ok_or("missing score trace")?;
                indices.extend(frame.indices);
                overflow::replay(witness);
                return Ok(Some((indices, score)));
            }
            wire::CONTINUE => {
                require(frame.terminal.is_none(), "early score trace")?;
                indices.extend(frame.indices);
                current = response.state;
            }
            _ => return Err("match outcome"),
        }
    }
    Err("unexpected fuzzy phase")
}

fn normalization_request(
    operation: Operation,
    state: State,
    original: &str,
) -> Result<Request<'_>, Error> {
    let seen = match operation {
        Operation::LowerHaystack => state[f::HAY_SEEN],
        Operation::LowerNeedle => state[f::NEEDLE_SEEN],
        Operation::Begin | Operation::Match => return Err("normalization operation"),
    };
    let remaining = original
        .get(to_usize(seen)?..)
        .ok_or("original byte boundary")?;
    let mut end = remaining.len().min(wire::FRAME_BYTES);
    while !remaining.is_char_boundary(end) {
        end -= 1;
    }
    Ok(Request {
        operation,
        flags: if end == remaining.len() { wire::END } else { 0 },
        state,
        argument_a: 0,
        argument_b: 0,
        payload: &remaining.as_bytes()[..end],
    })
}

fn invoke(request: &Request<'_>, totals: (u64, u64)) -> Result<Response, Error> {
    state::validate_request(request, totals)?;
    let source = request.encode()?;
    let mut output = vec![0; request.capacity()?];
    let mut workspace = [0; 1];
    // The three buffers are separate live allocations for this synchronous borrowed
    // call. No pointer is retained. Decode checks the complete u64 wrapper return.
    let returned = unsafe {
        codex_hia_fuzzy_match(
            source.as_ptr(),
            source.len(),
            output.as_mut_ptr(),
            output.len(),
            workspace.as_mut_ptr(),
            workspace.len(),
        )
    };
    require(workspace == [0], "workspace mutation")?;
    let response = wire::decode(request, returned, &output)?;
    state::validate_transition(request, &response)?;
    Ok(response)
}

#[cfg(test)]
#[path = "hia_native_fuzzy_match_transition_tests.rs"]
mod transition_tests;
#[cfg(test)]
#[path = "hia_native_fuzzy_match_wire_tests.rs"]
mod wire_tests;
