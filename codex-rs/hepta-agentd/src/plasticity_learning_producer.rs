//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. AgentdState retains it as the
//! only product-side producer façade; the long-lived runtime owner still
//! re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence and withholds success until the
//! rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::{
    ParameterPlasticityProductReceiptV1, ParameterPlasticityProductRequestV1,
};

use crate::{PlasticityRuntimeCallErrorV1, PlasticityRuntimeHandleV1};

/// Product-side learning producer bound to one Agentd generation.
///
/// It contains only the bounded runtime handle and cannot access proposal
/// writers, anchor stores, trust roots or authoritative owner stores.
#[derive(Clone)]
pub(crate) struct AgentdLearningPlasticityProducerV1 {
    handle: PlasticityRuntimeHandleV1,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(handle: PlasticityRuntimeHandleV1) -> Self {
        Self { handle }
    }

    pub(crate) async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_parameter(request, now).await
    }
}
