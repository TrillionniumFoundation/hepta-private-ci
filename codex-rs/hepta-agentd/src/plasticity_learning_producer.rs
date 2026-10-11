//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. AgentdState retains it as the
//! only product-side producer façade; the long-lived runtime owner still
//! re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence and withholds success until the
//! rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;

/// Product-side learning producer bound to one Agentd generation.
///
/// Holding this object is not authorization to install or promote learned
/// weights. It contains only the bounded owner channel and cannot access
/// proposal writers, anchor stores, trust roots or authoritative owner stores.
/// The unique PlasticityRuntimeOwnerV1 rechecks lifecycle/currentness,
/// separately signed learning evidence, Artifact CAS and durable rollback
/// anchors before accepting any proposal. Production callers must acquire
/// the handle through trusted Agentd startup composition.
#[derive(Clone)]
pub struct AgentdLearningPlasticityProducerV1 {
    handle: PlasticityRuntimeHandleV1,
}

impl AgentdLearningPlasticityProducerV1 {
    pub fn new(handle: PlasticityRuntimeHandleV1) -> Self {
        Self { handle }
    }

    /// An open channel is a health prerequisite, never a grant to change
    /// Cell weights or topology. The real owner retains authorization and
    /// durability decisions after receipt of a bounded request.
    #[must_use]
    pub fn is_open(&self) -> bool {
        self.handle.is_open()
    }

    pub async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_parameter(request, now).await
    }

    pub async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }
}
