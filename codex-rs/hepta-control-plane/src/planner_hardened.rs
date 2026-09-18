//! Hardened planner admission for production-facing composition.
//!
//! The legacy planner accepts an opaque resource-profile digest because it is
//! also used by low-level fixtures. This module closes that ambiguity for real
//! callers by deriving the digest from the exact sorted reservations before
//! candidate filtering.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::GlobalStateSnapshotV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::prepare_plan;

pub const MAX_RESOURCE_PROFILE_AXES: usize = 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerHardeningError {
    Planner(PlannerError),
    ResourceProfileBindingMismatch,
    InvalidResourceProfile,
}

impl fmt::Display for PlannerHardeningError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Planner(error) => write!(formatter, "{error}"),
            Self::ResourceProfileBindingMismatch => {
                formatter.write_str("resource profile digest does not bind exact reservations")
            }
            Self::InvalidResourceProfile => formatter.write_str("invalid resource profile"),
        }
    }
}

impl StdError for PlannerHardeningError {}

impl From<PlannerError> for PlannerHardeningError {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

/// Canonical digest of the exact resource endowments and essential floors.
/// Ordering is normalized by axis identity before hashing.
pub fn canonical_resource_profile_digest(
    reservations: &[ResourceReservationV1],
) -> Result<Digest32, PlannerHardeningError> {
    if reservations.is_empty() || reservations.len() > MAX_RESOURCE_PROFILE_AXES {
        return Err(PlannerHardeningError::InvalidResourceProfile);
    }
    let mut normalized = reservations.to_vec();
    normalized.sort_by(|left, right| left.axis.cmp(&right.axis));
    for window in normalized.windows(2) {
        if window[0].axis == window[1].axis {
            return Err(PlannerHardeningError::InvalidResourceProfile);
        }
    }
    for reservation in &normalized {
        if reservation.endowment < FixedQ32::ZERO
            || reservation.essential_floor < FixedQ32::ZERO
            || reservation.essential_floor > reservation.endowment
        {
            return Err(PlannerHardeningError::InvalidResourceProfile);
        }
    }

    let mut bytes = b"hepta.control.resource-profile.v1\0".to_vec();
    let count = u32::try_from(normalized.len())
        .map_err(|_| PlannerHardeningError::InvalidResourceProfile)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for reservation in normalized {
        let axis = reservation.axis.as_str().as_bytes();
        let axis_len =
            u32::try_from(axis.len()).map_err(|_| PlannerHardeningError::InvalidResourceProfile)?;
        bytes.extend_from_slice(&axis_len.to_be_bytes());
        bytes.extend_from_slice(axis);
        bytes.extend_from_slice(&reservation.endowment.raw().to_be_bytes());
        bytes.extend_from_slice(&reservation.essential_floor.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Production-facing preparation path. The caller cannot reuse an opaque
/// resource-profile identity with different endowment/floor semantics.
pub fn prepare_plan_hardened(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerHardeningError> {
    let expected = canonical_resource_profile_digest(&request.resource_reservations)?;
    if request.resource_profile_digest != expected {
        return Err(PlannerHardeningError::ResourceProfileBindingMismatch);
    }
    prepare_plan(snapshot, request).map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::OwnerReadinessV1;
    use crate::OwnerSummaryV1;
    use crate::PlanCandidateV1;
    use crate::PlannerAxisValueV1;
    use crate::SnapshotRequestV1;
    use crate::collect_snapshot;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn q32(value: i64) -> FixedQ32 {
        FixedQ32::from_raw(value << 32)
    }

    fn reservations() -> Vec<ResourceReservationV1> {
        vec![
            ResourceReservationV1 {
                axis: id("memory"),
                endowment: q32(10),
                essential_floor: q32(2),
            },
            ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(8),
                essential_floor: q32(1),
            },
        ]
    }

    #[test]
    fn resource_profile_digest_is_order_independent_and_semantic() {
        let left = reservations();
        let mut right = left.clone();
        right.reverse();
        assert_eq!(
            canonical_resource_profile_digest(&left).expect("left digest"),
            canonical_resource_profile_digest(&right).expect("right digest")
        );
        right[0].essential_floor = q32(3);
        assert_ne!(
            canonical_resource_profile_digest(&left).expect("left digest"),
            canonical_resource_profile_digest(&right).expect("changed digest")
        );
    }

    #[test]
    fn hardened_prepare_rejects_opaque_or_stale_resource_binding() {
        let generation = Generation::new(1).expect("generation");
        let snapshot = collect_snapshot(
            SnapshotRequestV1 {
                objective_digest: digest("objective"),
                body_generation: generation,
                configuration_digest: digest("configuration"),
                revocation_frontier_digest: digest("revocations"),
                snapshot_policy_digest: digest("snapshot-policy"),
                collected_at_micros: 100,
                maximum_owner_age_micros: 10,
                expires_at_micros: 200,
                required_owner_ids: vec![id("owner")],
            },
            vec![OwnerSummaryV1 {
                owner_id: id("owner"),
                revision: Revision::new(1).expect("revision"),
                objective_digest: digest("objective"),
                body_generation: generation,
                configuration_digest: digest("configuration"),
                observed_at_micros: 99,
                expires_at_micros: 200,
                readiness: OwnerReadinessV1::Ready,
                source_frontier_digest: digest("frontier"),
                support_digest: digest("support"),
            }],
        )
        .expect("snapshot");
        let resource_reservations = vec![ResourceReservationV1 {
            axis: id("compute"),
            endowment: q32(2),
            essential_floor: FixedQ32::ZERO,
        }];
        let request = PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 100,
            deadline_micros: 190,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("not-the-resource-profile"),
            candidates: vec![PlanCandidateV1 {
                candidate_id: id("abstain"),
                operation_id: id("abstain-op"),
                plan_digest: digest("abstain-plan"),
                required_owner_ids: vec![id("owner")],
                final_payload_digests: vec![],
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("compute"),
                    value: FixedQ32::ZERO,
                }],
            }],
            resource_reservations,
        };
        assert_eq!(
            prepare_plan_hardened(&snapshot, request),
            Err(PlannerHardeningError::ResourceProfileBindingMismatch)
        );
    }
}
