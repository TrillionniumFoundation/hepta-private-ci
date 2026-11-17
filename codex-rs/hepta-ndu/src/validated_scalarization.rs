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
