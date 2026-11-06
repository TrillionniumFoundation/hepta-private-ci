//! Versioned stateful backend protocol. Workers propose bytes; only the host
//! owner commits state and output. V1 feature and sparse bytes are unchanged.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::cell_task_cost::CellTaskCostV2;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationScopeV2 {
    pub principal_digest: [u8; 32],
    pub agent_id: String,
    pub cell_id: String,
    pub run_id: String,
}

/// A frozen inference bundle has no resumable optimizer. A resumable learner
/// must bind every member of its checkpoint closure, including its cursor.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CellLearningBindingV2 {
    Frozen {
        weights: [u8; 32],
    },
    Resumable {
        weights: [u8; 32],
        optimizer: [u8; 32],
        rng: [u8; 32],
        sampler: [u8; 32],
        training_cursor: [u8; 32],
    },
}

/// References to the existing evolution/artifacts owner, not a new authority
/// to adopt, publish or withdraw a bundle. The host verifies those references.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellEvolutionBindingV2 {
    pub structure: [u8; 32],
    pub lineage: [u8; 32],
    pub source_dependencies: [u8; 32],
    pub adoption_receipt: [u8; 32],
}

/// One input/state/output contract can name an encoder, head, memory, world
/// model or decoder. An absent component is explicit, never an invented model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellBackendManifestV2 {
    pub profile: String,
    pub source_digest: [u8; 32],
    pub bundle_digest: [u8; 32],
    pub encoder: Option<[u8; 32]>,
    pub head: Option<[u8; 32]>,
    pub memory: Option<[u8; 32]>,
    pub world_model: Option<[u8; 32]>,
    pub decoder: Option<[u8; 32]>,
    pub runtime_digest: [u8; 32],
    pub device_digest: [u8; 32],
    pub input_schema: [u8; 32],
    pub state_schema: [u8; 32],
    pub output_schema: [u8; 32],
    pub learning: CellLearningBindingV2,
    pub evolution: CellEvolutionBindingV2,
    pub max_input_bytes: u32,
    pub max_state_bytes: u32,
    pub max_delta_bytes: u32,
    pub max_prefix_bytes: u32,
    /// Receipt bounds are part of admission, so settlement always has capacity.
    pub max_step_cost_entries: u32,
    pub max_ack_cost_entries: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellRuntimeSnapshotV2 {
    pub scope: CellGenerationScopeV2,
    pub manifest_digest: [u8; 32],
    pub generation: u64,
    pub writer_epoch: u64,
    pub revision: u64,
    pub state: Vec<u8>,
    /// Exact irrevocable committed bytes, including chunks not yet acknowledged.
    pub prefix: Vec<u8>,
    pub stopped: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationRequestV2 {
    pub operation_id: String,
    pub task_digest: [u8; 32],
    pub source_frontier: [u8; 32],
    pub predecessor: CellRuntimeSnapshotV2,
    pub input: Vec<u8>,
    /// Host-owned monotonic epoch, preserved for the lifetime of this journal.
    pub admitted_at_micros: u64,
    pub deadline_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellGenerationDispositionV2 {
    Advanced,
    Stopped,
    Cancelled,
    Failed,
    Rejected,
    DeadlineExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationProposalV2 {
    pub request_digest: [u8; 32],
    pub bundle_digest: [u8; 32],
    pub runtime_digest: [u8; 32],
    pub device_digest: [u8; 32],
    pub successor_state: Vec<u8>,
    /// Unpublished bytes. This proposal and its cost grant no external effect.
    pub output_delta: Vec<u8>,
    pub disposition: CellGenerationDispositionV2,
    pub cost: CellTaskCostV2,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationReceiptV2 {
    pub operation_id: String,
    pub request_digest: [u8; 32],
    pub proposal_digest: [u8; 32],
    pub checkpoint_after: [u8; 32],
    pub disposition: CellGenerationDispositionV2,
    pub cost: CellTaskCostV2,
}

impl CellGenerationReceiptV2 {
    pub fn authority(&self) -> codex_hepta_types::AuthorityPosture {
        codex_hepta_types::AuthorityPosture::DENY_ALL
    }
}

/// Transport receives only an already committed item. An uncertain delivery
/// stays pending; replay must retain this exact operation ID, offset and bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellOutputChunkV2 {
    pub operation_id: String,
    pub request_digest: [u8; 32],
    pub prefix_offset: u64,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellGenerationErrorV2 {
    InvalidBinding,
    Capacity,
    Conflict,
    Pending,
    Draining,
    Stopped,
    Deadline,
    Unavailable,
    CommitUncertain,
    Corrupt,
    AcknowledgedHistoryMissing,
}

impl std::fmt::Display for CellGenerationErrorV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellGenerationErrorV2 {}

/// Implement at the admitted inference-control/worker boundary. Execute must
/// recheck its reservation and live deadline; it cannot persist owner state or
/// publish output. Readback inspects only this original request, never submits
/// another computation. An error or missing receipt does not prove no contact.
pub trait CellGenerationControlPortV2 {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2>;

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2>;

    fn cancel_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2>;
}

impl CellBackendManifestV2 {
    pub fn digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        StableId::new(&self.profile).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let mut digests = vec![
            self.source_digest,
            self.bundle_digest,
            self.runtime_digest,
            self.device_digest,
            self.input_schema,
            self.state_schema,
            self.output_schema,
            self.evolution.structure,
            self.evolution.lineage,
            self.evolution.source_dependencies,
            self.evolution.adoption_receipt,
        ];
        let components = [
            self.encoder,
            self.head,
            self.memory,
            self.world_model,
            self.decoder,
        ];
        if components.iter().all(Option::is_none) {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        digests.extend(components.into_iter().flatten());
        match &self.learning {
            CellLearningBindingV2::Frozen { weights } => digests.push(*weights),
            CellLearningBindingV2::Resumable {
                weights,
                optimizer,
                rng,
                sampler,
                training_cursor,
            } => {
                digests.extend([*weights, *optimizer, *rng, *sampler, *training_cursor]);
            }
        }
        if digests.contains(&[0; 32]) {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if !(1..=65_536).contains(&self.max_input_bytes)
            || !(1..=65_536).contains(&self.max_state_bytes)
            || !(1..=65_536).contains(&self.max_delta_bytes)
            || !(1..=262_144).contains(&self.max_prefix_bytes)
            || self.max_delta_bytes > self.max_prefix_bytes
            || !(1..=32).contains(&self.max_step_cost_entries)
            || !(1..=16).contains(&self.max_ack_cost_entries)
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        digest(b"hepta.cell.backend.v2\0", self)
    }
}

impl CellRuntimeSnapshotV2 {
    pub fn digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        for id in [
            &self.scope.agent_id,
            &self.scope.cell_id,
            &self.scope.run_id,
        ] {
            StableId::new(id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        }
        if self.scope.principal_digest == [0; 32]
            || self.manifest_digest == [0; 32]
            || self.generation == 0
            || self.writer_epoch == 0
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if self.state.len() > 65_536 || self.prefix.len() > 262_144 {
            return Err(CellGenerationErrorV2::Capacity);
        }
        digest(b"hepta.cell.runtime-state.v2\0", self)
    }
}

impl CellGenerationRequestV2 {
    pub fn digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        StableId::new(&self.operation_id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        self.predecessor.digest()?;
        if self.task_digest == [0; 32]
            || self.source_frontier == [0; 32]
            || self.admitted_at_micros == 0
            || self.deadline_micros <= self.admitted_at_micros
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if self.input.len() > 65_536 {
            return Err(CellGenerationErrorV2::Capacity);
        }
        digest(b"hepta.cell.generation-request.v2\0", self)
    }
}

pub(crate) fn digest(
    domain: &[u8],
    value: &impl Serialize,
) -> Result<[u8; 32], CellGenerationErrorV2> {
    let bytes = serde_json::to_vec(value).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    Ok(Digest32::of_parts(&[domain, &bytes]).into_array())
}
