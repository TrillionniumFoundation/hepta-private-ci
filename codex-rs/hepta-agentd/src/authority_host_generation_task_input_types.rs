//! Bounded Root-owned task configuration data, never an admission or receipt.
//! The original task factory remains responsible for publication, Source,
//! registry, Cell, model and current-generation authentication.

use std::fs::File;
use std::path::PathBuf;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_neuron::CellCandidateMaskV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::invalid;
use super::model_types::Definition;
use crate::AgentdError;
use crate::CellQ24ModelFilesV1;
use crate::CircuitCellRouteV1;
use crate::CircuitTaskSourceInputV1;

/// Existing, host-selected descriptors. This value does not create paths,
/// represent a verified publication, or retain an alternative writer.
pub struct RootHostQ24TaskFilesV1 {
    pub source_journal: File,
    pub source_witness: File,
    pub cell_journal: File,
    pub cell_witness: File,
    pub inference_control: File,
    pub model: CellQ24ModelFilesV1,
}

#[derive(Clone, Copy, Eq, PartialEq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum TaskFilePurpose { Create, Recover }

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Deployment {
    pub schema_version: u32,
    pub purpose: String,
    pub source_mode: TaskFilePurpose,
    pub clock_epoch: String,
    pub definition: Definition,
    pub source: SourceInput,
    pub source_witness: Witness,
    pub cell_witness: Witness,
    pub inference_control_diagnostic_path: PathBuf,
    pub inference_control_capacity: usize,
    pub fence: Fence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<Route>,
    pub bundle: Bundle,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub queue_capacity: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Witness {
    scope_digest: [u8; 32],
    objective_digest: [u8; 32],
    generation: u64,
    pub max_records: usize,
}

impl Witness {
    pub(super) fn scope(&self) -> JournalScope {
        JournalScope {
            scope_digest: Digest32::from_array(self.scope_digest),
            objective_digest: Digest32::from_array(self.objective_digest),
        }
    }
    pub(super) fn generation(&self) -> Result<Generation, AgentdError> {
        Generation::new(self.generation).map_err(invalid)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SourceInput {
    agent_id: String,
    cell_id: String,
    run_id: String,
    principal_digest: [u8; 32],
    source_frontier: [u8; 32],
    objective_digest: [u8; 32],
    ndu_snapshot_digest: [u8; 32],
    monotonic_micros: u64,
    deadline_micros: u64,
    observation: Vec<u8>,
    candidates: Vec<Mask>,
    lease_duration_ms: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Mask { candidate_id: String, allowed: bool }

impl SourceInput {
    pub(super) fn into_original(self) -> Result<CircuitTaskSourceInputV1, AgentdError> {
        Ok(CircuitTaskSourceInputV1 {
            scope: CellScopeV1 {
                agent_id: StableId::new(self.agent_id).map_err(invalid)?,
                cell_id: StableId::new(self.cell_id).map_err(invalid)?,
                run_id: StableId::new(self.run_id).map_err(invalid)?,
                principal_digest: Digest32::from_array(self.principal_digest),
            },
            source_frontier: Digest32::from_array(self.source_frontier),
            objective_digest: Digest32::from_array(self.objective_digest),
            ndu_snapshot_digest: Digest32::from_array(self.ndu_snapshot_digest),
            monotonic_micros: self.monotonic_micros,
            deadline_micros: self.deadline_micros,
            observation: self.observation,
            candidates: self.candidates.into_iter().map(|candidate| {
                Ok(CellCandidateMaskV1 {
                    candidate_id: StableId::new(candidate.candidate_id).map_err(invalid)?,
                    allowed: candidate.allowed,
                })
            }).collect::<Result<_, AgentdError>>()?,
            lease_duration_ms: self.lease_duration_ms,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Fence {
    owner_agent_id: AgentId,
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
}

impl Fence {
    pub(super) fn into_original(self) -> Result<TaskFlowFence, AgentdError> {
        // These are the actual preheld Agent-local values. The original daemon
        // AutomationStore still authenticates its own fence; this is no mint.
        TaskFlowFence::new(self.owner_agent_id, self.owner_id, self.owner_epoch,
            self.generation, self.fencing_token).map_err(invalid)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Route {
    candidate_id: String,
    outcome: CircuitExitV2,
    selected_edges: Vec<String>,
}

impl Route {
    pub(super) fn into_original(self) -> Result<CircuitCellRouteV1, AgentdError> {
        Ok(CircuitCellRouteV1 {
            candidate_id: StableId::new(self.candidate_id).map_err(invalid)?,
            outcome: self.outcome,
            selected_edges: self.selected_edges,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Bundle {
    artifact_id: String,
    generation: u64,
    components: Components,
    training_lineage: Option<Lineage>,
    rollback_predecessor: Option<[u8; 32]>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Components {
    base: [u8; 32],
    organ_adapter: Option<[u8; 32]>,
    cell_adapter: Option<[u8; 32]>,
    heads: [u8; 32],
    composition: [u8; 32],
    encoder: [u8; 32],
    tokenizer: [u8; 32],
    normalizer: [u8; 32],
    calibration: [u8; 32],
    numeric_profile: [u8; 32],
    output_schema: [u8; 32],
    state_schema: [u8; 32],
    state_semantics: [u8; 32],
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Lineage {
    source_bundle: [u8; 32],
    dataset: [u8; 32],
    update_rule: [u8; 32],
    evaluation_profile: [u8; 32],
}

impl Bundle {
    pub(super) fn into_original(self) -> Result<CellCompatibilityBundleV1, AgentdError> {
        let c = self.components;
        let bundle = CellCompatibilityBundleV1 {
            artifact_id: StableId::new(self.artifact_id).map_err(invalid)?,
            generation: Generation::new(self.generation).map_err(invalid)?,
            components: CellBundleComponentsV1 {
                base: Digest32::from_array(c.base),
                organ_adapter: c.organ_adapter.map(Digest32::from_array),
                cell_adapter: c.cell_adapter.map(Digest32::from_array),
                heads: Digest32::from_array(c.heads),
                composition: Digest32::from_array(c.composition),
                encoder: Digest32::from_array(c.encoder),
                tokenizer: Digest32::from_array(c.tokenizer),
                normalizer: Digest32::from_array(c.normalizer),
                calibration: Digest32::from_array(c.calibration),
                numeric_profile: Digest32::from_array(c.numeric_profile),
                output_schema: Digest32::from_array(c.output_schema),
                state_schema: Digest32::from_array(c.state_schema),
                state_semantics: Digest32::from_array(c.state_semantics),
            },
            training_lineage: self.training_lineage.map(|lineage| CellTrainingLineageV1 {
                source_bundle: Digest32::from_array(lineage.source_bundle),
                dataset: Digest32::from_array(lineage.dataset),
                update_rule: Digest32::from_array(lineage.update_rule),
                evaluation_profile: Digest32::from_array(lineage.evaluation_profile),
            }),
            rollback_predecessor: self.rollback_predecessor.map(Digest32::from_array),
        };
        bundle.digest().map_err(invalid)?;
        Ok(bundle)
    }
}
