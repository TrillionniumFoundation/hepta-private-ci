use codex_hepta_types::FixedQ32;

use crate::NduError;

const SCALE: i128 = 1_i128 << 32;
const HALF_SCALE: i128 = SCALE / 2;

/// Multiplies two signed Q32 values with round-to-nearest, ties-to-even.
pub fn mul_q32_ties_even(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, NduError> {
    let product = i128::from(left.raw()) * i128::from(right.raw());
    let negative = product.is_negative();
    let magnitude = product.checked_abs().ok_or(NduError::Arithmetic)?;
    let mut quotient = magnitude / SCALE;
    let remainder = magnitude % SCALE;
    if remainder > HALF_SCALE || (remainder == HALF_SCALE && quotient % 2 == 1) {
        quotient = quotient.checked_add(1).ok_or(NduError::Arithmetic)?;
    }
    let signed = if negative { -quotient } else { quotient };
    let raw = i64::try_from(signed).map_err(|_| NduError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

#[cfg(test)]
#[path = "fixed_tests.rs"]
mod tests;
