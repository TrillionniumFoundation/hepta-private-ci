//! Finite-precision certificates for ESS of the original propensity ratios.

use super::OpeError;
use super::SCALE;
use super::scaled_ratio;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PropensityRatio {
    pub(crate) evaluation: u64,
    pub(crate) behavior: u64,
}

impl PropensityRatio {
    pub(crate) fn same_positive_ratio(self, other: Self) -> bool {
        self.evaluation > 0
            && other.evaluation > 0
            && self.behavior > 0
            && other.behavior > 0
            && u128::from(self.evaluation) * u128::from(other.behavior)
                == u128::from(other.evaluation) * u128::from(self.behavior)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct WeightBounds {
    pub(crate) lower: i128,
    pub(crate) upper: i128,
}

impl WeightBounds {
    pub(crate) const UNIT: Self = Self {
        lower: SCALE,
        upper: SCALE,
    };

    pub(crate) fn advance(self, ratio: PropensityRatio) -> Result<Self, OpeError> {
        let evaluation = i128::from(ratio.evaluation);
        let behavior = i128::from(ratio.behavior);
        if self.lower < 0
            || self.upper < self.lower
            || evaluation > SCALE
            || !(1..=SCALE).contains(&behavior)
        {
            return Err(OpeError::Arithmetic);
        }
        let lower = self
            .lower
            .checked_mul(evaluation)
            .ok_or(OpeError::Arithmetic)?;
        let upper = self
            .upper
            .checked_mul(evaluation)
            .ok_or(OpeError::Arithmetic)?;
        Ok(Self {
            lower: lower / behavior,
            upper: (upper / behavior)
                .checked_add(i128::from(upper % behavior != 0))
                .ok_or(OpeError::Arithmetic)?,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SupportCertification {
    Supported,
    Insufficient,
    RequiresEquality,
    Unresolved,
}

#[derive(Default)]
pub(crate) struct SupportAccumulator {
    count: i128,
    lower_sum: i128,
    upper_sum: i128,
    lower_squares: i128,
    upper_squares: i128,
}

impl SupportAccumulator {
    pub(crate) fn add(&mut self, bounds: WeightBounds) -> Result<(), OpeError> {
        if bounds.lower < 0 || bounds.upper < bounds.lower {
            return Err(OpeError::Arithmetic);
        }
        self.count = self.count.checked_add(1).ok_or(OpeError::Arithmetic)?;
        self.lower_sum = self
            .lower_sum
            .checked_add(bounds.lower)
            .ok_or(OpeError::Arithmetic)?;
        self.upper_sum = self
            .upper_sum
            .checked_add(bounds.upper)
            .ok_or(OpeError::Arithmetic)?;
        self.lower_squares = bounds
            .lower
            .checked_mul(bounds.lower)
            .and_then(|square| self.lower_squares.checked_add(square))
            .ok_or(OpeError::Arithmetic)?;
        self.upper_squares = bounds
            .upper
            .checked_mul(bounds.upper)
            .and_then(|square| self.upper_squares.checked_add(square))
            .ok_or(OpeError::Arithmetic)?;
        Ok(())
    }

    pub(crate) fn certify(&self, minimum: i128) -> Result<SupportCertification, OpeError> {
        let maximum = self.count.checked_mul(SCALE).ok_or(OpeError::Arithmetic)?;
        if minimum > maximum || self.upper_squares == 0 {
            return Ok(SupportCertification::Insufficient);
        }
        // OPE caps n at 10^6 and U at 50*S: squared sums stay below 2^116
        // and sums of squares below 2^96. Sequential limits are smaller.
        // Every original weight lies in [L/S,U/S]. Nonnegative sums and
        // squares give (sum L)^2/sum U^2 <= true ESS <= (sum U)^2/sum L^2.
        // At the maximum ESS=n, Cauchy equality can resolve the exact tie.
        let lower_square = self
            .lower_sum
            .checked_mul(self.lower_sum)
            .ok_or(OpeError::Arithmetic)?;
        if scaled_ratio(lower_square, self.upper_squares)?.floor >= minimum {
            return Ok(SupportCertification::Supported);
        }
        if minimum == maximum {
            return Ok(SupportCertification::RequiresEquality);
        }
        if self.lower_squares > 0 {
            let upper_square = self
                .upper_sum
                .checked_mul(self.upper_sum)
                .ok_or(OpeError::Arithmetic)?;
            // ESS never exceeds n. A very wide UB can overflow its Q32
            // representation, but UB>=n cannot prove failure below n anyway.
            let maximum_square = self
                .count
                .checked_mul(self.lower_squares)
                .ok_or(OpeError::Arithmetic)?;
            if upper_square < maximum_square
                && scaled_ratio(upper_square, self.lower_squares)?.floor < minimum
            {
                return Ok(SupportCertification::Insufficient);
            }
        }
        Ok(SupportCertification::Unresolved)
    }
}

// Each horizon<=128 equality cross-product contains 2*h probability factors,
// each <=2^32. The endpoint 2^8192 needs 8193 bits, or exactly 129 u64 limbs.
// This fixed capacity proves equality only; it never represents arbitrary ESS.
const PRODUCT_LIMBS: usize = 129;

struct FixedProduct {
    limbs: [u64; PRODUCT_LIMBS],
    len: usize,
}

impl FixedProduct {
    fn one() -> Self {
        let mut limbs = [0; PRODUCT_LIMBS];
        limbs[0] = 1;
        Self { limbs, len: 1 }
    }

    fn multiply(&mut self, factor: u64) -> Result<(), OpeError> {
        if i128::from(factor) > SCALE {
            return Err(OpeError::Arithmetic);
        }
        if factor == 0 {
            self.len = 0;
            return Ok(());
        }
        let mut carry = 0_u128;
        for limb in &mut self.limbs[..self.len] {
            let product = u128::from(*limb) * u128::from(factor) + carry;
            *limb = product as u64;
            carry = product >> 64;
        }
        if carry != 0 {
            let next = self.limbs.get_mut(self.len).ok_or(OpeError::Arithmetic)?;
            *next = u64::try_from(carry).map_err(|_| OpeError::Arithmetic)?;
            self.len += 1;
        }
        Ok(())
    }
}

pub(crate) struct RatioProductEquality {
    left: FixedProduct,
    right: FixedProduct,
}

impl RatioProductEquality {
    pub(crate) fn new() -> Self {
        Self {
            left: FixedProduct::one(),
            right: FixedProduct::one(),
        }
    }

    pub(crate) fn advance(
        &mut self,
        left: PropensityRatio,
        right: PropensityRatio,
    ) -> Result<(), OpeError> {
        if left.behavior == 0 || right.behavior == 0 {
            return Err(OpeError::Arithmetic);
        }
        self.left.multiply(left.evaluation)?;
        self.left.multiply(right.behavior)?;
        self.right.multiply(right.evaluation)?;
        self.right.multiply(left.behavior)?;
        Ok(())
    }

    pub(crate) fn equal_positive(&self) -> bool {
        self.left.len > 0
            && self.left.len == self.right.len
            && self.left.limbs[..self.left.len] == self.right.limbs[..self.right.len]
    }
}

#[cfg(test)]
#[path = "ope_support_tests.rs"]
mod tests;
