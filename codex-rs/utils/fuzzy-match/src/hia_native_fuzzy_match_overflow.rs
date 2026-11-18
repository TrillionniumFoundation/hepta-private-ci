//! Bind the HIA trace, then preserve the crate's ordinary i32 overflow behavior.

use super::wire::Error;
use super::wire::State;
use super::wire::field as f;
use super::wire::require;
use super::wire::to_u64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Witness {
    None,
    Subtract { lhs: i32, rhs: i32 },
    Add { lhs: i32, rhs: i32 },
}

pub(super) fn validate(state: State, needle_len: usize) -> Result<(i32, Witness), Error> {
    require(
        to_u64(needle_len)? == state[f::NEEDLE_LOWER],
        "score needle length",
    )?;
    let low32 = u64::from(u32::MAX);
    for index in [
        f::SCORE,
        f::OVERFLOW_LHS,
        f::OVERFLOW_RHS,
        f::R1,
        f::R2,
        f::R3,
    ] {
        require(state[index] <= low32, "arithmetic word width")?;
    }
    let mask = state[f::OVERFLOW_MASK];
    require(mask <= 7, "overflow mask")?;
    let first = if mask & 1 != 0 {
        1
    } else if mask & 2 != 0 {
        2
    } else if mask & 4 != 0 {
        3
    } else {
        0
    };
    require(state[f::OVERFLOW_OP] == first, "first overflow stage")?;
    let (lhs, rhs) = match first {
        0 => (0, 0),
        1 => (state[f::LAST_HIT] & low32, state[f::FIRST_START] & low32),
        2 => (state[f::R1], 1),
        3 => (state[f::R2], to_u64(needle_len)? & low32),
        _ => return Err("overflow stage"),
    };
    require(
        state[f::OVERFLOW_LHS] == lhs && state[f::OVERFLOW_RHS] == rhs,
        "overflow operands",
    )?;
    let witness = match first {
        0 => Witness::None,
        1 | 3 => Witness::Subtract {
            lhs: signed_bits(lhs)?,
            rhs: signed_bits(rhs)?,
        },
        2 => Witness::Add {
            lhs: signed_bits(lhs)?,
            rhs: signed_bits(rhs)?,
        },
        _ => return Err("overflow stage"),
    };
    Ok((signed_bits(state[f::SCORE])?, witness))
}

fn signed_bits(value: u64) -> Result<i32, Error> {
    let bits = u32::try_from(value).map_err(|_| "arithmetic word width")?;
    Ok(i32::from_le_bytes(bits.to_le_bytes()))
}

pub(super) fn replay(witness: Witness) {
    // Runtime operands preserve this crate's actual overflow-check policy. The result
    // is deliberately unused: HIA owns the wrapped arithmetic, clamp and final score.
    match witness {
        Witness::None => {}
        Witness::Subtract { lhs, rhs } => {
            let _ = lhs - rhs;
        }
        Witness::Add { lhs, rhs } => {
            let _ = lhs + rhs;
        }
    }
}
