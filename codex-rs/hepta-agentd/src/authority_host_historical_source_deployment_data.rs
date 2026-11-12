//! Fixed single-published-Q24 Source data from the Root0600 deployment file.
//! It contains no execution observation, pin, completion flag, grant or retired claim.

use std::fs::File;
use std::io;
use std::path::PathBuf;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_neuron::CellCandidateMaskV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::AgentdIdentity;
use crate::CircuitCellRouteV1;
use crate::CircuitTaskSourceInputV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::RootHistoricalSourceInputsV1;

#[path = "authority_host_historical_source_deployment_cell.rs"]
mod cell;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SourceDeploymentData {
    pub(super) schema_version: u32,
    pub(super) purpose: String,
    pub(super) source_journal: PathBuf,
    pub(super) source_witness: PathBuf,
    witness_scope: [u8; 32],
    witness_objective: [u8; 32],
    witness_generation: u64,
    witness_records: usize,
    fence: FenceData,
    circuit: BoundedCircuitDefinitionV2,
    routes: Vec<RouteData>,
    definition: cell::CellData,
    source: SourceData,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FenceData {
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteData {
    candidate_id: String,
    outcome: CircuitExitV2,
    selected_edges: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceData {
    cell_id: String,
    run_id: String,
    principal_digest: [u8; 32],
    source_frontier: [u8; 32],
    objective_digest: [u8; 32],
    ndu_snapshot_digest: [u8; 32],
    monotonic_micros: u64,
    deadline_micros: u64,
    observation: Vec<u8>,
    candidates: Vec<MaskData>,
    lease_duration_ms: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MaskData {
    candidate_id: String,
    allowed: bool,
}

impl SourceDeploymentData {
    pub(super) fn into_inputs(
        self,
        identity: &AgentdIdentity,
        journal: File,
        witness: File,
    ) -> io::Result<RootHistoricalSourceInputsV1> {
        let original = self.into_configuration(identity)?;
        let registry = original.registry().map_err(io::Error::other)?;
        Ok(RootHistoricalSourceInputsV1 {
            journal,
            witness,
            witness_scope: original.witness_scope,
            witness_generation: original.witness_generation,
            witness_records: original.witness_records,
            fence: original.fence,
            registry,
            definition: original.definition,
            source: original.source,
        })
    }

    fn into_configuration(
        self,
        identity: &AgentdIdentity,
    ) -> io::Result<OriginalSingleQ24SourceConfigurationV1> {
        if self.schema_version != 1 || self.purpose != super::DEPLOYMENT_PURPOSE {
            return Err(io::Error::other(
                "original single Q24 Source deployment required",
            ));
        }
        let definition = self.definition.into_definition()?;
        let source = self.source;
        let original = OriginalSingleQ24SourceConfigurationV1 {
            source_journal: self.source_journal,
            source_witness: self.source_witness,
            witness_scope: JournalScope {
                scope_digest: Digest32::from_array(self.witness_scope),
                objective_digest: Digest32::from_array(self.witness_objective),
            },
            witness_generation: Generation::new(self.witness_generation)
                .map_err(io::Error::other)?,
            witness_records: self.witness_records,
            fence: TaskFlowFence::new(
                identity.agent_id.clone(),
                self.fence.owner_id,
                self.fence.owner_epoch,
                self.fence.generation,
                self.fence.fencing_token,
            )
            .map_err(io::Error::other)?,
            circuit: self.circuit,
            routes: self
                .routes
                .into_iter()
                .map(|route| {
                    Ok(CircuitCellRouteV1 {
                        candidate_id: StableId::new(route.candidate_id)
                            .map_err(io::Error::other)?,
                        outcome: route.outcome,
                        selected_edges: route.selected_edges,
                    })
                })
                .collect::<io::Result<Vec<_>>>()?,
            definition,
            source: CircuitTaskSourceInputV1 {
                scope: CellScopeV1 {
                    agent_id: StableId::new(identity.agent_id.as_str())
                        .map_err(io::Error::other)?,
                    cell_id: StableId::new(source.cell_id).map_err(io::Error::other)?,
                    run_id: StableId::new(source.run_id).map_err(io::Error::other)?,
                    principal_digest: Digest32::from_array(source.principal_digest),
                },
                source_frontier: Digest32::from_array(source.source_frontier),
                objective_digest: Digest32::from_array(source.objective_digest),
                ndu_snapshot_digest: Digest32::from_array(source.ndu_snapshot_digest),
                monotonic_micros: source.monotonic_micros,
                deadline_micros: source.deadline_micros,
                observation: source.observation,
                candidates: source
                    .candidates
                    .into_iter()
                    .map(|mask| {
                        Ok(CellCandidateMaskV1 {
                            candidate_id: StableId::new(mask.candidate_id)
                                .map_err(io::Error::other)?,
                            allowed: mask.allowed,
                        })
                    })
                    .collect::<io::Result<Vec<_>>>()?,
                lease_duration_ms: source.lease_duration_ms,
            },
        };
        original.registry().map_err(io::Error::other)?;
        Ok(original)
    }
}

impl OriginalSingleQ24SourceConfigurationV1 {
    /// Decode the same complete Source preimage without acquiring Root custody,
    /// opening an owner, or asserting that an observation actually occurred.
    pub(crate) fn from_original_deployment_bytes(
        bytes: &[u8],
        identity: &AgentdIdentity,
    ) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > 1_048_576 {
            return Err(io::Error::other("original Source deployment size bound"));
        }
        let data: SourceDeploymentData = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        data.into_configuration(identity)
    }
}
