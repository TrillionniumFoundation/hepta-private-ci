//! Read the existing fleet revocation owner, never maintain a second frontier.
use codex_hepta_fleet::FleetNodeRevocationState;
use codex_hepta_fleet::FleetRevocationCoordinator;

use crate::SharedMemoryTrainingError;

/// A request stays within one acknowledged authority head. A newer head forces
/// a new request/grant even when the update did not mention this model.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct MemoryFleetHeadV1 {
    epoch: u64,
    revision: u64,
}

pub(super) fn require_current_memory_fleet_v1(
    fleet: &FleetRevocationCoordinator,
    node: &str,
) -> Result<MemoryFleetHeadV1, SharedMemoryTrainingError> {
    let state = fleet
        .node_state(node)
        .map_err(|_| SharedMemoryTrainingError::Invalid("memory fleet unavailable"))?;
    let head = fleet
        .status()
        .map_err(|_| SharedMemoryTrainingError::Invalid("memory fleet head unavailable"))?;
    if state != FleetNodeRevocationState::Ready || !head.feed_fresh {
        return Err(SharedMemoryTrainingError::Invalid(
            "memory fleet not authority-ready",
        ));
    }
    Ok(MemoryFleetHeadV1 {
        epoch: head.authority_epoch,
        revision: head.revision,
    })
}

#[cfg(test)]
#[path = "memory_serving_fleet_tests.rs"]
mod tests;
