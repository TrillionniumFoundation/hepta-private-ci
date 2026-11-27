use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::NduError;
use crate::ScalarizationProfile;
use crate::UtilityProfile;
use crate::canonical_scalarization_digest;
use crate::canonical_utility_profile_digest;

/// A scalarization profile whose axes, ranges and exact fixed-point mass have
/// been validated against one canonical utility profile.
///
/// Construction is the only way to obtain this type. In particular, computing
/// a standalone scalarization digest is not sufficient for production use:
/// the same weight vector can only be frozen after it is bound to the exact
/// utility-profile digest and its complete dimension set.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedScalarizationProfileV1 {
    profile: ScalarizationProfile,
    utility_profile_digest: Digest32,
    scalarization_digest: Digest32,
}

impl ValidatedScalarizationProfileV1 {
    pub fn try_new(
        utility_profile: &UtilityProfile,
        mut scalarization: ScalarizationProfile,
    ) -> Result<Self, NduError> {
        let utility_profile_digest = canonical_utility_profile_digest(utility_profile)?;
        scalarization.weights.sort();
        for window in scalarization.weights.windows(2) {
            if window[0].axis == window[1].axis {
                return Err(NduError::DuplicateAxis(window[0].axis.to_string()));
            }
        }
        if scalarization.weights.len() != utility_profile.dimensions.len() {
            return Err(NduError::IncompleteScalarization);
        }

        let weights: BTreeMap<&StableId, FixedQ32> = scalarization
            .weights
            .iter()
            .map(|weight| (&weight.axis, weight.value))
            .collect();
        let mut sum = FixedQ32::ZERO;
        for (axis, _) in &utility_profile.dimensions {
            let weight = weights
                .get(axis)
                .copied()
                .ok_or(NduError::IncompleteScalarization)?;
            if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&weight) {
                return Err(NduError::InvalidWeight(axis.to_string()));
            }
            sum = sum.checked_add(weight).map_err(|_| NduError::Arithmetic)?;
        }
        if sum != FixedQ32::ONE {
            return Err(NduError::IncompleteScalarization);
        }

        let scalarization_digest = canonical_scalarization_digest(&scalarization)?;
        Ok(Self {
            profile: scalarization,
            utility_profile_digest,
            scalarization_digest,
        })
    }

    #[must_use]
    pub const fn profile(&self) -> &ScalarizationProfile {
        &self.profile
    }

    #[must_use]
    pub fn into_profile(self) -> ScalarizationProfile {
        self.profile
    }

    #[must_use]
    pub const fn utility_profile_digest(&self) -> Digest32 {
        self.utility_profile_digest
    }

    #[must_use]
    pub const fn scalarization_digest(&self) -> Digest32 {
        self.scalarization_digest
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::StableId;

    use super::*;
    use crate::AxisDirection;
    use crate::AxisValue;
    use crate::RequiredOrganSet;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn profile() -> UtilityProfile {
        UtilityProfile {
            profile_id: id("utility-v1"),
            axis_registry_digest: Digest32::of_bytes(b"axis-registry"),
            normalization_manifest_digest: Digest32::of_bytes(b"normalization"),
            dimensions: vec![
                (id("latency"), AxisDirection::Minimize),
                (id("success"), AxisDirection::Maximize),
            ],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: Vec::new(),
            },
        }
    }

    #[test]
    fn validated_scalarization_is_profile_bound_and_canonical() {
        let scalarization = ScalarizationProfile {
            profile_id: id("weights-v1"),
            weights: vec![
                AxisValue {
                    axis: id("success"),
                    value: FixedQ32::ONE,
                },
                AxisValue {
                    axis: id("latency"),
                    value: FixedQ32::ZERO,
                },
            ],
        };
        let validated = ValidatedScalarizationProfileV1::try_new(&profile(), scalarization)
            .expect("valid scalarization");
        assert_eq!(validated.profile().weights[0].axis, id("latency"));
        assert!(!validated.utility_profile_digest().is_zero());
        assert!(!validated.scalarization_digest().is_zero());
    }

    #[test]
    fn incomplete_or_out_of_range_scalarization_is_rejected_before_owner_open() {
        let incomplete = ScalarizationProfile {
            profile_id: id("weights-v1"),
            weights: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ONE,
            }],
        };
        assert!(matches!(
            ValidatedScalarizationProfileV1::try_new(&profile(), incomplete),
            Err(NduError::IncompleteScalarization)
        ));

        let invalid = ScalarizationProfile {
            profile_id: id("weights-v1"),
            weights: vec![
                AxisValue {
                    axis: id("success"),
                    value: FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
                },
                AxisValue {
                    axis: id("latency"),
                    value: FixedQ32::from_raw(-1),
                },
            ],
        };
        assert!(matches!(
            ValidatedScalarizationProfileV1::try_new(&profile(), invalid),
            Err(NduError::InvalidWeight(_))
        ));
    }
}
