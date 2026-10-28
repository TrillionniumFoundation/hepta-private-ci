//! Immutable routing pins. Neither a route nor a deployment grants access.

use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::FederationCapability;
use codex_hepta_memory::memory_cell_scope_id;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;
use serde::Serializer;

pub const MAX_MEMORY_CELL_NETWORK_NODES: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellNetworkVersionV1 {
    pub generation: ContractGenerationV1,
    pub deployment_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellVersionPinV1 {
    pub scope: ContractIdV1,
    pub owner_cut_digest: ContractDigestV1,
    pub generation: ContractGenerationV1,
    pub bundle_digest: ContractDigestV1,
}

/// The grant comes from the existing cognitive owner, whose capability has
/// private fields and no deserializer. Every attempt still asks that actual
/// owner's control service for its current capability revision and generation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellNodeBindingV1 {
    #[serde(serialize_with = "serialize_node_id")]
    pub(super) node_id: StableId,
    pub(super) grant: FederationCapability,
    pub(super) spawn_generation: u64,
    pub(super) pin: MemoryCellVersionPinV1,
    pub(super) probe: MemoryRequestV1,
}

impl MemoryCellNodeBindingV1 {
    pub fn new(
        node_id: StableId,
        grant: FederationCapability,
        spawn_generation: u64,
        pin: MemoryCellVersionPinV1,
        probe: MemoryRequestV1,
    ) -> Result<Self, String> {
        probe.validate().map_err(|error| error.to_string())?;
        let scope = memory_cell_scope_id(grant.owner_agent_id(), grant.scope().owner_scope())
            .map_err(|error| error.to_string())?;
        if spawn_generation == 0
            || node_id.as_str() == "memory.network.router"
            || probe.scope != pin.scope
            || pin.scope != scope
        {
            return Err("memory node scope, generation or identity mismatch".to_string());
        }
        Ok(Self {
            node_id,
            grant,
            spawn_generation,
            pin,
            probe,
        })
    }

    pub fn node_id(&self) -> &StableId {
        &self.node_id
    }
    pub fn owner_agent_id(&self) -> &AgentId {
        self.grant.owner_agent_id()
    }
    pub fn pin(&self) -> &MemoryCellVersionPinV1 {
        &self.pin
    }
    pub(super) fn digest(&self) -> Result<Digest32, String> {
        serde_json::to_vec(self)
            .map(|bytes| Digest32::of_bytes(&bytes))
            .map_err(|error| error.to_string())
    }
}

/// One complete version vector. Different source owners retain their own cuts;
/// activation never substitutes a shared, caller-claimed owner snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellDeploymentV1 {
    pub(super) generation: ContractGenerationV1,
    pub(super) nodes: Vec<MemoryCellNodeBindingV1>,
    #[serde(skip)]
    pub(super) digest: ContractDigestV1,
}

impl MemoryCellDeploymentV1 {
    pub fn new(
        generation: ContractGenerationV1,
        mut nodes: Vec<MemoryCellNodeBindingV1>,
    ) -> Result<Self, String> {
        if nodes.is_empty() || nodes.len() > MAX_MEMORY_CELL_NETWORK_NODES {
            return Err("memory deployment node budget exceeded".to_string());
        }
        nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        let owners: BTreeSet<_> = nodes
            .iter()
            .map(|node| node.grant.owner_agent_id())
            .collect();
        if nodes
            .windows(2)
            .any(|pair| pair[0].node_id == pair[1].node_id)
            || owners.len() != nodes.len()
            || nodes
                .iter()
                .any(|node| node.grant.consumer_agent_id() != nodes[0].grant.consumer_agent_id())
        {
            return Err("memory deployment repeats an owner/node or changes consumer".to_string());
        }
        let bytes = serde_json::to_vec(&("hepta.memory.network.deployment.v1", generation, &nodes))
            .map_err(|error| error.to_string())?;
        if bytes.len() > codex_hepta_control_plane::MAX_ORGAN_MESSAGE_BYTES {
            return Err("memory deployment metadata exceeds organ bound".to_string());
        }
        let digest = ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
            .map_err(|error| error.to_string())?;
        Ok(Self {
            generation,
            nodes,
            digest,
        })
    }

    pub fn version(&self) -> MemoryCellNetworkVersionV1 {
        MemoryCellNetworkVersionV1 {
            generation: self.generation,
            deployment_digest: self.digest,
        }
    }
    pub fn nodes(&self) -> &[MemoryCellNodeBindingV1] {
        &self.nodes
    }
}

/// Actual control-transport counts; elapsed time includes validation/probes.
/// These counters exclude kernel framing, remote inference CPU and storage.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct MemoryCellNetworkCostV1 {
    pub rpc_attempts: u64,
    pub transmitted_bytes: u64,
    pub received_bytes: u64,
    pub elapsed_micros: u64,
}

#[derive(Debug)]
pub struct MemoryCellNetworkErrorV1 {
    pub reason: String,
    pub cost: MemoryCellNetworkCostV1,
}

impl std::fmt::Display for MemoryCellNetworkErrorV1 {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(output, "{}", self.reason)
    }
}
impl std::error::Error for MemoryCellNetworkErrorV1 {}

impl From<String> for MemoryCellNetworkErrorV1 {
    fn from(reason: String) -> Self {
        Self {
            reason,
            cost: MemoryCellNetworkCostV1::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct MemoryCellNodeReadoutV1 {
    #[serde(serialize_with = "serialize_node_id")]
    pub node_id: StableId,
    pub owner_agent_id: AgentId,
    pub readout: MemoryReadoutV1,
}

// Keep the validated ID opaque in memory; only this metadata field is a string.
fn serialize_node_id<S>(node_id: &StableId, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_str(node_id.as_str())
}

/// Read evidence from one unchanged deployment admission epoch. The network's
/// final-use method rechecks the complete vector, not just returned nodes.
pub struct MemoryCellNetworkReadV1 {
    pub(super) host_token: Arc<()>,
    pub(super) version: MemoryCellNetworkVersionV1,
    pub(super) admission_epoch: u64,
    pub(super) readouts: Vec<MemoryCellNodeReadoutV1>,
    pub(super) cost: MemoryCellNetworkCostV1,
}

impl MemoryCellNetworkReadV1 {
    pub fn version(&self) -> MemoryCellNetworkVersionV1 {
        self.version
    }
    pub fn readouts(&self) -> &[MemoryCellNodeReadoutV1] {
        &self.readouts
    }
    pub fn cost(&self) -> MemoryCellNetworkCostV1 {
        self.cost
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryCellNetworkReceiptV1 {
    pub version: MemoryCellNetworkVersionV1,
    pub cost: MemoryCellNetworkCostV1,
}
