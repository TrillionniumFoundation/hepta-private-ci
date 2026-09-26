use std::error::Error;
use std::fmt;

use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::ContractRegistryV1;
use crate::Digest32;
use crate::FIXED_Q32_ARITHMETIC_PROFILE_V1;
use crate::IdentityError;
use crate::StableId;
use crate::canonical_digest_v1;

pub const NUMERIC_PROFILE_DEFINITION_VERSION_V1: u32 = 1;

/// Native engineering conventions, not production profile registrations.
/// These names do not change the legacy `FixedQ32` arithmetic methods.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum NumericProfileV1 {
    HnmfPpmTowardZero,
    SignedQ24NearestTiesEven,
    SignedQ32NearestTiesEven,
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum NumericRoundingV1 {
    TowardZero,
    NearestTiesEven,
}

impl NumericRoundingV1 {
    pub const fn id(self) -> &'static str {
        match self {
            Self::TowardZero => "toward-zero",
            Self::NearestTiesEven => "nearest-ties-even",
        }
    }
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

    pub const fn shares_fixed_q32_raw_scale(self) -> bool {
        matches!(self, Self::SignedQ32NearestTiesEven)
    }

    pub const fn fixed_q32_arithmetic_compatible(self) -> bool {
        false
    }

    pub const fn fixed_q32_arithmetic_profile_id(self) -> &'static str {
        FIXED_Q32_ARITHMETIC_PROFILE_V1
    }
}

/// Exact, digest-bound production-admission definition for one native numeric
/// profile. V1 cannot change scale or rounding under the same profile identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NumericProfileDefinitionV1 {
    profile: NumericProfileV1,
    version: u32,
    scale: u64,
    rounding: NumericRoundingV1,
    digest: Digest32,
}

impl NumericProfileDefinitionV1 {
    pub fn canonical(profile: NumericProfileV1) -> Result<Self, NumericProfileDefinitionError> {
        Self::new(
            profile,
            NUMERIC_PROFILE_DEFINITION_VERSION_V1,
            profile.scale(),
            profile.rounding(),
        )
    }

    pub fn new(
        profile: NumericProfileV1,
        version: u32,
        scale: u64,
        rounding: NumericRoundingV1,
    ) -> Result<Self, NumericProfileDefinitionError> {
        if version != NUMERIC_PROFILE_DEFINITION_VERSION_V1 {
            return Err(NumericProfileDefinitionError::UnsupportedVersion(version));
        }
        if scale == 0 {
            return Err(NumericProfileDefinitionError::ZeroScale);
        }
        if scale != profile.scale() || rounding != profile.rounding() {
            return Err(NumericProfileDefinitionError::SemanticMismatch);
        }
        let type_id = StableId::new("platform.types:numeric-profile-definition-v1")
            .map_err(NumericProfileDefinitionError::Identity)?;
        let fields = [
            CanonicalFieldV1 {
                name: "profile_id",
                value: CanonicalValueV1::Text(profile.id()),
            },
            CanonicalFieldV1 {
                name: "version",
                value: CanonicalValueV1::U64(u64::from(version)),
            },
            CanonicalFieldV1 {
                name: "scale",
                value: CanonicalValueV1::U64(scale),
            },
            CanonicalFieldV1 {
                name: "rounding",
                value: CanonicalValueV1::Text(rounding.id()),
            },
        ];
        let digest = canonical_digest_v1(&type_id, 1, &fields)
            .map_err(NumericProfileDefinitionError::Canonical)?;
        Ok(Self {
            profile,
            version,
            scale,
            rounding,
            digest,
        })
    }

    pub const fn profile(&self) -> NumericProfileV1 {
        self.profile
    }
    pub const fn version(&self) -> u32 {
        self.version
    }
    pub const fn scale(&self) -> u64 {
        self.scale
    }
    pub const fn rounding(&self) -> NumericRoundingV1 {
        self.rounding
    }
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NumericProfileDefinitionError {
    Identity(IdentityError),
    Canonical(CanonicalDigestError),
    UnsupportedVersion(u32),
    ZeroScale,
    SemanticMismatch,
}

impl fmt::Display for NumericProfileDefinitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Identity(error) => error.fmt(formatter),
            Self::Canonical(error) => error.fmt(formatter),
            Self::UnsupportedVersion(version) => {
                write!(
                    formatter,
                    "unsupported numeric profile definition version: {version}"
                )
            }
            Self::ZeroScale => formatter.write_str("numeric profile scale must be non-zero"),
            Self::SemanticMismatch => formatter.write_str(
                "numeric profile identity cannot change scale or rounding semantics in V1",
            ),
        }
    }
}

impl Error for NumericProfileDefinitionError {}

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
    pub const fn id(self) -> &'static str {
        match self {
            Self::Dimensionless => "dimensionless",
            Self::Metres => "metres",
            Self::MetresPerSecond => "metres-per-second",
            Self::MetresPerSecondSquared => "metres-per-second-squared",
            Self::Utility => "utility",
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
    pub fn validate_with_registry(
        &self,
        registry: &ContractRegistryV1,
    ) -> Result<(), NumericConversionError> {
        self.element_count()?;
        registry
            .require_normalization(self.normalization_digest)
            .map_err(|_| NumericConversionError::UnknownNormalization)?;
        registry
            .require_numeric_profile(self.profile)
            .map_err(|_| NumericConversionError::UnregisteredProfile)?;
        Ok(())
    }

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
    UnregisteredProfile,
    MissingNormalization,
    UnknownNormalization,
    NormalizationMismatch,
    UnitMismatch,
    Shape,
    InvalidRange,
    OutOfRange,
    Overflow,
    RegistryAdmission,
    CanonicalEncoding,
}

impl fmt::Display for NumericConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NumericConversionError {}

#[cfg(test)]
#[path = "numeric_profile_tests.rs"]
mod tests;
