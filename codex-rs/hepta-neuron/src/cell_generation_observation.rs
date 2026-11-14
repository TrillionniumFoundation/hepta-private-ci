//! Immutable episode observations captured by the existing Cell journal owner.
//! Pending work and delivery remain separate from recorded cost lower bounds.

use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::cell_generation_state::CellGenerationConfigV2;
use crate::cell_generation_state::GenerationState;
use crate::cell_generation_types::CellGenerationErrorV2;
use crate::cell_generation_types::CellGenerationRequestV2;
use crate::cell_generation_types::CellOutputChunkV2;
use crate::cell_generation_types::CellRuntimeSnapshotV2;
use crate::cell_generation_types::digest;
use crate::cell_task_cost::CellCostMetricsV2;
use crate::cell_task_cost::CellTaskCostV2;

/// A single healthy owner cut. Private fields and no deserializer prevent a
/// caller from presenting separately sampled or caller-constructed task facts
/// as an owner observation. This value confers no dispatch or effect authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellGenerationObservationV1 {
    task_digest: [u8; 32],
    source_frontier: [u8; 32],
    initial_snapshot_digest: [u8; 32],
    first_advance_input_digest: Option<[u8; 32]>,
    owner_checkpoint: [u8; 32],
    snapshot: CellRuntimeSnapshotV2,
    cost: CellTaskCostV2,
    pending_request_digest: Option<[u8; 32]>,
    pending_output: Option<CellOutputChunkV2>,
}

impl CellGenerationObservationV1 {
    pub(crate) fn capture(
        config: &CellGenerationConfigV2,
        state: &GenerationState,
        owner_checkpoint: Digest32,
    ) -> Result<Self, CellGenerationErrorV2> {
        state
            .cost
            .validate()
            .map_err(|_| CellGenerationErrorV2::Corrupt)?;
        Ok(Self {
            task_digest: config.task_digest,
            source_frontier: config.source_frontier,
            initial_snapshot_digest: config.initial.digest()?,
            first_advance_input_digest: state.first_advance_input_digest,
            owner_checkpoint: owner_checkpoint.into_array(),
            snapshot: state.snapshot.clone(),
            cost: state.cost.clone(),
            pending_request_digest: state
                .pending
                .as_ref()
                .map(CellGenerationRequestV2::digest)
                .transpose()?,
            pending_output: state.outbox.clone(),
        })
    }

    pub fn task_digest(&self) -> [u8; 32] {
        self.task_digest
    }

    pub fn source_digest(&self) -> [u8; 32] {
        self.cost.identity().source_digest
    }

    pub fn source_frontier(&self) -> [u8; 32] {
        self.source_frontier
    }

    pub fn manifest_digest(&self) -> [u8; 32] {
        self.snapshot.manifest_digest
    }

    pub fn initial_snapshot_digest(&self) -> [u8; 32] {
        self.initial_snapshot_digest
    }

    /// Exact input to the first adopted Advanced/Stopped result, reconstructed
    /// from retained admission/commit events. Failed or cancelled work cannot
    /// become evidence that a backend initialization was actually adopted.
    pub fn first_advance_input_digest(&self) -> Option<[u8; 32]> {
        self.first_advance_input_digest
    }

    pub fn snapshot(&self) -> &CellRuntimeSnapshotV2 {
        &self.snapshot
    }

    /// Includes the frozen config and every retained event, including ACKs,
    /// cancellation and costs that do not advance the runtime snapshot.
    pub fn owner_checkpoint(&self) -> Digest32 {
        Digest32::from_array(self.owner_checkpoint)
    }

    /// Recorded observations only. Their known sum remains a lower bound
    /// while work, delivery, stage coverage or any metric is unresolved.
    pub fn cost(&self) -> &CellTaskCostV2 {
        &self.cost
    }

    pub fn pending_request_digest(&self) -> Option<[u8; 32]> {
        self.pending_request_digest
    }

    pub fn pending_output(&self) -> Option<&CellOutputChunkV2> {
        self.pending_output.as_ref()
    }

    /// STOP with no unresolved worker or delivery. This is an episode
    /// lifecycle observation, not evidence of output quality or model benefit.
    pub fn is_terminal(&self) -> bool {
        self.snapshot.stopped
            && self.pending_request_digest.is_none()
            && self.pending_output.is_none()
    }

    /// Complete only relative to recorded stage coverage and meter claims.
    /// A measured subtotal never closes an unresolved episode or delivery.
    pub fn complete_metrics(&self) -> Option<CellCostMetricsV2> {
        if !self.is_terminal() {
            return None;
        }
        self.cost.summary().ok()?.complete_metrics()
    }

    pub fn digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        digest(b"hepta.cell.generation-observation.v1\0", self)
    }
}
