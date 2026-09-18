use super::*;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngramPopulationV1 {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EngramNodeV1 {
    #[serde(with = "super::exact_u64")]
    pub node_id: NodeIdV1,
    pub population: EngramPopulationV1,
    pub modality_mask: Vec<ModalityKindV1>,
    pub semantic_cue_keys: Vec<String>,
    pub support_manifest_sha256: Sha256DigestV1,
    pub threshold_q16: i32,
    pub target_activity_ppm: u32,
    pub confidence_ppm: u32,
    #[serde(with = "super::exact_u64")]
    pub snapshot_generation: u64,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for EngramNodeV1 {
    const SCHEMA_ID: &'static str = "EngramNodeV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.node_id == 0 || self.snapshot_generation == 0 {
            return Err(HnmfContractError::Invalid("engram identity/generation must be non-zero"));
        }
        if self.modality_mask.is_empty() || self.modality_mask.len() > ModalityKindV1::ALL.len() {
            return Err(HnmfContractError::BoundExceeded("engram modality mask"));
        }
        validate_sorted_unique_enum(&self.modality_mask, "engram modality mask")?;
        validate_sorted_unique_text(&self.semantic_cue_keys, MAX_SEMANTIC_KEYS, "engram semantic keys")?;
        ppm(self.target_activity_ppm, "engram target activity")?;
        ppm(self.confidence_ppm, "engram confidence")?;
        self.authority.validate()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SynapseRelationV1 {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseV1 {
    #[serde(with = "super::exact_u64")]
    pub source_node_id: NodeIdV1,
    #[serde(with = "super::exact_u64")]
    pub target_node_id: NodeIdV1,
    pub relation: SynapseRelationV1,
    pub weight_q16: i32,
    pub delay_steps: u32,
    pub plasticity_class: String,
    pub eligibility_ppm: i32,
    pub support_manifest_sha256: Sha256DigestV1,
    #[serde(with = "super::exact_u64")]
    pub snapshot_generation: u64,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for SynapseV1 {
    const SCHEMA_ID: &'static str = "SynapseV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == 0
            || self.target_node_id == 0
            || self.source_node_id == self.target_node_id
            || self.snapshot_generation == 0
        {
            return Err(HnmfContractError::Invalid("synapse endpoints/generation are invalid"));
        }
        if self.delay_steps > 4_096 {
            return Err(HnmfContractError::BoundExceeded("synapse delay"));
        }
        validate_text(&self.plasticity_class, 128, "plasticity class")?;
        if !(-1_000_000..=1_000_000).contains(&self.eligibility_ppm) {
            return Err(HnmfContractError::Invalid("synapse eligibility outside ppm range"));
        }
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallResourceBudgetV1 {
    pub maximum_candidate_events: u32,
    pub maximum_nodes: u32,
    pub maximum_synapses: u32,
    pub maximum_recurrent_steps: u8,
    pub maximum_recall_events: u16,
    pub maximum_activation_paths: u16,
}

impl RecallResourceBudgetV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.maximum_candidate_events == 0 || self.maximum_candidate_events > 512
            || self.maximum_nodes == 0 || self.maximum_nodes > 4_096
            || self.maximum_synapses == 0 || self.maximum_synapses > 32_768
            || self.maximum_recurrent_steps == 0 || self.maximum_recurrent_steps > 4
            || self.maximum_recall_events == 0 || usize::from(self.maximum_recall_events) > MAX_RECALL_EVENTS
            || self.maximum_activation_paths == 0 || usize::from(self.maximum_activation_paths) > MAX_ACTIVATION_PATHS
        {
            return Err(HnmfContractError::BoundExceeded("recall resource budget"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCueV1 {
    pub cue_id: String,
    pub objective_digest: Sha256DigestV1,
    pub ndu_state_digest: Sha256DigestV1,
    pub modalities: Vec<ModalityKindV1>,
    pub semantic_keys: Vec<String>,
    #[serde(with = "super::exact_u64_vec")]
    pub seed_node_ids: Vec<NodeIdV1>,
    #[serde(with = "super::exact_i64")]
    pub now_unix_ms: i64,
    pub resource_budget: RecallResourceBudgetV1,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for MemoryCueV1 {
    const SCHEMA_ID: &'static str = "MemoryCueV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        validate_text(&self.cue_id, 128, "cue id")?;
        if self.modalities.is_empty() || self.modalities.len() > ModalityKindV1::ALL.len() {
            return Err(HnmfContractError::BoundExceeded("cue modalities"));
        }
        validate_sorted_unique_enum(&self.modalities, "cue modalities")?;
        validate_sorted_unique_text(&self.semantic_keys, MAX_SEMANTIC_KEYS, "cue semantic keys")?;
        validate_sorted_unique_u64_bounded(&self.seed_node_ids, MAX_CUE_SEEDS, "cue seed nodes")?;
        self.resource_budget.validate()?;
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EventRevisionRefV1 {
    #[serde(with = "super::exact_u64")]
    pub event_id: EventIdV1,
    #[serde(with = "super::exact_u64")]
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActiveNodeV1 {
    #[serde(with = "super::exact_u64")]
    pub node_id: NodeIdV1,
    pub population: EngramPopulationV1,
    pub activation_ppm: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivationPathV1 {
    #[serde(with = "super::exact_u64")]
    pub source_node_id: NodeIdV1,
    #[serde(with = "super::exact_u64")]
    pub target_node_id: NodeIdV1,
    pub relation: SynapseRelationV1,
    pub contribution_ppm: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContradictionV1 {
    #[serde(with = "super::exact_u64")]
    pub left_node_id: NodeIdV1,
    #[serde(with = "super::exact_u64")]
    pub right_node_id: NodeIdV1,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecallAbstainReasonV1 {
    NoCandidate,
    OutOfDistribution,
    LowConfidence,
    UnresolvedContradiction,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceReceiptV1 {
    pub candidate_events: u32,
    pub nodes_considered: u32,
    pub synapses_considered: u32,
    pub recurrent_steps: u8,
    pub truncated: bool,
}

impl ResourceReceiptV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.candidate_events > 512
            || self.nodes_considered > 4_096
            || self.synapses_considered > 32_768
            || self.recurrent_steps > 4
        {
            return Err(HnmfContractError::BoundExceeded("resource receipt"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallPacketV1 {
    pub cue_digest: Sha256DigestV1,
    pub event_snapshot_digest: Sha256DigestV1,
    pub engram_snapshot_digest: Sha256DigestV1,
    pub selected_events: Vec<EventRevisionRefV1>,
    pub active_nodes: Vec<ActiveNodeV1>,
    pub activation_paths: Vec<ActivationPathV1>,
    pub contradictions: Vec<ContradictionV1>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: Option<RecallAbstainReasonV1>,
    pub resource_receipt: ResourceReceiptV1,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for RecallPacketV1 {
    const SCHEMA_ID: &'static str = "RecallPacketV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.selected_events.len() > MAX_RECALL_EVENTS
            || self.active_nodes.len() > MAX_SUBGRAPH_NODES
            || self.activation_paths.len() > MAX_ACTIVATION_PATHS
        {
            return Err(HnmfContractError::BoundExceeded("recall packet"));
        }
        ppm(self.coverage_ppm, "recall coverage")?;
        ppm(self.confidence_ppm, "recall confidence")?;
        ppm(self.ood_ppm, "recall OOD")?;
        self.resource_receipt.validate()?;
        self.authority.validate()
    }
}
