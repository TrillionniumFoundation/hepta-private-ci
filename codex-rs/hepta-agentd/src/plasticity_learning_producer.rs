//! Named in-process submission boundary for the generation's plasticity owner.
//!
//! The producer owns only a bounded sender. The supervised owner retains every
//! writer, anchor store, trust root and owner-evidence store, and revalidates each
//! request before admission. Creating or cloning a producer grants no selection,
//! model installation, topology application, promotion or release authority.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use crate::PlasticityRuntimeCallErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCommandV1;

/// Bounded producer retained by Agentd for one generation's exclusive owner.
///
/// Existing callers may use the `PlasticityRuntimeHandleV1` alias and its
/// `propose_parameter` / `propose_topology` methods for the same submission path.
#[derive(Clone)]
pub struct AgentdLearningPlasticityProducerV1 {
    sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(sender: mpsc::Sender<PlasticityRuntimeCommandV1>) -> Self {
        Self { sender }
    }

    /// Submit a parameter request for the live owner's final admission checks.
    pub async fn submit_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Parameter {
                request: Box::new(request),
                now,
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    /// Submit a topology request for the live owner's final admission checks.
    pub async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::Topology {
                request: Box::new(request),
                now,
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }

    /// Compatibility entrypoint for the existing runtime handle API.
    pub async fn propose_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<ParameterPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.submit_parameter(request, now).await
    }

    /// Compatibility entrypoint for the existing runtime handle API.
    pub async fn propose_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.submit_topology(request, now).await
    }
}
