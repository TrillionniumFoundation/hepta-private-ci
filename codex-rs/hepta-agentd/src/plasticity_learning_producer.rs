//! Named non-test learning/self-iteration producer for governed plasticity.
//!
//! This adapter is intentionally internal to Agentd. It owns no mutable writer,
//! trust root, owner-evidence store or authority. AgentdState retains it as the
//! only product-side producer facade; the long-lived runtime owner still
//! re-resolves current owner frontiers, revalidates independent evidence and
//! withholds success until the rollback-domain anchor commit succeeds.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use tokio_util::sync::CancellationToken;

use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;
use crate::SelfIterationParameterReceiptV1;
use crate::SelfIterationParameterSubmissionV1;
use crate::SelfIterationTopologyReceiptV1;
use crate::SelfIterationTopologySubmissionV1;

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

    pub(crate) async fn submit_parameter_controlled(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_parameter_controlled(request, now, deadline_unix_seconds, cancellation)
            .await
    }

    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }

    pub(crate) async fn submit_topology_controlled(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        deadline_unix_seconds: u64,
        cancellation: CancellationToken,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_topology_controlled(request, now, deadline_unix_seconds, cancellation)
            .await
    }

    pub(crate) async fn submit_self_iteration_parameter(
        &self,
        submission: SelfIterationParameterSubmissionV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationParameterReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_self_iteration_parameter(submission, now, cancellation)
            .await
    }

    pub(crate) async fn submit_self_iteration_topology(
        &self,
        submission: SelfIterationTopologySubmissionV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<SelfIterationTopologyReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle
            .propose_self_iteration_topology(submission, now, cancellation)
            .await
    }

    #[must_use]
    pub(crate) fn metrics_snapshot(&self) -> crate::PlasticityRuntimeMetricsSnapshotV1 {
        self.handle.metrics_snapshot()
    }
}
