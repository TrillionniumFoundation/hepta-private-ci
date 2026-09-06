use std::error::Error;
use std::fmt;

use crate::Digest32;

/// Native engineering conventions, not production profile registrations.
/// These names do not change the legacy `FixedQ32` arithmetic methods.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NumericProfileV1 {
    HnmfPpmTowardZero,
    SignedQ24NearestTiesEven,
    SignedQ32NearestTiesEven,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NumericRoundingV1 {
    TowardZero,
    NearestTiesEven,
}

impl NumericProfileV1 {
    pub fn from_id(id: &str) -> Result<Self, NumericConversionError> {
        match id {
            "hnmf-ppm-toward-zero-v1" => Ok(Self::HnmfPpmTowardZero),
            "signed-q24-nearest-ties-even-v1" => Ok(Self::SignedQ24NearestTiesEven),
            "signed-q32-nearest-ties-even-v1" => Ok(Self::SignedQ32NearestTiesEven),
            _ => Err(NumericConversionError::UnknownProfile),
        }
    }

    pub const fn id(self) -> &'static str {
        match self {
            Self::HnmfPpmTowardZero => "hnmf-ppm-toward-zero-v1",
            Self::SignedQ24NearestTiesEven => "signed-q24-nearest-ties-even-v1",
            Self::SignedQ32NearestTiesEven => "signed-q32-nearest-ties-even-v1",
        }
    }

    pub const fn scale(self) -> u64 {
        match self {
            Self::HnmfPpmTowardZero => 1_000_000,
            Self::SignedQ24NearestTiesEven => 1 << 24,
            Self::SignedQ32NearestTiesEven => 1 << 32,
        }
    }

    pub const fn rounding(self) -> NumericRoundingV1 {
        match self {
            Self::HnmfPpmTowardZero => NumericRoundingV1::TowardZero,
            Self::SignedQ24NearestTiesEven | Self::SignedQ32NearestTiesEven => {
                NumericRoundingV1::NearestTiesEven
            }
        }
    }
}

/// Closed native signal units. Identity, authority, fences, deadlines and
/// deletion state have no unit here and must retain their exact owner types.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignalUnitV1 {
    Dimensionless,
    Metres,
    MetresPerSecond,
    MetresPerSecondSquared,
    Utility,
}

impl SignalUnitV1 {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Dimensionless => 0,
            Self::Metres => 1,
            Self::MetresPerSecond => 2,
            Self::MetresPerSecondSquared => 3,
            Self::Utility => 4,
        }
    }
}

/// Row-major signal schema. An empty shape means one scalar; otherwise rank is
/// at most four and the product of positive dimensions cannot exceed 4096.
/// Overflow and out-of-range results reject; conversion never clips.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NumericSignalSchemaV1 {
    pub profile: NumericProfileV1,
    pub unit: SignalUnitV1,
    pub shape: Vec<usize>,
    pub minimum_raw: i64,
    pub maximum_raw: i64,
    pub normalization_digest: Digest32,
}

impl NumericSignalSchemaV1 {
    pub(crate) fn element_count(&self) -> Result<usize, NumericConversionError> {
        if self.normalization_digest.is_zero() {
            return Err(NumericConversionError::MissingNormalization);
        }
        if self.minimum_raw > self.maximum_raw {
            return Err(NumericConversionError::InvalidRange);
        }
        if self.shape.len() > 4 {
            return Err(NumericConversionError::Shape);
        }
        let mut count: usize = 1;
        for dimension in &self.shape {
            count = count
                .checked_mul(*dimension)
                .ok_or(NumericConversionError::Shape)?;
            if count == 0 || count > 4096 {
                return Err(NumericConversionError::Shape);
            }
        }
        Ok(count)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NumericConversionError {
    UnknownProfile,
    MissingNormalization,
    NormalizationMismatch,
    UnitMismatch,
    Shape,
    InvalidRange,
    OutOfRange,
    Overflow,
}

impl fmt::Display for NumericConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NumericConversionError {}
