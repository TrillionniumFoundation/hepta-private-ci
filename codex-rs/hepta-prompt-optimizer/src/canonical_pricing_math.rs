//! Fixed-point utility and confidence values in the same net-cost basis.

use codex_hepta_types::FixedQ32;

use super::CanonicalPromptError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct NetUtilityInterval {
    pub mean: FixedQ32,
    pub lower: FixedQ32,
    pub upper: FixedQ32,
}

/// Costs are fixed conditional on the frozen pricing inputs. Subtract each
/// identical cost from the mean and both bounds; do not relabel gross bounds as
/// a net interval. Uncertain cost estimates need their own joint uncertainty
/// model and are not made statistically calibrated by this transformation.
pub(super) fn net_interval(
    mean: FixedQ32,
    lower: FixedQ32,
    upper: FixedQ32,
    costs: impl IntoIterator<Item = FixedQ32>,
) -> Result<NetUtilityInterval, CanonicalPromptError> {
    if lower > mean || mean > upper {
        return Err(CanonicalPromptError::CandidateIntegrity(
            "gross confidence interval",
        ));
    }
    let mut value = NetUtilityInterval { mean, lower, upper };
    for cost in costs {
        if cost < FixedQ32::ZERO {
            return Err(CanonicalPromptError::InvalidPricingPolicy);
        }
        value.mean = value
            .mean
            .checked_sub(cost)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        value.lower = value
            .lower
            .checked_sub(cost)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        value.upper = value
            .upper
            .checked_sub(cost)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
    }
    Ok(value)
}

#[cfg(test)]
#[path = "canonical_pricing_math_tests.rs"]
mod tests;
