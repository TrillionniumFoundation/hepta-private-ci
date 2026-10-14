//! The Control-owned journal serves signed NDU reads and the checkpoint
//! compare-and-publish. CNS cutover must use this SAME owner instance.

use codex_hepta_control_plane::NduPublicationOwnerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;
use codex_hepta_types::StableId;
use std::sync::Arc;

use crate::neuron_ndu_read::NduReadFrontierPortV1;
use crate::neuron_ndu_read::NduReadVerificationErrorV1;

#[derive(Debug)]
pub struct ControlNduFrontierAdapterV1 {
    owner: Arc<NduPublicationOwnerV1>,
}
impl ControlNduFrontierAdapterV1 {
    pub fn new(owner: Arc<NduPublicationOwnerV1>) -> Self {
        Self { owner }
    }
}
impl NduReadFrontierPortV1 for ControlNduFrontierAdapterV1 {
    fn latest(&self, scope: &StableId) -> Result<NduSnapshotRefV1, NduReadVerificationErrorV1> {
        let (snapshot, _) = self
            .owner
            .current()
            .map_err(|_| NduReadVerificationErrorV1::FrontierUnavailable)?;
        if snapshot.scope_id != *scope {
            return Err(NduReadVerificationErrorV1::StaleFrontier);
        }
        Ok(snapshot)
    }

    fn compare_and_publish_checkpoint(
        &self,
        expected: &NduSnapshotRefV1,
        verified_read_digest: Digest32,
        tick_digest: Digest32,
        previous_checkpoint: Digest32,
        next_checkpoint: Digest32,
    ) -> Result<Digest32, NduReadVerificationErrorV1> {
        self.owner
            .compare_and_publish_checkpoint(
                expected,
                verified_read_digest,
                tick_digest,
                previous_checkpoint,
                next_checkpoint,
            )
            .map_err(|_| NduReadVerificationErrorV1::CheckpointPublicationUnavailable)
    }
}

#[cfg(test)]
#[path = "neuron_control_frontier_tests.rs"]
mod tests;
