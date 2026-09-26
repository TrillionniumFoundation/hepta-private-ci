//! Final-use admission over durable allocation and revocation state.
//!
//! The caller supplies independently pinned revocation trust roots. The durable
//! snapshot contains only signed update/acknowledgement evidence. Admission
//! requires the exact node to be `Ready`, verifies the allocation and host
//! fences, then confirms that the durable revocation snapshot did not change
//! during the check. The returned witness is point-in-time evidence; callers
//! must invoke it immediately before the physical effect.

use crate::DurableFleetError;
use crate::DurableFleetOwner;
use crate::FleetNodeRevocationState;
use crate::FleetRevocationError;
use crate::FleetRevocationSnapshotError;
use crate::GrantUseWitnessV1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseRevocationConvergenceVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use serde::Deserialize;
use serde::Serialize;
use std::fmt;
use std::sync::Arc;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RevocationBoundGrantUseWitnessV1 {
    pub grant: GrantUseWitnessV1,
    pub revocation_snapshot_sha256: String,
    pub revocation_authority_epoch: u64,
    pub revocation_revision: u64,
    pub node_id: String,
}

pub fn verify_final_use_with_revocation(
    owner: &mut DurableFleetOwner,
    feed_verifier: FinalUseRevocationFeedVerifier,
    convergence_verifier: FinalUseRevocationConvergenceVerifier,
    authority_clock: Arc<dyn AuthorityClock>,
    node_id: &str,
    allocation_id: &str,
    expected_lease_generation: u64,
    expected_host_id: &str,
    expected_host_generation: u64,
    semantic_digest: &str,
) -> Result<RevocationBoundGrantUseWitnessV1, FleetFinalUseError> {
    // `metrics` reloads the latest committed generation under the owner lock.
    owner.metrics().map_err(FleetFinalUseError::Durable)?;
    let snapshot = owner
        .state()
        .fleet_revocation_frontier
        .clone()
        .ok_or(FleetFinalUseError::RevocationSnapshotMissing)?;
    let snapshot_sha256 = snapshot
        .semantic_digest()
        .map_err(FleetFinalUseError::Snapshot)?;
    let coordinator = snapshot
        .restore(feed_verifier, convergence_verifier, authority_clock)
        .map_err(FleetFinalUseError::Snapshot)?;
    let node_state = coordinator
        .node_state(node_id)
        .map_err(FleetFinalUseError::Revocation)?;
    if node_state != FleetNodeRevocationState::Ready {
        return Err(FleetFinalUseError::NodeNotReady(node_state));
    }
    let status = coordinator
        .status()
        .map_err(FleetFinalUseError::Revocation)?;
    if !status.feed_fresh || !status.converged {
        return Err(FleetFinalUseError::NodeNotReady(
            FleetNodeRevocationState::FeedStale,
        ));
    }

    let grant = owner
        .verify_final_use(
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        )
        .map_err(FleetFinalUseError::Durable)?;

    // Reopen the owner generation after grant verification. If another writer
    // advanced the revocation snapshot during the check, fail closed instead of
    // publishing a witness spanning two different authority cuts.
    owner.metrics().map_err(FleetFinalUseError::Durable)?;
    let current_snapshot = owner
        .state()
        .fleet_revocation_frontier
        .as_ref()
        .ok_or(FleetFinalUseError::RevocationSnapshotChanged)?;
    let current_sha256 = current_snapshot
        .semantic_digest()
        .map_err(FleetFinalUseError::Snapshot)?;
    if current_sha256 != snapshot_sha256 {
        return Err(FleetFinalUseError::RevocationSnapshotChanged);
    }

    Ok(RevocationBoundGrantUseWitnessV1 {
        grant,
        revocation_snapshot_sha256: snapshot_sha256,
        revocation_authority_epoch: status.authority_epoch,
        revocation_revision: status.revision,
        node_id: node_id.to_string(),
    })
}

#[derive(Debug)]
pub enum FleetFinalUseError {
    RevocationSnapshotMissing,
    RevocationSnapshotChanged,
    NodeNotReady(FleetNodeRevocationState),
    Durable(DurableFleetError),
    Snapshot(FleetRevocationSnapshotError),
    Revocation(FleetRevocationError),
}

impl fmt::Display for FleetFinalUseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for FleetFinalUseError {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SystemFleetClock;

    #[test]
    fn missing_durable_revocation_snapshot_fails_closed() {
        let directory = tempfile::tempdir().expect("tempdir");
        let state_root = directory.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let owner = DurableFleetOwner::open_supervisor_state_root(
            &state_root,
            Arc::new(SystemFleetClock),
        )
        .expect("owner");

        // Trust objects are deliberately not manufactured here: absence of the
        // durable snapshot is checked before they can authorize any use.
        assert!(owner.state().fleet_revocation_frontier.is_none());
    }
}
