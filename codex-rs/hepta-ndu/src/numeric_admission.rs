use std::error::Error;
use std::fmt;

use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NumericConversionError;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalSchemaV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::RegisteredNumericConversionReceiptV1;
use codex_hepta_types::RegistryError;
use codex_hepta_types::SignalUnitV1;
use codex_hepta_types::rescale_signal_registered;

use crate::AxisValue;
use crate::UtilityProfile;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduNumericAdmissionErrorV1 {
    Registry(RegistryError),
    Conversion(NumericConversionError),
    RegistryNotConfigured,
    EmptyRegistryDigest,
    RegistryDigestMismatch,
    NormalizationMismatch,
    UnitMismatch,
    AxisCountMismatch,
    AxisIdentityMismatch,
    ShapeMismatch,
}

impl fmt::Display for NduNumericAdmissionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduNumericAdmissionErrorV1 {}

impl From<RegistryError> for NduNumericAdmissionErrorV1 {
    fn from(error: RegistryError) -> Self {
        Self::Registry(error)
    }
}

impl From<NumericConversionError> for NduNumericAdmissionErrorV1 {
    fn from(error: NumericConversionError) -> Self {
        Self::Conversion(error)
    }
}

/// One immutable platform.types registry generation selected by the NDU owner.
///
/// Construction computes the canonical registry digest once.  The owner freezes
/// this value for its lifetime; callers cannot swap a different registry under
/// an already opened owner or present a pure conversion receipt as admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduNumericRegistryV1 {
    registry: ContractRegistryV1,
    registry_digest: Digest32,
}

impl NduNumericRegistryV1 {
    pub fn new(registry: ContractRegistryV1) -> Result<Self, NduNumericAdmissionErrorV1> {
        let registry_digest = registry.registry_digest()?;
        if registry_digest.is_zero() {
            return Err(NduNumericAdmissionErrorV1::EmptyRegistryDigest);
        }
        Ok(Self {
            registry,
            registry_digest,
        })
    }

    #[must_use]
    pub const fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    /// Admit the existing typed Q32 contribution surface. This checks numeric
    /// representation and normalization, not FixedQ32 arithmetic compatibility.
    pub(crate) fn admit_utility_axes(
        &self,
        profile: &UtilityProfile,
        axes: &[AxisValue],
    ) -> Result<NduRegisteredUtilitySignalV1, NduNumericAdmissionErrorV1> {
        if axes.len() != profile.dimensions.len() || axes.len() > 8 {
            return Err(NduNumericAdmissionErrorV1::AxisCountMismatch);
        }
        let mut values = Vec::with_capacity(axes.len());
        for (axis, _) in &profile.dimensions {
            let mut matches = axes.iter().filter(|value| value.axis == *axis);
            let value = matches
                .next()
                .ok_or(NduNumericAdmissionErrorV1::AxisIdentityMismatch)?;
            if matches.next().is_some() {
                return Err(NduNumericAdmissionErrorV1::AxisIdentityMismatch);
            }
            values.push(value.value.raw());
        }
        self.admit_utility_signal(
            profile,
            &NumericSignalV1 {
                schema: NumericSignalSchemaV1 {
                    profile: NumericProfileV1::SignedQ32NearestTiesEven,
                    unit: SignalUnitV1::Utility,
                    shape: vec![values.len()],
                    minimum_raw: i64::MIN,
                    maximum_raw: i64::MAX,
                    normalization_digest: profile.normalization_manifest_digest,
                },
                values,
            },
        )
    }

    pub fn admit_utility_signal(
        &self,
        utility_profile: &UtilityProfile,
        source: &NumericSignalV1,
    ) -> Result<NduRegisteredUtilitySignalV1, NduNumericAdmissionErrorV1> {
        if source.schema.normalization_digest != utility_profile.normalization_manifest_digest {
            return Err(NduNumericAdmissionErrorV1::NormalizationMismatch);
        }
        if source.schema.unit != SignalUnitV1::Utility {
            return Err(NduNumericAdmissionErrorV1::UnitMismatch);
        }
        if source.values.len() != utility_profile.dimensions.len() {
            return Err(NduNumericAdmissionErrorV1::AxisCountMismatch);
        }
        if source.schema.shape != [utility_profile.dimensions.len()] {
            return Err(NduNumericAdmissionErrorV1::ShapeMismatch);
        }

        let target = NumericSignalSchemaV1 {
            profile: NumericProfileV1::SignedQ32NearestTiesEven,
            unit: SignalUnitV1::Utility,
            shape: source.schema.shape.clone(),
            minimum_raw: i64::MIN,
            maximum_raw: i64::MAX,
            normalization_digest: utility_profile.normalization_manifest_digest,
        };
        let (signal, admission) = rescale_signal_registered(source, &target, &self.registry)?;
        if admission.registry_digest != self.registry_digest {
            return Err(NduNumericAdmissionErrorV1::RegistryDigestMismatch);
        }
        let axis_values = utility_profile
            .dimensions
            .iter()
            .zip(signal.values.iter())
            .map(|((axis, _), value)| AxisValue {
                axis: axis.clone(),
                value: codex_hepta_types::FixedQ32::from_raw(*value),
            })
            .collect();
        Ok(NduRegisteredUtilitySignalV1 {
            signal,
            axis_values,
            registry_digest: self.registry_digest,
            admission,
        })
    }
}

/// NDU utility-axis values with a distinct registry-admission receipt.
///
/// `admission.conversion` remains the pure arithmetic receipt.  The outer type
/// additionally carries the immutable registry generation and admission digest,
/// so downstream code cannot treat a plain conversion as owner admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduRegisteredUtilitySignalV1 {
    pub signal: NumericSignalV1,
    pub axis_values: Vec<AxisValue>,
    pub registry_digest: Digest32,
    pub admission: RegisteredNumericConversionReceiptV1,
}

#[cfg(test)]
#[path = "numeric_admission_tests.rs"]
mod tests;
