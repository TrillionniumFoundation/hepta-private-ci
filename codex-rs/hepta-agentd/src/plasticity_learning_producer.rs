//! Named bounded-channel producer behind the existing public runtime handle.
//!
//! It retains no writer, trust root, anchor or owner evidence. Every proposal
//! still crosses the same queue and the long-lived owner's currentness checks.

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use crate::PlasticityRuntimeCallErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCommandV1;

/// The single submission implementation shared by public runtime-handle clones.
#[derive(Clone)]
pub(crate) struct AgentdLearningPlasticityProducerV1 {
    sender: mpsc::Sender<PlasticityRuntimeCommandV1>,
}

impl AgentdLearningPlasticityProducerV1 {
    pub(crate) fn new(sender: mpsc::Sender<PlasticityRuntimeCommandV1>) -> Self {
        Self { sender }
    }

    pub(crate) async fn submit_parameter(
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

    pub(crate) async fn submit_topology(
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
}
