#![forbid(unsafe_code)]

use hnmf_reference::{
    ActivationPath, ActiveNode, Contradiction, EngramNode, EngramPopulation, EventId, FabricConfig,
    FabricError, ForgetBatch, MemoryCue, MemoryEvent, NodeId, OutcomeSignal, PPM, PlasticityBatch,
    RecallAbstainReason, RecallPacket, ReplayCandidate, ReplaySelectionReceipt, Synapse,
    SynapseRelation, ThresholdProposal, WeightProposal,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

pub const MAX_STORED_EVENTS: usize = 65_536;
pub const MAX_GRAPH_HOPS: u8 = 4;
pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HardeningConfig {
    pub maximum_stored_events: usize,
    pub maximum_candidate_events: usize,
    pub maximum_graph_hops: u8,
}

impl Default for HardeningConfig {
    fn default() -> Self {
        Self {
            maximum_stored_events: 16_384,
            maximum_candidate_events: 512,
            maximum_graph_hops: 2,
        }
    }
}

impl HardeningConfig {
    pub fn validate(self) -> Result<(), HardeningError> {
        if self.maximum_stored_events == 0
            || self.maximum_stored_events > MAX_STORED_EVENTS
            || self.maximum_candidate_events == 0
            || self.maximum_candidate_events > 512
            || self.maximum_candidate_events > self.maximum_stored_events
            || self.maximum_graph_hops == 0
            || self.maximum_graph_hops > MAX_GRAPH_HOPS
        {
            return Err(HardeningError::BoundExceeded("hardening configuration"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundRecallPacket {
    pub source_cue: MemoryCue,
    pub candidate_event_ids: Vec<EventId>,
    pub expanded_node_ids: Vec<NodeId>,
    pub packet: RecallPacket,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundPlasticityBatch {
    pub source_packet: BoundRecallPacket,
    pub outcome_signal: OutcomeSignal,
    pub batch: PlasticityBatch,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExactForgetBatch {
    pub batch: ForgetBatch,
    pub exact_support_closure: bool,
    pub production_activation_allowed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HardeningError {
    Reference(FabricError),
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    AuthorityBoundary,
    ArithmeticOverflow,
}

impl From<FabricError> for HardeningError {
    fn from(value: FabricError) -> Self {
        Self::Reference(value)
    }
}

impl fmt::Display for HardeningError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Reference(error) => write!(formatter, "HNMF reference error: {error}"),
            Self::Invalid(message) => write!(formatter, "invalid HNMF hardening input: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "HNMF hardening bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "HNMF hardening conflict: {message}"),
            Self::Missing(name) => write!(formatter, "HNMF hardening object missing: {name}"),
            Self::AuthorityBoundary => {
                write!(formatter, "HNMF hardening authority boundary crossed")
            }
            Self::ArithmeticOverflow => write!(formatter, "HNMF hardening arithmetic overflow"),
        }
    }
}

impl std::error::Error for HardeningError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HardenedFabric {
    generation: u64,
    runtime: FabricConfig,
    hardening: HardeningConfig,
    events: BTreeMap<EventId, MemoryEvent>,
    nodes: BTreeMap<NodeId, EngramNode>,
    synapses: BTreeMap<(NodeId, NodeId, SynapseRelation), Synapse>,
}

impl HardenedFabric {
    pub fn new(
        generation: u64,
        runtime: FabricConfig,
        hardening: HardeningConfig,
    ) -> Result<Self, HardeningError> {
        if generation == 0 {
            return Err(HardeningError::Invalid("generation must be non-zero"));
        }
        runtime.validate()?;
        hardening.validate()?;
        if hardening.maximum_candidate_events > runtime.maximum_candidate_events {
            return Err(HardeningError::BoundExceeded(
                "candidate bound exceeds runtime reference bound",
            ));
        }
        Ok(Self {
            generation,
            runtime,
            hardening,
            events: BTreeMap::new(),
            nodes: BTreeMap::new(),
            synapses: BTreeMap::new(),
        })
    }

    pub const fn generation(&self) -> u64 {
        self.generation
    }

    pub fn event(&self, event_id: EventId) -> Option<&MemoryEvent> {
        self.events.get(&event_id)
    }

    pub fn node(&self, node_id: NodeId) -> Option<&EngramNode> {
        self.nodes.get(&node_id)
    }

    pub fn synapse(
        &self,
        source: NodeId,
        target: NodeId,
        relation: SynapseRelation,
    ) -> Option<&Synapse> {
        self.synapses.get(&(source, target, relation))
    }

    pub fn insert_event(&mut self, event: MemoryEvent) -> Result<(), HardeningError> {
        event.validate()?;
        if self.events.len() >= self.hardening.maximum_stored_events
            && !self.events.contains_key(&event.id)
        {
            return Err(HardeningError::BoundExceeded("stored events"));
        }
        insert_exact(&mut self.events, event.id, event, "event identity")
    }

    pub fn insert_node(&mut self, node: EngramNode) -> Result<(), HardeningError> {
        node.validate()?;
        if self.nodes.len() >= self.runtime.maximum_nodes && !self.nodes.contains_key(&node.id) {
            return Err(HardeningError::BoundExceeded("nodes"));
        }
        if node
            .support_events
            .iter()
            .any(|event_id| !self.events.contains_key(event_id))
        {
            return Err(HardeningError::Missing("node support event"));
        }
        insert_exact(&mut self.nodes, node.id, node, "node identity")
    }

    pub fn insert_synapse(&mut self, synapse: Synapse) -> Result<(), HardeningError> {
        synapse.validate()?;
        let key = (synapse.source, synapse.target, synapse.relation);
        if self.synapses.len() >= self.runtime.maximum_synapses && !self.synapses.contains_key(&key)
        {
            return Err(HardeningError::BoundExceeded("synapses"));
        }
        if !self.nodes.contains_key(&synapse.source) || !self.nodes.contains_key(&synapse.target) {
            return Err(HardeningError::Missing("synapse endpoint"));
        }
        if synapse
            .support_events
            .iter()
            .any(|event_id| !self.events.contains_key(event_id))
        {
            return Err(HardeningError::Missing("synapse support event"));
        }
        insert_exact(&mut self.synapses, key, synapse, "synapse identity")
    }

    pub fn validate(&self) -> Result<(), HardeningError> {
        self.runtime.validate()?;
        self.hardening.validate()?;
        if self.generation == 0
            || self.events.len() > self.hardening.maximum_stored_events
            || self.nodes.len() > self.runtime.maximum_nodes
            || self.synapses.len() > self.runtime.maximum_synapses
        {
            return Err(HardeningError::BoundExceeded("fabric snapshot"));
        }
        for event in self.events.values() {
            event.validate()?;
        }
        for node in self.nodes.values() {
            node.validate()?;
            if node
                .support_events
                .iter()
                .any(|event_id| !self.events.contains_key(event_id))
            {
                return Err(HardeningError::Missing("node support event"));
            }
        }
        for synapse in self.synapses.values() {
            synapse.validate()?;
            if !self.nodes.contains_key(&synapse.source)
                || !self.nodes.contains_key(&synapse.target)
            {
                return Err(HardeningError::Missing("synapse endpoint"));
            }
            if synapse
                .support_events
                .iter()
                .any(|event_id| !self.events.contains_key(event_id))
            {
                return Err(HardeningError::Missing("synapse support event"));
            }
        }
        Ok(())
    }
}

fn insert_exact<K: Ord + Clone, V: Eq>(
    map: &mut BTreeMap<K, V>,
    key: K,
    value: V,
    conflict: &'static str,
) -> Result<(), HardeningError> {
    if let Some(existing) = map.get(&key) {
        return if existing == &value {
            Ok(())
        } else {
            Err(HardeningError::Conflict(conflict))
        };
    }
    map.insert(key, value);
    Ok(())
}

fn eligible(event: &MemoryEvent, now_unix_ms: i64) -> bool {
    !event.tombstoned
        && event.valid_from_unix_ms <= now_unix_ms
        && event.valid_to_unix_ms.is_none_or(|end| now_unix_ms < end)
}

fn mul_ppm(left: i64, right: i64) -> Result<i64, HardeningError> {
    left.checked_mul(right)
        .ok_or(HardeningError::ArithmeticOverflow)
        .map(|value| value / PPM)
}

const fn clamp(value: i64, minimum: i64, maximum: i64) -> i64 {
    if value < minimum {
        minimum
    } else if value > maximum {
        maximum
    } else {
        value
    }
}

fn ratio_ppm(numerator: usize, denominator: usize) -> u32 {
    if denominator == 0 {
        return 0;
    }
    numerator
        .saturating_mul(PPM as usize)
        .checked_div(denominator)
        .unwrap_or(0)
        .min(PPM as usize) as u32
}

mod learning;
mod recall;

pub use learning::select_replay_hardened;

#[cfg(test)]
mod tests;
