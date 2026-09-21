//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. It only forwards an already
//! typed/signed product request through AgentdState, where the long-lived
//! plasticity owner re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence and withholds success until the
//! rollback-domain anchor commit succeeds.

use std::sync::Arc;

use codex_hepta_intelligence::{
    ParameterPlasticityProductReceiptV1, ParameterPlasticityProductRequestV1,
};

use crate::{AgentdState, PlasticityRuntimeCallErrorV1};

/// Product-side learning producer bound to one Agentd generation.
///
/// The producer deliberately holds only Agentd state, never the proposal
/// registry writer or anchor store. Consequently it cannot bypass generation
/// readiness, owner-evidence refresh, trust verification or durable anchoring.
#[derive(Clone)]
pub(crate) struct AgentdLearningPlasticityProducerV1 {
    state: Arc<AgentdState>,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(state: Arc<AgentdState>) -> Self {
        Self { state }
    }

    pub(crate) async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.state.submit_parameter_plasticity_v1(request, now).await
    }
}
