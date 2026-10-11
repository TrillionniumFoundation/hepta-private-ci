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

    /// Qualification-only compatibility callers exercise the REAL bounded
    /// runtime owner and WAL/CAS replay. No production caller is wired until
    /// a separately signed learning admission has been verified.
    #[cfg(test)]
    pub(crate) async fn submit_parameter(
        &self,
        request: codex_hepta_intelligence::ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::ParameterPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        self.handle.propose_parameter(request, now).await
    }

    #[cfg(test)]
    pub(crate) async fn submit_topology(
        &self,
        request: codex_hepta_intelligence::TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::TopologyPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        self.handle.propose_topology(request, now).await
    }
}
