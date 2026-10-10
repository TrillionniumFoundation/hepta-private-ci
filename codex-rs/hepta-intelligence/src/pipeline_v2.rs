//! Capability snapshot consumer using the existing shadow stage engine.
//!
//! Optional adapters are not called when absent. Their fallback evidence names
//! a configuration absence, never a fabricated owner response or model artifact.
//! The distinct V2 receipt envelope binds a V2 snapshot to a shared trace format.
//! Admission of owner facts, transport isolation and deployment remain host jobs.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::LaneFBudgetV1;
use crate::LaneFShadowPipelineReceiptV1;
use crate::LaneFShadowPortsV1;
use crate::PipelineErrorV1;
use crate::PortFailureClassV1;
use crate::PortFailureV1;
use crate::PortInputV1;
use crate::PortReceiptV1;
use crate::pipeline::PipelineRunInput;
use crate::pipeline::run_admitted_pipeline;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFRunRequestV2 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub budget: LaneFBudgetV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PipelineErrorV2 {
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    Pipeline(PipelineErrorV1),
}

impl fmt::Display for PipelineErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for PipelineErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFShadowPipelineReceiptV2 {
    trace: LaneFShadowPipelineReceiptV1,
    absent_adapters: Vec<&'static str>,
    receipt_digest: Digest32,
}

impl LaneFShadowPipelineReceiptV2 {
    /// The shared trace format does not change the receipt's V2 snapshot domain.
    #[must_use]
    pub fn trace(&self) -> &LaneFShadowPipelineReceiptV1 {
        &self.trace
    }

    #[must_use]
    pub fn absent_adapters(&self) -> &[&'static str] {
        &self.absent_adapters
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.receipt_digest
    }
}

pub fn run_shadow_pipeline_v2<P: LaneFShadowPortsV1>(
    request: LaneFRunRequestV2,
    ports: &mut P,
) -> Result<LaneFShadowPipelineReceiptV2, PipelineErrorV2> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("dispatch.proposal", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ] {
        match request.snapshot.bound_owner(capability) {
            None => return Err(PipelineErrorV2::MissingCapability(capability)),
            Some(actual) if actual != owner => {
                return Err(PipelineErrorV2::OwnerMismatch(capability));
            }
            Some(_) => {}
        }
    }
    let mut absent_adapters = Vec::new();
    for (capability, owner) in [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ] {
        match request.snapshot.bound_owner(capability) {
            None => absent_adapters.push(capability),
            Some(actual) if actual != owner => {
                return Err(PipelineErrorV2::OwnerMismatch(capability));
            }
            Some(_) => {}
        }
    }
    let snapshot_digest = request.snapshot.digest();
    let mut adapter = CapabilityPorts {
        inner: ports,
        snapshot: &request.snapshot,
    };
    let trace = run_admitted_pipeline(
        PipelineRunInput {
            run_id: request.run_id,
            request_digest: request.request_digest,
            budget: request.budget,
        },
        snapshot_digest,
        &mut adapter,
    )
    .map_err(PipelineErrorV2::Pipeline)?;
    let mut bytes = b"hepta.intelligence.lane-f-pipeline.v2\0".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(trace.trace_digest.as_array());
    for capability in &absent_adapters {
        bytes.extend_from_slice(capability.as_bytes());
        bytes.push(0);
    }
    Ok(LaneFShadowPipelineReceiptV2 {
        trace,
        absent_adapters,
        receipt_digest: Digest32::of_bytes(&bytes),
    })
}

struct CapabilityPorts<'a, P> {
    inner: &'a mut P,
    snapshot: &'a CapabilitySnapshotV2,
}

fn absent(snapshot: &CapabilitySnapshotV2, capability: &str) -> PortFailureV1 {
    let mut bytes = b"hepta.intelligence.absent-adapter.v2\0".to_vec();
    bytes.extend_from_slice(snapshot.digest().as_array());
    bytes.extend_from_slice(capability.as_bytes());
    PortFailureV1 {
        class: PortFailureClassV1::Unavailable,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

impl<P: LaneFShadowPortsV1> LaneFShadowPortsV1 for CapabilityPorts<'_, P> {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.validate_objective(input)
    }
    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.build_legal_set(input)
    }
    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        if self.snapshot.bound_owner("neural.signal").is_none() {
            return Err(absent(self.snapshot, "neural.signal"));
        }
        self.inner.collect_neural_signal(input)
    }
    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        if self.snapshot.bound_owner("prompt.portfolio").is_none() {
            return Err(absent(self.snapshot, "prompt.portfolio"));
        }
        self.inner.build_prompt_portfolio(input)
    }
    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.decide_intuition(input)
    }
    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.compile_context(input)
    }
    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.propose_dispatch(input)
    }
    fn record_learning(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.inner.record_learning(input)
    }
}

#[cfg(test)]
#[path = "pipeline_v2_tests.rs"]
mod tests;
