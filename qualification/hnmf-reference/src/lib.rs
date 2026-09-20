#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

pub const PPM: i64 = 1_000_000;
pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

pub const MAX_EVENT_SEMANTIC_KEYS: usize = 64;
pub const MAX_EVENT_SOURCES: usize = 32;
pub const MAX_CUE_KEYS: usize = 64;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_SUPPORT_EVENTS: usize = 64;
pub const MAX_TOPOLOGY_LABEL_BYTES: usize = 128;

pub type EventId = u64;
pub type EpisodeId = u64;
pub type NodeId = u64;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ModalityKind {
    Text,
    Image,
    Audio,
    Video,
    CodeAst,
    GuiState,
    ToolTrajectory,
    StructuredData,
    Sensor,
}

impl ModalityKind {
    pub const ALL: [Self; 9] = [
        Self::Text,
        Self::Image,
        Self::Audio,
        Self::Video,
        Self::CodeAst,
        Self::GuiState,
        Self::ToolTrajectory,
        Self::StructuredData,
        Self::Sensor,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Text => "text",
            Self::Image => "image",
            Self::Audio => "audio",
            Self::Video => "video",
            Self::CodeAst => "code_ast",
            Self::GuiState => "gui_state",
            Self::ToolTrajectory => "tool_trajectory",
            Self::StructuredData => "structured_data",
            Self::Sensor => "sensor",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum EngramPopulation {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

impl EngramPopulation {
    pub const ALL: [Self; 7] = [
        Self::SensoryTrace,
        Self::EpisodicBinding,
        Self::SemanticConcept,
        Self::ProceduralSkill,
        Self::PredictiveWorld,
        Self::UtilitySalience,
        Self::MetaMemory,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SensoryTrace => "sensory_trace",
            Self::EpisodicBinding => "episodic_binding",
            Self::SemanticConcept => "semantic_concept",
            Self::ProceduralSkill => "procedural_skill",
            Self::PredictiveWorld => "predictive_world",
            Self::UtilitySalience => "utility_salience",
            Self::MetaMemory => "meta_memory",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SynapseRelation {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

impl SynapseRelation {
    const fn is_negative(self) -> bool {
        matches!(self, Self::Inhibitory | Self::Contradicts)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivacyClass {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryEvent {
    pub id: EventId,
    pub episode_id: EpisodeId,
    pub modalities: BTreeSet<ModalityKind>,
    pub semantic_keys: BTreeSet<String>,
    pub source_sha256: BTreeSet<String>,
    pub privacy: PrivacyClass,
    pub valid_from_unix_ms: i64,
    pub valid_to_unix_ms: Option<i64>,
    pub utility_ppm: i32,
    pub risk_ppm: u32,
    pub tombstoned: bool,
}

impl MemoryEvent {
    pub fn validate(&self) -> Result<(), FabricError> {
        if self.id == 0 || self.episode_id == 0 {
            return Err(FabricError::Invalid(
                "event and episode ids must be non-zero",
            ));
        }
        if self.modalities.is_empty() || self.modalities.len() > ModalityKind::ALL.len() {
            return Err(FabricError::Invalid(
                "event modality set is empty or invalid",
            ));
        }
        validate_keys(
            &self.semantic_keys,
            MAX_EVENT_SEMANTIC_KEYS,
            "event semantic keys",
        )?;
        if self.source_sha256.is_empty() || self.source_sha256.len() > MAX_EVENT_SOURCES {
            return Err(FabricError::Invalid(
                "event source set is empty or exceeds its bound",
            ));
        }
        if self
            .source_sha256
            .iter()
            .any(|value| !is_lower_hex_64(value))
        {
            return Err(FabricError::Invalid(
                "event source digest is not lowercase SHA-256",
            ));
        }
        if self
            .valid_to_unix_ms
            .is_some_and(|end| end <= self.valid_from_unix_ms)
        {
            return Err(FabricError::Invalid(
                "event validity interval is not increasing",
            ));
        }
        if !(-PPM as i32..=PPM as i32).contains(&self.utility_ppm) {
            return Err(FabricError::Invalid(
                "event utility is outside the fixed-point range",
            ));
        }
        if u64::from(self.risk_ppm) > PPM as u64 {
            return Err(FabricError::Invalid(
                "event risk is outside the fixed-point range",
            ));
        }
        Ok(())
    }

    fn eligible(&self, now_unix_ms: i64) -> bool {
        !self.tombstoned
            && self.valid_from_unix_ms <= now_unix_ms
            && self.valid_to_unix_ms.is_none_or(|end| now_unix_ms < end)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramNode {
    pub id: NodeId,
    pub population: EngramPopulation,
    pub modalities: BTreeSet<ModalityKind>,
    pub cue_keys: BTreeSet<String>,
    pub support_events: BTreeSet<EventId>,
    pub threshold_ppm: i32,
    pub target_activity_ppm: u32,
    pub confidence_ppm: u32,
    pub retired: bool,
}

impl EngramNode {
    pub fn validate(&self) -> Result<(), FabricError> {
        if self.id == 0 {
            return Err(FabricError::Invalid("node id must be non-zero"));
        }
        if self.modalities.is_empty() || self.modalities.len() > ModalityKind::ALL.len() {
            return Err(FabricError::Invalid(
                "node modality set is empty or invalid",
            ));
        }
        validate_keys(&self.cue_keys, MAX_EVENT_SEMANTIC_KEYS, "node cue keys")?;
        if self.support_events.len() > MAX_SUPPORT_EVENTS
            || (!self.retired && self.support_events.is_empty())
        {
            return Err(FabricError::Invalid(
                "node support set is empty for an active node or exceeds its bound",
            ));
        }
        if !(-PPM as i32..=PPM as i32).contains(&self.threshold_ppm) {
            return Err(FabricError::Invalid(
                "node threshold is outside the fixed-point range",
            ));
        }
        if u64::from(self.target_activity_ppm) > PPM as u64
            || u64::from(self.confidence_ppm) > PPM as u64
        {
            return Err(FabricError::Invalid(
                "node activity or confidence is outside the fixed-point range",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Synapse {
    pub source: NodeId,
    pub target: NodeId,
    pub relation: SynapseRelation,
    pub weight_ppm: i32,
    pub eligibility_ppm: i32,
    pub support_events: BTreeSet<EventId>,
    pub retired: bool,
}

impl Synapse {
    pub fn validate(&self) -> Result<(), FabricError> {
        if self.source == 0 || self.target == 0 || self.source == self.target {
            return Err(FabricError::Invalid(
                "synapse endpoints must be distinct non-zero ids",
            ));
        }
        if !(-PPM as i32..=PPM as i32).contains(&self.weight_ppm)
            || !(-PPM as i32..=PPM as i32).contains(&self.eligibility_ppm)
        {
            return Err(FabricError::Invalid(
                "synapse weight or eligibility is outside range",
            ));
        }
        if self.support_events.len() > MAX_SUPPORT_EVENTS
            || (!self.retired && self.support_events.is_empty())
        {
            return Err(FabricError::Invalid(
                "synapse support set is empty for an active synapse or exceeds its bound",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FabricConfig {
    pub maximum_candidate_events: usize,
    pub maximum_nodes: usize,
    pub maximum_synapses: usize,
    pub maximum_active_nodes: usize,
    pub maximum_active_per_population: usize,
    pub maximum_recurrent_steps: u8,
    pub maximum_recall_events: usize,
    pub maximum_activation_paths: usize,
    pub leak_ppm: u32,
    pub lateral_inhibition_ppm: u32,
    pub trace_decay_ppm: u32,
    pub learning_rate_ppm: u32,
    pub homeostasis_rate_ppm: u32,
    pub maximum_weight_delta_ppm: i32,
    pub ood_abstain_ppm: u32,
    pub minimum_confidence_ppm: u32,
    pub contradiction_forces_abstention: bool,
}

impl Default for FabricConfig {
    fn default() -> Self {
        Self {
            maximum_candidate_events: 512,
            maximum_nodes: 4096,
            maximum_synapses: 32768,
            maximum_active_nodes: 4096,
            maximum_active_per_population: 64,
            maximum_recurrent_steps: 4,
            maximum_recall_events: 16,
            maximum_activation_paths: 32,
            leak_ppm: 350_000,
            lateral_inhibition_ppm: 80_000,
            trace_decay_ppm: 800_000,
            learning_rate_ppm: 100_000,
            homeostasis_rate_ppm: 20_000,
            maximum_weight_delta_ppm: 50_000,
            ood_abstain_ppm: 800_000,
            minimum_confidence_ppm: 250_000,
            contradiction_forces_abstention: true,
        }
    }
}

impl FabricConfig {
    pub fn validate(self) -> Result<(), FabricError> {
        if self.maximum_candidate_events == 0
            || self.maximum_candidate_events > 512
            || self.maximum_nodes == 0
            || self.maximum_nodes > 4096
            || self.maximum_synapses == 0
            || self.maximum_synapses > 32768
            || self.maximum_active_nodes == 0
            || self.maximum_active_nodes > self.maximum_nodes
            || self.maximum_active_per_population == 0
            || self.maximum_active_per_population > 64
            || self.maximum_recurrent_steps == 0
            || self.maximum_recurrent_steps > 4
            || self.maximum_recall_events == 0
            || self.maximum_recall_events > 16
            || self.maximum_activation_paths == 0
            || self.maximum_activation_paths > 32
        {
            return Err(FabricError::BoundExceeded("fabric structural bound"));
        }
        for value in [
            self.leak_ppm,
            self.lateral_inhibition_ppm,
            self.trace_decay_ppm,
            self.learning_rate_ppm,
            self.homeostasis_rate_ppm,
            self.ood_abstain_ppm,
            self.minimum_confidence_ppm,
        ] {
            if u64::from(value) > PPM as u64 {
                return Err(FabricError::Invalid(
                    "configuration fixed-point value exceeds one",
                ));
            }
        }
        if self.maximum_weight_delta_ppm <= 0 || i64::from(self.maximum_weight_delta_ppm) > PPM {
            return Err(FabricError::Invalid("maximum weight delta is invalid"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCue {
    pub modalities: BTreeSet<ModalityKind>,
    pub semantic_keys: BTreeSet<String>,
    pub seed_nodes: BTreeSet<NodeId>,
    pub now_unix_ms: i64,
}

impl MemoryCue {
    pub fn validate(&self) -> Result<(), FabricError> {
        if self.modalities.is_empty() || self.modalities.len() > ModalityKind::ALL.len() {
            return Err(FabricError::Invalid("cue modality set is empty or invalid"));
        }
        validate_keys(&self.semantic_keys, MAX_CUE_KEYS, "cue semantic keys")?;
        if self.seed_nodes.len() > MAX_CUE_SEEDS || self.seed_nodes.contains(&0) {
            return Err(FabricError::BoundExceeded("cue seed nodes"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActiveNode {
    pub node_id: NodeId,
    pub population: EngramPopulation,
    pub activation_ppm: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActivationPath {
    pub source: NodeId,
    pub target: NodeId,
    pub relation: SynapseRelation,
    pub contribution_ppm: i32,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Contradiction {
    pub left: NodeId,
    pub right: NodeId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallAbstainReason {
    NoCandidate,
    OutOfDistribution,
    LowConfidence,
    UnresolvedContradiction,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallPacket {
    pub snapshot_generation: u64,
    pub candidate_event_count: usize,
    pub selected_events: Vec<EventId>,
    pub active_nodes: Vec<ActiveNode>,
    pub activation_paths: Vec<ActivationPath>,
    pub contradictions: Vec<Contradiction>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub settling_steps: u8,
    pub abstain: Option<RecallAbstainReason>,
    pub contains_raw_source_payload: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OutcomeSignal {
    pub utility_delta_ppm: i32,
    pub prediction_error_ppm: u32,
    pub novelty_ppm: u32,
    pub risk_ppm: u32,
    pub ood_ppm: u32,
}

impl OutcomeSignal {
    pub fn validate(self) -> Result<(), FabricError> {
        if !(-PPM as i32..=PPM as i32).contains(&self.utility_delta_ppm) {
            return Err(FabricError::Invalid("utility delta is outside range"));
        }
        for value in [
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.risk_ppm,
            self.ood_ppm,
        ] {
            if u64::from(value) > PPM as u64 {
                return Err(FabricError::Invalid("outcome component is outside range"));
            }
        }
        Ok(())
    }

    pub fn modulator_ppm(self) -> Result<i32, FabricError> {
        self.validate()?;
        let positive = i64::from(self.utility_delta_ppm)
            + i64::from(self.prediction_error_ppm) / 2
            + i64::from(self.novelty_ppm) / 4;
        let negative = i64::from(self.risk_ppm) + i64::from(self.ood_ppm);
        Ok(clamp_i64(positive - negative, -PPM, PPM) as i32)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WeightProposal {
    pub source: NodeId,
    pub target: NodeId,
    pub relation: SynapseRelation,
    pub old_weight_ppm: i32,
    pub new_weight_ppm: i32,
    pub delta_ppm: i32,
    pub new_eligibility_ppm: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ThresholdProposal {
    pub node_id: NodeId,
    pub old_threshold_ppm: i32,
    pub new_threshold_ppm: i32,
    pub delta_ppm: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityBatch {
    pub predecessor_generation: u64,
    pub next_generation: u64,
    pub modulator_ppm: i32,
    pub weight_proposals: Vec<WeightProposal>,
    pub threshold_proposals: Vec<ThresholdProposal>,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayCandidate {
    pub event_id: EventId,
    pub source_bucket: u16,
    pub expected_utility_gain_ppm: u32,
    pub prediction_error_ppm: u32,
    pub novelty_ppm: u32,
    pub rarity_ppm: u32,
    pub forgetting_risk_ppm: u32,
    pub coverage_need_ppm: u32,
    pub privacy_allowed: bool,
}

impl ReplayCandidate {
    fn score(&self) -> Result<u64, FabricError> {
        for value in [
            self.expected_utility_gain_ppm,
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.rarity_ppm,
            self.forgetting_risk_ppm,
            self.coverage_need_ppm,
        ] {
            if u64::from(value) > PPM as u64 {
                return Err(FabricError::Invalid("replay score component exceeds one"));
            }
        }
        let values = [
            self.expected_utility_gain_ppm,
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.rarity_ppm,
            self.forgetting_risk_ppm,
            self.coverage_need_ppm,
        ];
        Ok(values.into_iter().map(u64::from).sum())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplaySelectionReceipt {
    pub selected_event_ids: Vec<EventId>,
    pub source_bucket_counts: BTreeMap<u16, usize>,
    pub candidate_count: usize,
    pub maximum_per_source_bucket: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyOperation {
    AddNode {
        label: String,
        population: EngramPopulation,
    },
    SplitNode {
        node_id: NodeId,
        labels: [String; 2],
    },
    MergeNodes {
        left: NodeId,
        right: NodeId,
        label: String,
    },
    RetireNode {
        node_id: NodeId,
        reason: String,
    },
    Rewire {
        source: NodeId,
        old_target: NodeId,
        new_target: NodeId,
        relation: SynapseRelation,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposal {
    pub predecessor_generation: u64,
    pub next_generation: u64,
    pub operation: TopologyOperation,
    pub capability_typed: bool,
    pub sandbox_only: bool,
    pub operator_accepted: bool,
    pub production_activation_allowed: bool,
}

impl TopologyProposal {
    pub fn validate(&self) -> Result<(), FabricError> {
        if self.predecessor_generation == 0
            || self.next_generation != self.predecessor_generation + 1
            || !self.capability_typed
            || !self.sandbox_only
            || self.operator_accepted
            || self.production_activation_allowed
        {
            return Err(FabricError::AuthorityBoundary);
        }
        match &self.operation {
            TopologyOperation::AddNode { label, .. }
            | TopologyOperation::MergeNodes { label, .. } => validate_label(label)?,
            TopologyOperation::SplitNode { node_id, labels } => {
                if *node_id == 0 {
                    return Err(FabricError::Invalid("split node id is zero"));
                }
                validate_label(&labels[0])?;
                validate_label(&labels[1])?;
                if labels[0] == labels[1] {
                    return Err(FabricError::Invalid("split labels must be distinct"));
                }
            }
            TopologyOperation::RetireNode { node_id, reason } => {
                if *node_id == 0 {
                    return Err(FabricError::Invalid("retire node id is zero"));
                }
                validate_label(reason)?;
            }
            TopologyOperation::Rewire {
                source,
                old_target,
                new_target,
                ..
            } => {
                if *source == 0
                    || *old_target == 0
                    || *new_target == 0
                    || source == old_target
                    || source == new_target
                    || old_target == new_target
                {
                    return Err(FabricError::Invalid("rewire endpoints are invalid"));
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ForgetBatch {
    pub event_id: EventId,
    pub predecessor_generation: u64,
    pub next_generation: u64,
    pub affected_nodes: Vec<NodeId>,
    pub affected_synapses: Vec<(NodeId, NodeId, SynapseRelation)>,
    pub projection_rebuild_required: bool,
    pub artifact_revocation_required: bool,
    pub production_activation_allowed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FabricError {
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    AuthorityBoundary,
    ArithmeticOverflow,
}

impl fmt::Display for FabricError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid HNMF input: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "HNMF bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "HNMF conflict: {message}"),
            Self::Missing(name) => write!(formatter, "HNMF object is missing: {name}"),
            Self::AuthorityBoundary => write!(formatter, "HNMF authority boundary crossed"),
            Self::ArithmeticOverflow => write!(formatter, "HNMF fixed-point arithmetic overflow"),
        }
    }
}

impl std::error::Error for FabricError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HnmfFabric {
    generation: u64,
    config: FabricConfig,
    events: BTreeMap<EventId, MemoryEvent>,
    nodes: BTreeMap<NodeId, EngramNode>,
    synapses: BTreeMap<(NodeId, NodeId, SynapseRelation), Synapse>,
}

impl HnmfFabric {
    pub fn new(generation: u64, config: FabricConfig) -> Result<Self, FabricError> {
        if generation == 0 {
            return Err(FabricError::Invalid("snapshot generation must be non-zero"));
        }
        config.validate()?;
        Ok(Self {
            generation,
            config,
            events: BTreeMap::new(),
            nodes: BTreeMap::new(),
            synapses: BTreeMap::new(),
        })
    }

    pub const fn generation(&self) -> u64 {
        self.generation
    }

    pub const fn config(&self) -> FabricConfig {
        self.config
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

    pub fn insert_event(&mut self, event: MemoryEvent) -> Result<(), FabricError> {
        event.validate()?;
        if self.events.len() >= self.config.maximum_candidate_events
            && !self.events.contains_key(&event.id)
        {
            return Err(FabricError::BoundExceeded("events"));
        }
        insert_exact(&mut self.events, event.id, event, "event identity")
    }

    pub fn insert_node(&mut self, node: EngramNode) -> Result<(), FabricError> {
        node.validate()?;
        if self.nodes.len() >= self.config.maximum_nodes && !self.nodes.contains_key(&node.id) {
            return Err(FabricError::BoundExceeded("nodes"));
        }
        for event_id in &node.support_events {
            if !self.events.contains_key(event_id) {
                return Err(FabricError::Missing("node support event"));
            }
        }
        insert_exact(&mut self.nodes, node.id, node, "node identity")
    }

    pub fn insert_synapse(&mut self, synapse: Synapse) -> Result<(), FabricError> {
        synapse.validate()?;
        if self.synapses.len() >= self.config.maximum_synapses
            && !self
                .synapses
                .contains_key(&(synapse.source, synapse.target, synapse.relation))
        {
            return Err(FabricError::BoundExceeded("synapses"));
        }
        if !self.nodes.contains_key(&synapse.source) || !self.nodes.contains_key(&synapse.target) {
            return Err(FabricError::Missing("synapse endpoint"));
        }
        for event_id in &synapse.support_events {
            if !self.events.contains_key(event_id) {
                return Err(FabricError::Missing("synapse support event"));
            }
        }
        let key = (synapse.source, synapse.target, synapse.relation);
        insert_exact(&mut self.synapses, key, synapse, "synapse identity")
    }

    pub fn validate(&self) -> Result<(), FabricError> {
        self.config.validate()?;
        if self.generation == 0
            || self.events.len() > self.config.maximum_candidate_events
            || self.nodes.len() > self.config.maximum_nodes
            || self.synapses.len() > self.config.maximum_synapses
        {
            return Err(FabricError::BoundExceeded("snapshot"));
        }
        for event in self.events.values() {
            event.validate()?;
        }
        for node in self.nodes.values() {
            node.validate()?;
            if node
                .support_events
                .iter()
                .any(|id| !self.events.contains_key(id))
            {
                return Err(FabricError::Missing("node support event"));
            }
        }
        for synapse in self.synapses.values() {
            synapse.validate()?;
            if !self.nodes.contains_key(&synapse.source)
                || !self.nodes.contains_key(&synapse.target)
            {
                return Err(FabricError::Missing("synapse endpoint"));
            }
            if synapse
                .support_events
                .iter()
                .any(|id| !self.events.contains_key(id))
            {
                return Err(FabricError::Missing("synapse support event"));
            }
        }
        Ok(())
    }

    pub fn recall(&self, cue: &MemoryCue) -> Result<RecallPacket, FabricError> {
        self.validate()?;
        cue.validate()?;

        let mut candidate_events = self
            .events
            .values()
            .filter(|event| event.eligible(cue.now_unix_ms))
            .filter_map(|event| {
                let semantic_overlap = event.semantic_keys.intersection(&cue.semantic_keys).count();
                let modality_overlap = event.modalities.intersection(&cue.modalities).count();
                let seeded = self.nodes.values().any(|node| {
                    cue.seed_nodes.contains(&node.id) && node.support_events.contains(&event.id)
                });
                if semantic_overlap == 0 && modality_overlap == 0 && !seeded {
                    return None;
                }
                let cross_modal = semantic_overlap > 0 && modality_overlap == 0;
                let score = semantic_overlap as i64 * 1_000_000
                    + modality_overlap as i64 * 250_000
                    + if cross_modal { 500_000 } else { 0 }
                    + if seeded { 2_000_000 } else { 0 }
                    + i64::from(event.utility_ppm).max(0)
                    - i64::from(event.risk_ppm);
                Some((event.id, score.max(0) as u64))
            })
            .collect::<Vec<_>>();
        candidate_events
            .sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        candidate_events.truncate(self.config.maximum_candidate_events);
        let candidate_event_ids = candidate_events
            .iter()
            .map(|(event_id, _)| *event_id)
            .collect::<BTreeSet<_>>();

        if candidate_event_ids.is_empty() {
            return Ok(empty_packet(
                self.generation,
                RecallAbstainReason::NoCandidate,
                self.config.maximum_recurrent_steps,
            ));
        }

        let candidate_nodes = self
            .nodes
            .values()
            .filter(|node| !node.retired)
            .filter(|node| {
                cue.seed_nodes.contains(&node.id)
                    || node
                        .support_events
                        .iter()
                        .any(|event_id| candidate_event_ids.contains(event_id))
            })
            .map(|node| node.id)
            .collect::<BTreeSet<_>>();

        let mut direct_drive = BTreeMap::new();
        for node_id in &candidate_nodes {
            let node = self
                .nodes
                .get(node_id)
                .ok_or(FabricError::Missing("candidate node"))?;
            let semantic_overlap = node.cue_keys.intersection(&cue.semantic_keys).count() as i64;
            let modality_overlap = node.modalities.intersection(&cue.modalities).count() as i64;
            let seeded = if cue.seed_nodes.contains(node_id) {
                1_i64
            } else {
                0
            };
            let cross_modal = if semantic_overlap > 0 && modality_overlap == 0 {
                1_i64
            } else {
                0
            };
            let drive = semantic_overlap
                .checked_mul(300_000)
                .and_then(|value| value.checked_add(modality_overlap * 100_000))
                .and_then(|value| value.checked_add(cross_modal * 200_000))
                .and_then(|value| value.checked_add(seeded * 800_000))
                .ok_or(FabricError::ArithmeticOverflow)?;
            direct_drive.insert(*node_id, clamp_i64(drive, 0, PPM));
        }

        let mut activation = candidate_nodes
            .iter()
            .map(|node_id| (*node_id, 0_i64))
            .collect::<BTreeMap<_, _>>();
        let mut last_paths = Vec::new();

        for _ in 0..self.config.maximum_recurrent_steps {
            let mut raw = BTreeMap::new();
            let mut paths = Vec::new();
            for node_id in &candidate_nodes {
                let node = self
                    .nodes
                    .get(node_id)
                    .ok_or(FabricError::Missing("candidate node"))?;
                let previous = activation.get(node_id).copied().unwrap_or(0);
                let leak = mul_ppm(previous, i64::from(self.config.leak_ppm))?;
                let mut value = direct_drive.get(node_id).copied().unwrap_or(0) + leak
                    - i64::from(node.threshold_ppm);
                for synapse in self.synapses.values().filter(|synapse| {
                    !synapse.retired
                        && synapse.target == *node_id
                        && candidate_nodes.contains(&synapse.source)
                }) {
                    let source_activation = activation.get(&synapse.source).copied().unwrap_or(0);
                    if source_activation <= 0 {
                        continue;
                    }
                    let magnitude =
                        mul_ppm(source_activation, i64::from(synapse.weight_ppm).abs())?;
                    let contribution = if synapse.relation.is_negative() {
                        -magnitude
                    } else if synapse.weight_ppm < 0 {
                        -magnitude
                    } else {
                        magnitude
                    };
                    value = value
                        .checked_add(contribution)
                        .ok_or(FabricError::ArithmeticOverflow)?;
                    if contribution != 0 {
                        paths.push(ActivationPath {
                            source: synapse.source,
                            target: synapse.target,
                            relation: synapse.relation,
                            contribution_ppm: clamp_i64(contribution, -PPM, PPM) as i32,
                        });
                    }
                }
                raw.insert(*node_id, clamp_i64(value, 0, PPM));
            }
            activation = sparse_select(self, &raw)?;
            paths.sort_by(|left, right| {
                right
                    .contribution_ppm
                    .unsigned_abs()
                    .cmp(&left.contribution_ppm.unsigned_abs())
                    .then_with(|| left.source.cmp(&right.source))
                    .then_with(|| left.target.cmp(&right.target))
                    .then_with(|| left.relation.cmp(&right.relation))
            });
            paths.truncate(self.config.maximum_activation_paths);
            last_paths = paths;
        }

        let mut active_nodes = activation
            .iter()
            .filter(|(_, value)| **value > 0)
            .map(|(node_id, value)| {
                let node = self.nodes.get(node_id).expect("candidate node exists");
                ActiveNode {
                    node_id: *node_id,
                    population: node.population,
                    activation_ppm: *value as i32,
                }
            })
            .collect::<Vec<_>>();
        active_nodes.sort_by(|left, right| {
            right
                .activation_ppm
                .cmp(&left.activation_ppm)
                .then_with(|| left.node_id.cmp(&right.node_id))
        });
        active_nodes.truncate(self.config.maximum_active_nodes);

        let active_ids = active_nodes
            .iter()
            .map(|active| active.node_id)
            .collect::<BTreeSet<_>>();
        let mut contradictions = self
            .synapses
            .values()
            .filter(|synapse| {
                !synapse.retired
                    && synapse.relation == SynapseRelation::Contradicts
                    && active_ids.contains(&synapse.source)
                    && active_ids.contains(&synapse.target)
            })
            .map(|synapse| Contradiction {
                left: synapse.source.min(synapse.target),
                right: synapse.source.max(synapse.target),
            })
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        contradictions.sort_by_key(|item| (item.left, item.right));

        let mut event_strength = BTreeMap::<EventId, i64>::new();
        for active in &active_nodes {
            let node = self
                .nodes
                .get(&active.node_id)
                .ok_or(FabricError::Missing("active node"))?;
            for event_id in &node.support_events {
                if candidate_event_ids.contains(event_id)
                    && self
                        .events
                        .get(event_id)
                        .is_some_and(|event| event.eligible(cue.now_unix_ms))
                {
                    event_strength
                        .entry(*event_id)
                        .and_modify(|value| *value = (*value).max(i64::from(active.activation_ppm)))
                        .or_insert(i64::from(active.activation_ppm));
                }
            }
        }
        let mut selected_events = event_strength.into_iter().collect::<Vec<_>>();
        selected_events
            .sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        selected_events.truncate(self.config.maximum_recall_events);
        let selected_events = selected_events
            .into_iter()
            .map(|(event_id, _)| event_id)
            .collect::<Vec<_>>();

        let covered_keys = selected_events
            .iter()
            .filter_map(|event_id| self.events.get(event_id))
            .flat_map(|event| event.semantic_keys.iter())
            .filter(|key| cue.semantic_keys.contains(*key))
            .cloned()
            .collect::<BTreeSet<_>>();
        let coverage_ppm = if cue.semantic_keys.is_empty() {
            0
        } else {
            ratio_ppm(covered_keys.len(), cue.semantic_keys.len())
        };
        let ood_ppm = (PPM as u32).saturating_sub(coverage_ppm);
        let confidence_ppm = if active_nodes.is_empty() {
            0
        } else {
            let total = active_nodes.iter().try_fold(0_u64, |sum, active| {
                let node = self
                    .nodes
                    .get(&active.node_id)
                    .ok_or(FabricError::Missing("active node"))?;
                let calibrated = u64::from(active.activation_ppm.unsigned_abs())
                    .min(u64::from(node.confidence_ppm));
                sum.checked_add(calibrated)
                    .ok_or(FabricError::ArithmeticOverflow)
            })?;
            u32::try_from(total / active_nodes.len() as u64).unwrap_or(PPM as u32)
        };

        let abstain = if selected_events.is_empty() {
            Some(RecallAbstainReason::NoCandidate)
        } else if self.config.contradiction_forces_abstention && !contradictions.is_empty() {
            Some(RecallAbstainReason::UnresolvedContradiction)
        } else if ood_ppm >= self.config.ood_abstain_ppm {
            Some(RecallAbstainReason::OutOfDistribution)
        } else if confidence_ppm < self.config.minimum_confidence_ppm {
            Some(RecallAbstainReason::LowConfidence)
        } else {
            None
        };

        Ok(RecallPacket {
            snapshot_generation: self.generation,
            candidate_event_count: candidate_event_ids.len(),
            selected_events,
            active_nodes,
            activation_paths: last_paths,
            contradictions,
            coverage_ppm,
            confidence_ppm,
            ood_ppm,
            settling_steps: self.config.maximum_recurrent_steps,
            abstain,
            contains_raw_source_payload: false,
        })
    }

    pub fn propose_plasticity(
        &self,
        packet: &RecallPacket,
        signal: OutcomeSignal,
    ) -> Result<PlasticityBatch, FabricError> {
        self.validate()?;
        if packet.snapshot_generation != self.generation || packet.contains_raw_source_payload {
            return Err(FabricError::Conflict(
                "recall packet does not match current snapshot",
            ));
        }
        let modulator_ppm = signal.modulator_ppm()?;
        let active = packet
            .active_nodes
            .iter()
            .map(|node| (node.node_id, i64::from(node.activation_ppm)))
            .collect::<BTreeMap<_, _>>();
        let mut weight_proposals = Vec::new();
        for synapse in self.synapses.values().filter(|synapse| !synapse.retired) {
            let pre = active.get(&synapse.source).copied().unwrap_or(0).max(0);
            let post = active.get(&synapse.target).copied().unwrap_or(0).max(0);
            let coactivation = if pre > 0 && post > 0 {
                mul_ppm(pre, post)?
            } else {
                0
            };
            let decayed = mul_ppm(
                i64::from(synapse.eligibility_ppm),
                i64::from(self.config.trace_decay_ppm),
            )?;
            let eligibility = clamp_i64(decayed + coactivation, -PPM, PPM);
            let modulated = mul_ppm(eligibility, i64::from(modulator_ppm))?;
            let mut delta = mul_ppm(modulated, i64::from(self.config.learning_rate_ppm))?;
            if synapse.relation.is_negative() {
                delta = -delta;
            }
            delta = clamp_i64(
                delta,
                -i64::from(self.config.maximum_weight_delta_ppm),
                i64::from(self.config.maximum_weight_delta_ppm),
            );
            let new_weight = clamp_i64(i64::from(synapse.weight_ppm) + delta, -PPM, PPM);
            if eligibility != i64::from(synapse.eligibility_ppm) || delta != 0 {
                weight_proposals.push(WeightProposal {
                    source: synapse.source,
                    target: synapse.target,
                    relation: synapse.relation,
                    old_weight_ppm: synapse.weight_ppm,
                    new_weight_ppm: new_weight as i32,
                    delta_ppm: delta as i32,
                    new_eligibility_ppm: eligibility as i32,
                });
            }
        }
        weight_proposals
            .sort_by_key(|proposal| (proposal.source, proposal.target, proposal.relation));

        let mut threshold_proposals = Vec::new();
        for node in self.nodes.values().filter(|node| !node.retired) {
            let observed = if active.get(&node.id).copied().unwrap_or(0) > 0 {
                PPM
            } else {
                0
            };
            let difference = observed - i64::from(node.target_activity_ppm);
            let delta = mul_ppm(difference, i64::from(self.config.homeostasis_rate_ppm))?;
            let new_threshold = clamp_i64(i64::from(node.threshold_ppm) + delta, -PPM, PPM);
            threshold_proposals.push(ThresholdProposal {
                node_id: node.id,
                old_threshold_ppm: node.threshold_ppm,
                new_threshold_ppm: new_threshold as i32,
                delta_ppm: delta as i32,
            });
        }
        threshold_proposals.sort_by_key(|proposal| proposal.node_id);

        Ok(PlasticityBatch {
            predecessor_generation: self.generation,
            next_generation: self.generation + 1,
            modulator_ppm,
            weight_proposals,
            threshold_proposals,
            current_snapshot_immutable: true,
            production_activation_allowed: false,
        })
    }

    pub fn apply_plasticity(&self, batch: &PlasticityBatch) -> Result<Self, FabricError> {
        if batch.predecessor_generation != self.generation
            || batch.next_generation != self.generation + 1
        {
            return Err(FabricError::Conflict("plasticity generation mismatch"));
        }
        if !batch.current_snapshot_immutable || batch.production_activation_allowed {
            return Err(FabricError::AuthorityBoundary);
        }
        let mut next = self.clone();
        for proposal in &batch.weight_proposals {
            let synapse = next
                .synapses
                .get_mut(&(proposal.source, proposal.target, proposal.relation))
                .ok_or(FabricError::Missing("plasticity synapse"))?;
            if synapse.weight_ppm != proposal.old_weight_ppm {
                return Err(FabricError::Conflict("plasticity old weight mismatch"));
            }
            if proposal.new_weight_ppm - proposal.old_weight_ppm != proposal.delta_ppm
                || i64::from(proposal.delta_ppm).abs()
                    > i64::from(self.config.maximum_weight_delta_ppm)
            {
                return Err(FabricError::Invalid("plasticity delta is invalid"));
            }
            synapse.weight_ppm = proposal.new_weight_ppm;
            synapse.eligibility_ppm = proposal.new_eligibility_ppm;
        }
        for proposal in &batch.threshold_proposals {
            let node = next
                .nodes
                .get_mut(&proposal.node_id)
                .ok_or(FabricError::Missing("plasticity node"))?;
            if node.threshold_ppm != proposal.old_threshold_ppm
                || proposal.new_threshold_ppm - proposal.old_threshold_ppm != proposal.delta_ppm
            {
                return Err(FabricError::Conflict("plasticity threshold mismatch"));
            }
            node.threshold_ppm = proposal.new_threshold_ppm;
        }
        next.generation = batch.next_generation;
        next.validate()?;
        Ok(next)
    }

    pub fn propose_forget(&self, event_id: EventId) -> Result<ForgetBatch, FabricError> {
        let event = self
            .events
            .get(&event_id)
            .ok_or(FabricError::Missing("forget event"))?;
        if event.tombstoned {
            return Err(FabricError::Conflict("event is already tombstoned"));
        }
        let affected_nodes = self
            .nodes
            .values()
            .filter(|node| node.support_events.contains(&event_id))
            .map(|node| node.id)
            .collect::<Vec<_>>();
        let affected_synapses = self
            .synapses
            .values()
            .filter(|synapse| synapse.support_events.contains(&event_id))
            .map(|synapse| (synapse.source, synapse.target, synapse.relation))
            .collect::<Vec<_>>();
        Ok(ForgetBatch {
            event_id,
            predecessor_generation: self.generation,
            next_generation: self.generation + 1,
            affected_nodes,
            affected_synapses,
            projection_rebuild_required: true,
            artifact_revocation_required: true,
            production_activation_allowed: false,
        })
    }

    pub fn apply_forget(&self, batch: &ForgetBatch) -> Result<Self, FabricError> {
        if batch.predecessor_generation != self.generation
            || batch.next_generation != self.generation + 1
        {
            return Err(FabricError::Conflict("forget generation mismatch"));
        }
        if !batch.projection_rebuild_required
            || !batch.artifact_revocation_required
            || batch.production_activation_allowed
        {
            return Err(FabricError::AuthorityBoundary);
        }
        let mut next = self.clone();
        let event = next
            .events
            .get_mut(&batch.event_id)
            .ok_or(FabricError::Missing("forget event"))?;
        if event.tombstoned {
            return Err(FabricError::Conflict("event is already tombstoned"));
        }
        event.tombstoned = true;
        for node in next.nodes.values_mut() {
            node.support_events.remove(&batch.event_id);
            if node.support_events.is_empty() {
                node.retired = true;
            }
        }
        for synapse in next.synapses.values_mut() {
            synapse.support_events.remove(&batch.event_id);
            if synapse.support_events.is_empty() {
                synapse.retired = true;
            }
        }
        next.generation = batch.next_generation;
        next.validate()?;
        Ok(next)
    }
}

pub fn select_replay(
    candidates: &[ReplayCandidate],
    maximum_selected: usize,
    maximum_per_source_bucket: usize,
) -> Result<ReplaySelectionReceipt, FabricError> {
    if candidates.len() > 4096
        || maximum_selected == 0
        || maximum_selected > 256
        || maximum_per_source_bucket == 0
        || maximum_per_source_bucket > maximum_selected
    {
        return Err(FabricError::BoundExceeded("replay selection"));
    }
    let mut scored = candidates
        .iter()
        .filter(|candidate| candidate.privacy_allowed)
        .map(|candidate| Ok((candidate, candidate.score()?)))
        .collect::<Result<Vec<_>, FabricError>>()?;
    scored.sort_by(|left, right| {
        right
            .1
            .cmp(&left.1)
            .then_with(|| left.0.source_bucket.cmp(&right.0.source_bucket))
            .then_with(|| left.0.event_id.cmp(&right.0.event_id))
    });
    let mut selected_event_ids = Vec::new();
    let mut source_bucket_counts = BTreeMap::<u16, usize>::new();
    for (candidate, _) in scored {
        if selected_event_ids.len() >= maximum_selected {
            break;
        }
        let count = source_bucket_counts
            .entry(candidate.source_bucket)
            .or_default();
        if *count >= maximum_per_source_bucket {
            continue;
        }
        *count += 1;
        selected_event_ids.push(candidate.event_id);
    }
    Ok(ReplaySelectionReceipt {
        selected_event_ids,
        source_bucket_counts,
        candidate_count: candidates.len(),
        maximum_per_source_bucket,
    })
}

fn sparse_select(
    fabric: &HnmfFabric,
    raw: &BTreeMap<NodeId, i64>,
) -> Result<BTreeMap<NodeId, i64>, FabricError> {
    let mut selected = BTreeMap::new();
    for population in EngramPopulation::ALL {
        let mut group = raw
            .iter()
            .filter_map(|(node_id, value)| {
                let node = fabric.nodes.get(node_id)?;
                (node.population == population && *value > 0).then_some((*node_id, *value))
            })
            .collect::<Vec<_>>();
        group.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        group.truncate(fabric.config.maximum_active_per_population);
        for (rank, (node_id, value)) in group.into_iter().enumerate() {
            let inhibition = i64::from(fabric.config.lateral_inhibition_ppm)
                .checked_mul(rank as i64)
                .ok_or(FabricError::ArithmeticOverflow)?;
            selected.insert(node_id, clamp_i64(value - inhibition, 0, PPM));
        }
    }
    let mut globally_ranked = selected.into_iter().collect::<Vec<_>>();
    globally_ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    globally_ranked.truncate(fabric.config.maximum_active_nodes);
    let active = globally_ranked.into_iter().collect::<BTreeMap<_, _>>();
    Ok(raw
        .keys()
        .map(|node_id| (*node_id, active.get(node_id).copied().unwrap_or(0)))
        .collect())
}

fn empty_packet(generation: u64, reason: RecallAbstainReason, settling_steps: u8) -> RecallPacket {
    RecallPacket {
        snapshot_generation: generation,
        candidate_event_count: 0,
        selected_events: Vec::new(),
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 0,
        confidence_ppm: 0,
        ood_ppm: PPM as u32,
        settling_steps,
        abstain: Some(reason),
        contains_raw_source_payload: false,
    }
}

fn insert_exact<K: Ord + Clone, V: Eq>(
    map: &mut BTreeMap<K, V>,
    key: K,
    value: V,
    conflict: &'static str,
) -> Result<(), FabricError> {
    if let Some(existing) = map.get(&key) {
        if existing == &value {
            return Ok(());
        }
        return Err(FabricError::Conflict(conflict));
    }
    map.insert(key, value);
    Ok(())
}

fn validate_keys(
    keys: &BTreeSet<String>,
    maximum: usize,
    name: &'static str,
) -> Result<(), FabricError> {
    if keys.is_empty() || keys.len() > maximum {
        return Err(FabricError::BoundExceeded(name));
    }
    for key in keys {
        if key.trim().is_empty()
            || key.len() > 128
            || key.chars().any(char::is_control)
            || key.to_lowercase() != key.as_str()
        {
            return Err(FabricError::Invalid("semantic key is not canonical"));
        }
    }
    Ok(())
}

fn validate_label(value: &str) -> Result<(), FabricError> {
    if value.trim().is_empty()
        || value.len() > MAX_TOPOLOGY_LABEL_BYTES
        || value.chars().any(char::is_control)
    {
        return Err(FabricError::Invalid("topology label is invalid"));
    }
    Ok(())
}

fn is_lower_hex_64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn mul_ppm(left: i64, right: i64) -> Result<i64, FabricError> {
    left.checked_mul(right)
        .ok_or(FabricError::ArithmeticOverflow)
        .map(|product| product / PPM)
}

const fn clamp_i64(value: i64, minimum: i64, maximum: i64) -> i64 {
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
    let value = numerator
        .saturating_mul(PPM as usize)
        .checked_div(denominator)
        .unwrap_or(0)
        .min(PPM as usize);
    value as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set<T: Ord>(values: impl IntoIterator<Item = T>) -> BTreeSet<T> {
        values.into_iter().collect()
    }

    fn digest(character: char) -> String {
        std::iter::repeat_n(character, 64).collect()
    }

    fn event(
        id: EventId,
        episode_id: EpisodeId,
        modalities: &[ModalityKind],
        keys: &[&str],
    ) -> MemoryEvent {
        MemoryEvent {
            id,
            episode_id,
            modalities: set(modalities.iter().copied()),
            semantic_keys: set(keys.iter().map(|value| (*value).to_string())),
            source_sha256: set([digest(char::from_digit(id as u32 % 6 + 10, 16).unwrap())]),
            privacy: PrivacyClass::AgentPrivate,
            valid_from_unix_ms: 1,
            valid_to_unix_ms: None,
            utility_ppm: 100_000,
            risk_ppm: 10_000,
            tombstoned: false,
        }
    }

    fn node(
        id: NodeId,
        population: EngramPopulation,
        modalities: &[ModalityKind],
        keys: &[&str],
        support_events: &[EventId],
        threshold_ppm: i32,
    ) -> EngramNode {
        EngramNode {
            id,
            population,
            modalities: set(modalities.iter().copied()),
            cue_keys: set(keys.iter().map(|value| (*value).to_string())),
            support_events: set(support_events.iter().copied()),
            threshold_ppm,
            target_activity_ppm: 100_000,
            confidence_ppm: 900_000,
            retired: false,
        }
    }

    fn synapse(
        source: NodeId,
        target: NodeId,
        relation: SynapseRelation,
        weight_ppm: i32,
        support_events: &[EventId],
    ) -> Synapse {
        Synapse {
            source,
            target,
            relation,
            weight_ppm,
            eligibility_ppm: 0,
            support_events: set(support_events.iter().copied()),
            retired: false,
        }
    }

    fn cue(modalities: &[ModalityKind], keys: &[&str], seeds: &[NodeId]) -> MemoryCue {
        MemoryCue {
            modalities: set(modalities.iter().copied()),
            semantic_keys: set(keys.iter().map(|value| (*value).to_string())),
            seed_nodes: set(seeds.iter().copied()),
            now_unix_ms: 10,
        }
    }

    fn cross_modal_fabric() -> HnmfFabric {
        let mut fabric = HnmfFabric::new(7, FabricConfig::default()).unwrap();
        fabric
            .insert_event(event(
                1,
                1,
                &[ModalityKind::Image, ModalityKind::Text],
                &["door", "red"],
            ))
            .unwrap();
        fabric
            .insert_node(node(
                1,
                EngramPopulation::SensoryTrace,
                &[ModalityKind::Image],
                &["door"],
                &[1],
                50_000,
            ))
            .unwrap();
        fabric
            .insert_node(node(
                2,
                EngramPopulation::EpisodicBinding,
                &[ModalityKind::Text, ModalityKind::Image],
                &["door"],
                &[1],
                100_000,
            ))
            .unwrap();
        fabric
            .insert_node(node(
                3,
                EngramPopulation::SemanticConcept,
                &[ModalityKind::Text],
                &["door", "red"],
                &[1],
                120_000,
            ))
            .unwrap();
        fabric
            .insert_synapse(synapse(1, 2, SynapseRelation::Associative, 900_000, &[1]))
            .unwrap();
        fabric
            .insert_synapse(synapse(2, 3, SynapseRelation::Supports, 800_000, &[1]))
            .unwrap();
        fabric
    }

    #[test]
    fn exposes_all_modalities_and_populations() {
        assert_eq!(ModalityKind::ALL.len(), 9);
        assert_eq!(EngramPopulation::ALL.len(), 7);
        assert_eq!(ModalityKind::ToolTrajectory.as_str(), "tool_trajectory");
        assert_eq!(EngramPopulation::MetaMemory.as_str(), "meta_memory");
    }

    #[test]
    fn cross_modal_pattern_completion_recalls_episode() {
        let fabric = cross_modal_fabric();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Audio], &["door"], &[1]))
            .unwrap();
        assert_eq!(packet.abstain, None);
        assert_eq!(packet.selected_events, vec![1]);
        assert!(packet.active_nodes.iter().any(|node| node.node_id == 2));
        assert!(packet.active_nodes.iter().any(|node| node.node_id == 3));
        assert!(!packet.contains_raw_source_payload);
    }

    #[test]
    fn sparse_competition_is_bounded() {
        let mut config = FabricConfig::default();
        config.maximum_active_per_population = 1;
        let mut fabric = HnmfFabric::new(1, config).unwrap();
        fabric
            .insert_event(event(1, 1, &[ModalityKind::Text], &["alpha"]))
            .unwrap();
        fabric
            .insert_node(node(
                1,
                EngramPopulation::SemanticConcept,
                &[ModalityKind::Text],
                &["alpha"],
                &[1],
                10_000,
            ))
            .unwrap();
        fabric
            .insert_node(node(
                2,
                EngramPopulation::SemanticConcept,
                &[ModalityKind::Text],
                &["alpha"],
                &[1],
                20_000,
            ))
            .unwrap();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Text], &["alpha"], &[]))
            .unwrap();
        let semantic_count = packet
            .active_nodes
            .iter()
            .filter(|node| node.population == EngramPopulation::SemanticConcept)
            .count();
        assert_eq!(semantic_count, 1);
        assert_eq!(packet.active_nodes[0].node_id, 1);
    }

    #[test]
    fn contradiction_forces_abstention() {
        let mut fabric = HnmfFabric::new(2, FabricConfig::default()).unwrap();
        fabric
            .insert_event(event(1, 1, &[ModalityKind::Text], &["status"]))
            .unwrap();
        fabric
            .insert_node(node(
                1,
                EngramPopulation::SemanticConcept,
                &[ModalityKind::Text],
                &["status"],
                &[1],
                10_000,
            ))
            .unwrap();
        fabric
            .insert_node(node(
                2,
                EngramPopulation::EpisodicBinding,
                &[ModalityKind::Text],
                &["status"],
                &[1],
                10_000,
            ))
            .unwrap();
        fabric
            .insert_synapse(synapse(1, 2, SynapseRelation::Contradicts, 1, &[1]))
            .unwrap();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Text], &["status"], &[1, 2]))
            .unwrap();
        assert_eq!(
            packet.abstain,
            Some(RecallAbstainReason::UnresolvedContradiction)
        );
        assert_eq!(packet.contradictions.len(), 1);
    }

    #[test]
    fn plasticity_does_not_mutate_current_snapshot() {
        let fabric = cross_modal_fabric();
        let before = fabric.clone();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Image], &["door"], &[1]))
            .unwrap();
        let batch = fabric
            .propose_plasticity(
                &packet,
                OutcomeSignal {
                    utility_delta_ppm: 400_000,
                    prediction_error_ppm: 500_000,
                    novelty_ppm: 200_000,
                    risk_ppm: 0,
                    ood_ppm: 0,
                },
            )
            .unwrap();
        assert_eq!(fabric, before);
        assert!(batch.current_snapshot_immutable);
        assert!(!batch.production_activation_allowed);
        assert_eq!(batch.predecessor_generation, 7);
        assert_eq!(batch.next_generation, 8);
        assert!(batch.weight_proposals.iter().all(|proposal| {
            i64::from(proposal.delta_ppm).abs()
                <= i64::from(fabric.config().maximum_weight_delta_ppm)
        }));
    }

    #[test]
    fn applying_plasticity_creates_exact_next_generation() {
        let fabric = cross_modal_fabric();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Image], &["door"], &[1]))
            .unwrap();
        let batch = fabric
            .propose_plasticity(
                &packet,
                OutcomeSignal {
                    utility_delta_ppm: 500_000,
                    prediction_error_ppm: 500_000,
                    novelty_ppm: 300_000,
                    risk_ppm: 0,
                    ood_ppm: 0,
                },
            )
            .unwrap();
        let next = fabric.apply_plasticity(&batch).unwrap();
        assert_eq!(fabric.generation(), 7);
        assert_eq!(next.generation(), 8);
        let proposal = batch.weight_proposals.first().unwrap();
        assert_eq!(
            next.synapse(proposal.source, proposal.target, proposal.relation)
                .unwrap()
                .weight_ppm,
            proposal.new_weight_ppm
        );
    }

    #[test]
    fn homeostasis_raises_threshold_for_active_node() {
        let fabric = cross_modal_fabric();
        let packet = fabric
            .recall(&cue(&[ModalityKind::Image], &["door"], &[1]))
            .unwrap();
        let batch = fabric
            .propose_plasticity(
                &packet,
                OutcomeSignal {
                    utility_delta_ppm: 0,
                    prediction_error_ppm: 0,
                    novelty_ppm: 0,
                    risk_ppm: 0,
                    ood_ppm: 0,
                },
            )
            .unwrap();
        let proposal = batch
            .threshold_proposals
            .iter()
            .find(|proposal| proposal.node_id == 1)
            .unwrap();
        assert!(proposal.delta_ppm > 0);
        assert!(proposal.new_threshold_ppm > proposal.old_threshold_ppm);
    }

    #[test]
    fn eligibility_trace_decays_without_new_coactivation() {
        let mut fabric = cross_modal_fabric();
        fabric
            .synapses
            .get_mut(&(1, 2, SynapseRelation::Associative))
            .unwrap()
            .eligibility_ppm = 500_000;
        let packet = RecallPacket {
            snapshot_generation: fabric.generation(),
            candidate_event_count: 1,
            selected_events: vec![1],
            active_nodes: vec![ActiveNode {
                node_id: 1,
                population: EngramPopulation::SensoryTrace,
                activation_ppm: 500_000,
            }],
            activation_paths: Vec::new(),
            contradictions: Vec::new(),
            coverage_ppm: 1_000_000,
            confidence_ppm: 900_000,
            ood_ppm: 0,
            settling_steps: 1,
            abstain: None,
            contains_raw_source_payload: false,
        };
        let batch = fabric
            .propose_plasticity(
                &packet,
                OutcomeSignal {
                    utility_delta_ppm: 0,
                    prediction_error_ppm: 0,
                    novelty_ppm: 0,
                    risk_ppm: 0,
                    ood_ppm: 0,
                },
            )
            .unwrap();
        let proposal = batch
            .weight_proposals
            .iter()
            .find(|proposal| {
                proposal.source == 1
                    && proposal.target == 2
                    && proposal.relation == SynapseRelation::Associative
            })
            .unwrap();
        assert_eq!(proposal.new_eligibility_ppm, 400_000);
        assert_eq!(proposal.delta_ppm, 0);
        assert_eq!(
            fabric
                .synapse(1, 2, SynapseRelation::Associative)
                .unwrap()
                .eligibility_ppm,
            500_000
        );
    }

    #[test]
    fn modulator_is_risk_and_ood_bounded() {
        let positive = OutcomeSignal {
            utility_delta_ppm: 900_000,
            prediction_error_ppm: 900_000,
            novelty_ppm: 900_000,
            risk_ppm: 0,
            ood_ppm: 0,
        }
        .modulator_ppm()
        .unwrap();
        let negative = OutcomeSignal {
            utility_delta_ppm: 100_000,
            prediction_error_ppm: 100_000,
            novelty_ppm: 100_000,
            risk_ppm: 900_000,
            ood_ppm: 900_000,
        }
        .modulator_ppm()
        .unwrap();
        assert_eq!(positive, PPM as i32);
        assert_eq!(negative, -(PPM as i32));
    }

    #[test]
    fn replay_selection_enforces_source_quota() {
        let candidates = (1..=6)
            .map(|event_id| ReplayCandidate {
                event_id,
                source_bucket: if event_id <= 4 { 1 } else { 2 },
                expected_utility_gain_ppm: 900_000 - event_id as u32,
                prediction_error_ppm: 800_000,
                novelty_ppm: 700_000,
                rarity_ppm: 600_000,
                forgetting_risk_ppm: 500_000,
                coverage_need_ppm: 400_000,
                privacy_allowed: true,
            })
            .collect::<Vec<_>>();
        let receipt = select_replay(&candidates, 4, 2).unwrap();
        assert_eq!(receipt.selected_event_ids.len(), 4);
        assert_eq!(receipt.source_bucket_counts.get(&1), Some(&2));
        assert_eq!(receipt.source_bucket_counts.get(&2), Some(&2));
    }

    #[test]
    fn forgetting_prevents_recall_resurrection() {
        let fabric = cross_modal_fabric();
        let batch = fabric.propose_forget(1).unwrap();
        let next = fabric.apply_forget(&batch).unwrap();
        assert_eq!(next.generation(), 8);
        assert!(next.event(1).unwrap().tombstoned);
        assert!(next.node(1).unwrap().retired);
        assert!(
            next.synapse(1, 2, SynapseRelation::Associative)
                .unwrap()
                .retired
        );
        let packet = next
            .recall(&cue(&[ModalityKind::Image], &["door"], &[1]))
            .unwrap();
        assert_eq!(packet.selected_events, Vec::<EventId>::new());
        assert_eq!(packet.abstain, Some(RecallAbstainReason::NoCandidate));
    }

    #[test]
    fn insertion_order_does_not_change_recall() {
        let first = cross_modal_fabric();
        let mut second = HnmfFabric::new(7, FabricConfig::default()).unwrap();
        second
            .insert_event(event(
                1,
                1,
                &[ModalityKind::Image, ModalityKind::Text],
                &["door", "red"],
            ))
            .unwrap();
        second
            .insert_node(node(
                3,
                EngramPopulation::SemanticConcept,
                &[ModalityKind::Text],
                &["door", "red"],
                &[1],
                120_000,
            ))
            .unwrap();
        second
            .insert_node(node(
                2,
                EngramPopulation::EpisodicBinding,
                &[ModalityKind::Text, ModalityKind::Image],
                &["door"],
                &[1],
                100_000,
            ))
            .unwrap();
        second
            .insert_node(node(
                1,
                EngramPopulation::SensoryTrace,
                &[ModalityKind::Image],
                &["door"],
                &[1],
                50_000,
            ))
            .unwrap();
        second
            .insert_synapse(synapse(2, 3, SynapseRelation::Supports, 800_000, &[1]))
            .unwrap();
        second
            .insert_synapse(synapse(1, 2, SynapseRelation::Associative, 900_000, &[1]))
            .unwrap();
        let recall_cue = cue(&[ModalityKind::Audio], &["door"], &[1]);
        assert_eq!(
            first.recall(&recall_cue).unwrap(),
            second.recall(&recall_cue).unwrap()
        );
    }

    #[test]
    fn topology_proposal_cannot_self_activate() {
        let proposal = TopologyProposal {
            predecessor_generation: 7,
            next_generation: 8,
            operation: TopologyOperation::SplitNode {
                node_id: 3,
                labels: ["door-red".to_string(), "door-blue".to_string()],
            },
            capability_typed: true,
            sandbox_only: true,
            operator_accepted: false,
            production_activation_allowed: false,
        };
        proposal.validate().unwrap();
        let invalid = TopologyProposal {
            production_activation_allowed: true,
            ..proposal
        };
        assert_eq!(invalid.validate(), Err(FabricError::AuthorityBoundary));
        assert!(!ONLINE_TOPOLOGY_ACTIVATION_ALLOWED);
        assert!(!PRODUCTION_AUTHORITY);
        assert!(!EXTERNAL_EFFECTS_ALLOWED);
        assert!(!CURRENT_RUN_MUTATION_ALLOWED);
    }

    #[test]
    fn hard_bounds_fail_closed() {
        let mut config = FabricConfig::default();
        config.maximum_recurrent_steps = 5;
        assert_eq!(
            HnmfFabric::new(1, config),
            Err(FabricError::BoundExceeded("fabric structural bound"))
        );
        let invalid_event = MemoryEvent {
            source_sha256: set(["not-a-digest".to_string()]),
            ..event(1, 1, &[ModalityKind::Text], &["alpha"])
        };
        assert_eq!(
            invalid_event.validate(),
            Err(FabricError::Invalid(
                "event source digest is not lowercase SHA-256"
            ))
        );
    }
}
