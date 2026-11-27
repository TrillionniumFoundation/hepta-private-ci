use std::error::Error;
use std::fmt;
use std::time::Duration;

use crate::MAX_FEDERATION_SOURCES_PER_AGENT;

pub const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS_HARD: usize = 128;
pub const MAX_PRODUCT_FEDERATION_ADMITTED_PEERS_HARD: usize = MAX_FEDERATION_SOURCES_PER_AGENT;
pub const MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY_HARD: usize = 32;
pub const MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY_HARD: usize = 16;
pub const MAX_PRODUCT_FEDERATION_TOTAL_BUDGET_MS_HARD: u64 = 30_000;
pub const MAX_PRODUCT_FEDERATION_PER_OWNER_BUDGET_MS_HARD: u64 = 5_000;

/// Host-selected bounds for the in-process memory federation product path.
///
/// Values may only narrow the architectural ceilings. The profile is fixed when
/// Agentd composes the runtime; request bytes cannot increase any bound.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FederationRuntimeProfile {
    max_owner_layouts: usize,
    max_admitted_peers: usize,
    discovery_concurrency: usize,
    revalidation_concurrency: usize,
    total_budget: Duration,
    per_owner_budget: Duration,
}

impl FederationRuntimeProfile {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        max_owner_layouts: usize,
        max_admitted_peers: usize,
        discovery_concurrency: usize,
        revalidation_concurrency: usize,
        total_budget_ms: u64,
        per_owner_budget_ms: u64,
    ) -> Result<Self, FederationRuntimeProfileError> {
        for (field, value) in [
            ("max_owner_layouts", max_owner_layouts),
            ("max_admitted_peers", max_admitted_peers),
            ("discovery_concurrency", discovery_concurrency),
            ("revalidation_concurrency", revalidation_concurrency),
        ] {
            if value == 0 {
                return Err(FederationRuntimeProfileError::Zero(field));
            }
        }
        for (field, value, maximum) in [
            (
                "max_owner_layouts",
                max_owner_layouts,
                MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS_HARD,
            ),
            (
                "max_admitted_peers",
                max_admitted_peers,
                MAX_PRODUCT_FEDERATION_ADMITTED_PEERS_HARD,
            ),
            (
                "discovery_concurrency",
                discovery_concurrency,
                MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY_HARD,
            ),
            (
                "revalidation_concurrency",
                revalidation_concurrency,
                MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY_HARD,
            ),
        ] {
            if value > maximum {
                return Err(FederationRuntimeProfileError::ExceedsHardLimit {
                    field,
                    value: u64::try_from(value).unwrap_or(u64::MAX),
                    maximum: u64::try_from(maximum).unwrap_or(u64::MAX),
                });
            }
        }
        for (field, value, maximum) in [
            (
                "total_budget_ms",
                total_budget_ms,
                MAX_PRODUCT_FEDERATION_TOTAL_BUDGET_MS_HARD,
            ),
            (
                "per_owner_budget_ms",
                per_owner_budget_ms,
                MAX_PRODUCT_FEDERATION_PER_OWNER_BUDGET_MS_HARD,
            ),
        ] {
            if value == 0 {
                return Err(FederationRuntimeProfileError::Zero(field));
            }
            if value > maximum {
                return Err(FederationRuntimeProfileError::ExceedsHardLimit {
                    field,
                    value,
                    maximum,
                });
            }
        }
        if max_admitted_peers > max_owner_layouts {
            return Err(FederationRuntimeProfileError::Inconsistent(
                "max_admitted_peers cannot exceed max_owner_layouts",
            ));
        }
        if discovery_concurrency > max_owner_layouts {
            return Err(FederationRuntimeProfileError::Inconsistent(
                "discovery_concurrency cannot exceed max_owner_layouts",
            ));
        }
        if revalidation_concurrency > max_owner_layouts {
            return Err(FederationRuntimeProfileError::Inconsistent(
                "revalidation_concurrency cannot exceed max_owner_layouts",
            ));
        }
        if per_owner_budget_ms > total_budget_ms {
            return Err(FederationRuntimeProfileError::Inconsistent(
                "per_owner_budget_ms cannot exceed total_budget_ms",
            ));
        }
        Ok(Self {
            max_owner_layouts,
            max_admitted_peers,
            discovery_concurrency,
            revalidation_concurrency,
            total_budget: Duration::from_millis(total_budget_ms),
            per_owner_budget: Duration::from_millis(per_owner_budget_ms),
        })
    }

    pub const fn max_owner_layouts(self) -> usize {
        self.max_owner_layouts
    }

    pub const fn max_admitted_peers(self) -> usize {
        self.max_admitted_peers
    }

    pub const fn discovery_concurrency(self) -> usize {
        self.discovery_concurrency
    }

    pub const fn revalidation_concurrency(self) -> usize {
        self.revalidation_concurrency
    }

    pub const fn total_budget(self) -> Duration {
        self.total_budget
    }

    pub const fn per_owner_budget(self) -> Duration {
        self.per_owner_budget
    }
}

impl Default for FederationRuntimeProfile {
    fn default() -> Self {
        Self {
            max_owner_layouts: MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS_HARD,
            max_admitted_peers: MAX_PRODUCT_FEDERATION_ADMITTED_PEERS_HARD,
            discovery_concurrency: 8,
            revalidation_concurrency: 8,
            total_budget: Duration::from_secs(2),
            per_owner_budget: Duration::from_secs(2),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationRuntimeProfileError {
    Zero(&'static str),
    ExceedsHardLimit {
        field: &'static str,
        value: u64,
        maximum: u64,
    },
    Inconsistent(&'static str),
}

impl fmt::Display for FederationRuntimeProfileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Zero(field) => write!(formatter, "{field} must be non-zero"),
            Self::ExceedsHardLimit {
                field,
                value,
                maximum,
            } => write!(
                formatter,
                "{field} value {value} exceeds architectural hard limit {maximum}"
            ),
            Self::Inconsistent(reason) => formatter.write_str(reason),
        }
    }
}

impl Error for FederationRuntimeProfileError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_profile_is_valid_and_bounded() {
        let profile = FederationRuntimeProfile::default();
        FederationRuntimeProfile::try_new(
            profile.max_owner_layouts(),
            profile.max_admitted_peers(),
            profile.discovery_concurrency(),
            profile.revalidation_concurrency(),
            u64::try_from(profile.total_budget().as_millis()).expect("total budget"),
            u64::try_from(profile.per_owner_budget().as_millis()).expect("owner budget"),
        )
        .expect("default profile");
    }

    #[test]
    fn request_cannot_widen_architectural_limits() {
        assert!(matches!(
            FederationRuntimeProfile::try_new(
                MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS_HARD + 1,
                1,
                1,
                1,
                1_000,
                1_000,
            ),
            Err(FederationRuntimeProfileError::ExceedsHardLimit {
                field: "max_owner_layouts",
                ..
            })
        ));
        assert!(matches!(
            FederationRuntimeProfile::try_new(8, 8, 8, 8, 1_000, 1_001),
            Err(FederationRuntimeProfileError::Inconsistent(_))
        ));
    }
}
