//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter owns no mutable writer, trust root, owner-evidence store, or
//! authority. It holds only the bounded runtime handle. The long-lived Agentd
//! owner still re-resolves current owner frontiers, revalidates independent
//! Generator/Observer/Evaluator evidence, and withholds success until the
//! rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeCancellationV1;
use crate::PlasticityRuntimeHandleV1;
use crate::PlasticityRuntimeMetricsSnapshotV1;
use crate::PlasticityRuntimeRequestOptionsV1;

/// Product-side learning producer bound to one Agentd generation.
///
/// The type is public so a control.engineering-owned coordinator can be composed
/// against the exact same named boundary retained by `AgentdState`. Constructing
/// or cloning it does not expose writers or create another mutable owner.
#[derive(Clone)]
pub struct AgentdLearningPlasticityProducerV1 {
    handle: PlasticityRuntimeHandleV1,
}

impl AgentdLearningPlasticityProducerV1 {
    #[must_use]
    pub fn new(handle: PlasticityRuntimeHandleV1) -> Self {
        Self { handle }
    }

    pub async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_parameter(request, now).await
    }

    pub async fn submit_parameter_with_options(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        options: PlasticityRuntimeRequestOptionsV1,
        cancellation: PlasticityRuntimeCancellationV1,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_parameter_with_options(request, now, options, cancellation)
            .await
    }

    pub async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }

    pub async fn submit_topology_with_options(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        options: PlasticityRuntimeRequestOptionsV1,
        cancellation: PlasticityRuntimeCancellationV1,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_topology_with_options(request, now, options, cancellation)
            .await
    }

    #[must_use]
    pub fn metrics_snapshot(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.handle.metrics_snapshot()
    }
}
