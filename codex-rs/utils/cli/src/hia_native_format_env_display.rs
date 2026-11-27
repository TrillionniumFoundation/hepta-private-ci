//! Ownership and bounded transfers for the HIA environment-display formatter.
//!
//! HIA owns heap control, byte comparisons, masks, separators and the empty
//! result. Rust keeps key references, the index vector and complete Strings.
//! Map values are never read, and each opaque AsRef call stays between the
//! complete map formatting phase and the final join.

use std::collections::HashMap;

use crate::hia_native_format_env_display_wire as wire;
use wire::CHUNK_BYTES;
use wire::NativeResult;
use wire::Operation;

pub(super) fn format_env_display<S: AsRef<str>>(
    env: Option<&HashMap<String, String>>,
    env_vars: &[S],
) -> String {
    match format_parts(env, env_vars) {
        Ok(output) => output,
        Err(reason) => panic!("HIA environment display failed: {reason}"),
    }
}

fn format_parts<S: AsRef<str>>(
    env: Option<&HashMap<String, String>>,
    env_vars: &[S],
) -> NativeResult<String> {
    let keys: Vec<&str> = match env {
        Some(map) => map.keys().map(String::as_str).collect(),
        None => Vec::new(),
    };
    let indices = sorted_indices(&keys)?;
    let mut parts = Vec::new();
    for index in indices {
        let key = keys.get(index).ok_or("sorted key index is out of bounds")?;
        parts.push(mask(key)?);
    }
    for variable in env_vars {
        let value = variable.as_ref();
        parts.push(mask(value)?);
    }
    join(&parts)
}

fn sorted_indices(keys: &[&str]) -> NativeResult<Vec<usize>> {
    let mut indices: Vec<usize> = (0..keys.len()).collect();
    let count = keys.len() as u64;
    let mut result = wire::call(Operation::SortInit, &[], &[count], &[])?;
    loop {
        let (words, tail) = wire::decode::<19>(&result)?;
        if !tail.is_empty() || words[1] != 1 || words[2] != count || words[18] != 0 {
            return Err("native sort result identity is invalid");
        }
        let mut state = [0_u64; 18];
        state.copy_from_slice(&words[1..]);
        match words[0] {
            0 => {
                if state[2] > 1 || state[8] > 1 || state[16] > 1 {
                    return Err("native comparison phase is invalid");
                }
                let left_position = wire::count(state[9])?;
                let right_position = wire::count(state[10])?;
                let left_index = *indices
                    .get(left_position)
                    .ok_or("left comparison position is out of bounds")?;
                let right_index = *indices
                    .get(right_position)
                    .ok_or("right comparison position is out of bounds")?;
                if left_position == right_position || left_index == right_index {
                    return Err("native comparison did not select distinct keys");
                }
                let left = keys[left_index].as_bytes();
                let right = keys[right_index].as_bytes();
                let offset = wire::count(state[11])?;
                let remaining = left
                    .len()
                    .min(right.len())
                    .checked_sub(offset)
                    .ok_or("native comparison offset is out of bounds")?;
                let amount = remaining.min(CHUNK_BYTES);
                let end = offset
                    .checked_add(amount)
                    .ok_or("comparison fragment end overflow")?;
                if state[16] == 0 {
                    if state[11..16] != [0; 5] {
                        return Err("new comparison has a nonempty prefix state");
                    }
                } else if state[12..16]
                    != [
                        left_index as u64,
                        right_index as u64,
                        left.len() as u64,
                        right.len() as u64,
                    ]
                {
                    return Err("comparison changed its bound keys");
                }
                result = wire::call(
                    Operation::SortResume,
                    &state,
                    &[
                        0,
                        left_index as u64,
                        right_index as u64,
                        left.len() as u64,
                        right.len() as u64,
                        amount as u64,
                    ],
                    &[&left[offset..end], &right[offset..end]],
                )?;
            }
            1 => {
                if state[2] > 1 || !matches!(state[8], 2 | 3) {
                    return Err("native swap phase is invalid");
                }
                let left = wire::count(state[9])?;
                let right = wire::count(state[10])?;
                if left >= indices.len() || right >= indices.len() || left == right {
                    return Err("native swap positions are invalid");
                }
                indices.swap(left, right);
                result = wire::call(Operation::SortResume, &state, &[1, 0, 0, 0, 0, 0], &[])?;
            }
            2 => {
                let expected_end = count.min(/*other*/ 1);
                if state[2] != 2
                    || state[3] != 0
                    || state[4] != expected_end
                    || state[5..8] != [0; 3]
                    || state[8] != 4
                    || state[9..] != [0; 9]
                {
                    return Err("native sort completion is invalid");
                }
                return Ok(indices);
            }
            _ => return Err("native sort action is unknown"),
        }
    }
}

fn mask(value: &str) -> NativeResult<String> {
    let total = value.len();
    let expected_length = total
        .checked_add(/*rhs*/ 6)
        .ok_or("masked part length overflow")?;
    let mut state = [total as u64, 0, 0];
    let mut output = Vec::new();
    loop {
        let offset = wire::count(state[1])?;
        let remaining = total
            .checked_sub(offset)
            .ok_or("mask offset is out of bounds")?;
        let amount = remaining.min(CHUNK_BYTES);
        let end = offset
            .checked_add(amount)
            .ok_or("mask fragment end overflow")?;
        let result = wire::call(
            Operation::MaskFragment,
            &state,
            &[amount as u64],
            &[&value.as_bytes()[offset..end]],
        )?;
        let (words, payload) = wire::decode::<4>(&result)?;
        let finished = end == total;
        let expected_payload = amount + if finished { 6 } else { 0 };
        if words[0] != payload.len() as u64
            || payload.len() != expected_payload
            || words[1..] != [total as u64, end as u64, u64::from(finished)]
        {
            return Err("native mask result is invalid");
        }
        output.extend_from_slice(payload);
        state.copy_from_slice(&words[1..]);
        if state[2] == 1 {
            if output.len() != expected_length {
                return Err("native masked part length is invalid");
            }
            return String::from_utf8(output).map_err(|_| "native masked part is not UTF-8");
        }
    }
}

fn join(parts: &[String]) -> NativeResult<String> {
    let count = parts.len() as u64;
    let result = wire::call(Operation::JoinInit, &[], &[count], &[])?;
    let (words, payload) = wire::decode::<8>(&result)?;
    let expected_state = if parts.is_empty() {
        [0, 0, 0, 0, 1, 0, 1]
    } else {
        [count, 0, 0, 0, 0, 0, 0]
    };
    if words[0] != payload.len() as u64 || words[1..] != expected_state {
        return Err("native join initialization is invalid");
    }
    if parts.is_empty() {
        if payload != b"-" {
            return Err("native empty display is invalid");
        }
        return String::from_utf8(payload.to_vec())
            .map_err(|_| "native empty display is not UTF-8");
    }
    if !payload.is_empty() {
        return Err("native join started with unexpected bytes");
    }
    let mut state = expected_state;
    let mut output = Vec::new();
    while state[6] == 0 {
        let index = wire::count(state[1])?;
        let part = parts
            .get(index)
            .ok_or("native join index is out of bounds")?;
        let offset = wire::count(state[3])?;
        let remaining = part
            .len()
            .checked_sub(offset)
            .ok_or("join offset is out of bounds")?;
        let amount = remaining.min(CHUNK_BYTES);
        let end = offset
            .checked_add(amount)
            .ok_or("join fragment end overflow")?;
        let result = wire::call(
            Operation::JoinFragment,
            &state,
            &[part.len() as u64, amount as u64],
            &[&part.as_bytes()[offset..end]],
        )?;
        let (words, payload) = wire::decode::<8>(&result)?;
        let separator = usize::from(state[5] == 0 && index > 0) * 2;
        let expected_payload = amount
            .checked_add(separator)
            .ok_or("join fragment payload overflow")?;
        let new_length = output
            .len()
            .checked_add(expected_payload)
            .ok_or("joined display length overflow")?;
        let expected_state = if end == part.len() {
            let next = index.checked_add(/*rhs*/ 1).ok_or("join index overflow")?;
            [
                count,
                next as u64,
                0,
                0,
                new_length as u64,
                0,
                u64::from(next == parts.len()),
            ]
        } else {
            [
                count,
                index as u64,
                part.len() as u64,
                end as u64,
                new_length as u64,
                1,
                0,
            ]
        };
        if words[0] != payload.len() as u64
            || payload.len() != expected_payload
            || words[1..] != expected_state
        {
            return Err("native join result is invalid");
        }
        output.extend_from_slice(payload);
        state.copy_from_slice(&words[1..]);
    }
    String::from_utf8(output).map_err(|_| "native joined display is not UTF-8")
}
