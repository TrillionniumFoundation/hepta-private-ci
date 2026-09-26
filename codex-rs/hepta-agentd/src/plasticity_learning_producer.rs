//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. Agentd retains it as the
//! product-side producer façade; the long-lived runtime owner re-resolves current
//! owner frontiers, revalidates independent evidence and withholds success until
//! the rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::CoveredParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use tokio_util::sync::CancellationToken;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;
use crate::PlasticityRuntimeOutcomeV1;
use crate::PlasticityRuntimeRequestBudgetV1;

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

    pub(crate) async fn submit_covered_parameter(
        &self,
        request: CoveredParameterPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<CoveredParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        self.handle
            .propose_covered_parameter(request, now, budget, cancellation)
            .await
    }

    pub(crate) async fn submit_parameter_bounded(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        self.handle
            .propose_parameter_bounded(request, now, budget, cancellation)
            .await
    }

    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }

    pub(crate) async fn submit_topology_bounded(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        self.handle
            .propose_topology_bounded(request, now, budget, cancellation)
            .await
    }
}
