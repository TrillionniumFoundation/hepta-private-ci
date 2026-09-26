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
use tokio_util::sync::CancellationToken;

use crate::PlasticityRuntimeBudgetV1;
use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;
use crate::PlasticityRuntimeMetricsSnapshotV1;

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
        evidence_now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_parameter(request, evidence_now).await
    }

    pub(crate) async fn submit_parameter_with_budget(
        &self,
        request: ParameterPlasticityProductRequestV1,
        evidence_now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_parameter_with_budget(request, evidence_now, budget, cancellation)
            .await
    }

    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, evidence_now).await
    }

    pub(crate) async fn submit_topology_with_budget(
        &self,
        request: TopologyPlasticityProductRequestV1,
        evidence_now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_topology_with_budget(request, evidence_now, budget, cancellation)
            .await
    }

    #[must_use]
    pub(crate) fn metrics(&self) -> PlasticityRuntimeMetricsSnapshotV1 {
        self.handle.metrics()
    }
}
