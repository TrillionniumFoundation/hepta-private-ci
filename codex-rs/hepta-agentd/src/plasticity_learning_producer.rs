//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. AgentdState retains it as the
//! only product-side producer façade; the long-lived runtime owner still
//! re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence and withholds success until the
//! rollback-domain anchor commit succeeds.

#[cfg(test)]
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
#[cfg(test)]
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
#[cfg(test)]
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
#[cfg(test)]
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;

#[cfg(test)]
use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;

/// Product-side learning producer bound to one Agentd generation.
///
/// It contains only the bounded runtime handle and cannot access proposal
/// writers, anchor stores, trust roots or authoritative owner stores.
#[derive(Clone)]
pub(crate) struct AgentdLearningPlasticityProducerV1 {
    _handle: PlasticityRuntimeHandleV1,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(handle: PlasticityRuntimeHandleV1) -> Self {
        Self { _handle: handle }
    }

    #[cfg(test)]
    pub(crate) async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self._handle.propose_parameter(request, now).await
    }

    #[cfg(test)]
    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }
}
