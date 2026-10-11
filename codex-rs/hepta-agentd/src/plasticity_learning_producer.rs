//! Generation-local, optional plasticity owner liveness binding.
//!
//! No caller can submit proposal effects through an unused Agentd shim;
//! production proposals remain exclusively owned by PlasticityRuntimeHandleV1
//! and must be wired through an independently authorized caller.

use crate::PlasticityRuntimeHandleV1;

#[derive(Clone)]
pub(crate) struct AgentdLearningPlasticityProducerV1 {
    handle: PlasticityRuntimeHandleV1,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(handle: PlasticityRuntimeHandleV1) -> Self {
        Self { handle }
    }

    /// A closed actor channel is an actual owner-loss condition, never a
    /// reason to fabricate a succeeded learning proposal.
    pub(crate) fn owner_channel_open(&self) -> bool {
        self.handle.is_open()
    }
}
