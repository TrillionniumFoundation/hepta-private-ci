//! Borrowed adapter used by the Agentd plasticity lifetime tests.
//!
//! Production composition retains PlasticityRuntimeHandleV1 directly in
//! AgentdState. A learning/self-iteration product caller is not yet composed.
//! This test adapter owns no writer, trust root, evidence store or authority.
//! It submits through the bounded channel to the long-lived runtime owner,
//! which re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence and withholds success until the
//! rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;

/// Borrowed test submission adapter for one Agentd generation.
///
/// It cannot access proposal writers, anchor stores, trust roots or authoritative
/// owner stores, and does not clone the retained runtime handle.
pub(crate) struct AgentdLearningPlasticityProducerV1<'a> {
    handle: &'a PlasticityRuntimeHandleV1,
}

impl<'a> AgentdLearningPlasticityProducerV1<'a> {
    pub(crate) fn new(handle: &'a PlasticityRuntimeHandleV1) -> Self {
        Self { handle }
    }

    pub(crate) async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_parameter(request, now).await
    }

    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }
}
