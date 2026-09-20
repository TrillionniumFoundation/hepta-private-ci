use std::error::Error;
use std::fmt;

const SCALE: i128 = 1_i128 << 32;

/// Signed Q32 fixed-point value with checked deterministic arithmetic.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FixedQ32(i64);

impl FixedQ32 {
    pub const ZERO: Self = Self(0);
    pub const ONE: Self = Self(1_i64 << 32);

    pub const fn from_raw(raw: i64) -> Self {
        Self(raw)
    }

    pub const fn raw(self) -> i64 {
        self.0
    }

    pub fn checked_add(self, other: Self) -> Result<Self, FixedQ32Error> {
        self.0
            .checked_add(other.0)
            .map(Self)
            .ok_or(FixedQ32Error::Overflow)
    }

    pub fn checked_sub(self, other: Self) -> Result<Self, FixedQ32Error> {
        self.0
            .checked_sub(other.0)
            .map(Self)
            .ok_or(FixedQ32Error::Overflow)
    }

    pub fn checked_mul(self, other: Self) -> Result<Self, FixedQ32Error> {
        let product = i128::from(self.0) * i128::from(other.0);
        let scaled = product / SCALE;
        i64::try_from(scaled)
            .map(Self)
            .map_err(|_| FixedQ32Error::Overflow)
    }

    pub fn checked_div(self, other: Self) -> Result<Self, FixedQ32Error> {
        if other.0 == 0 {
            return Err(FixedQ32Error::DivisionByZero);
        }
        let numerator = i128::from(self.0) * SCALE;
        let quotient = numerator / i128::from(other.0);
        i64::try_from(quotient)
            .map(Self)
            .map_err(|_| FixedQ32Error::Overflow)
    }

    pub fn clamp(self, minimum: Self, maximum: Self) -> Result<Self, FixedQ32Error> {
        if minimum > maximum {
            return Err(FixedQ32Error::InvalidRange);
        }
        Ok(Self(self.0.clamp(minimum.0, maximum.0)))
    }
}

/// Unsigned Q32 probability in the closed interval `[0, 1]`.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ProbabilityQ32(u64);

impl ProbabilityQ32 {
    pub const ZERO: Self = Self(0);
    pub const ONE: Self = Self(1_u64 << 32);

    pub fn from_raw(raw: u64) -> Result<Self, FixedQ32Error> {
        if raw > Self::ONE.0 {
            return Err(FixedQ32Error::ProbabilityOutOfRange(raw));
        }
        Ok(Self(raw))
    }

    pub const fn raw(self) -> u64 {
        self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FixedQ32Error {
    Overflow,
    DivisionByZero,
    InvalidRange,
    ProbabilityOutOfRange(u64),
}

impl fmt::Display for FixedQ32Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Overflow => formatter.write_str("Q32 arithmetic overflow"),
            Self::DivisionByZero => formatter.write_str("Q32 division by zero"),
            Self::InvalidRange => formatter.write_str("Q32 clamp range is inverted"),
            Self::ProbabilityOutOfRange(raw) => {
                write!(formatter, "Q32 probability is outside [0, 1]: {raw}")
            }
        }
    }
}

impl Error for FixedQ32Error {}

#[cfg(test)]
#[path = "fixed_tests.rs"]
mod tests;
