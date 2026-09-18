use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EventIdV1;
use super::MAX_SUPPORT_EVENTS;
use super::ModalityKindV1;
use super::NodeIdV1;
use super::TimeIntervalV1;
use super::validate_nonzero;
use super::validate_ppm;
use super::validate_semantic_keys;
use super::validate_signed_ppm;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
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

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
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

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlasticityClassV1 {
    Frozen,
    Hebbian,
    EligibilityModulated,
    Homeostatic,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct EngramNodeV1 {
    node_id: NodeIdV1,
    population: EngramPopulationV1,
    modality_mask: BTreeSet<ModalityKindV1>,
    semantic_keys: BTreeSet<String>,
    support_event_ids: BTreeSet<EventIdV1>,
    support_manifest_sha256: CanonicalDigestV1,
    threshold_q16: i32,
    target_activity_ppm: u32,
    confidence_ppm: u32,
    valid_interval: TimeIntervalV1,
    snapshot_generation: u64,
    retired: bool,
}

impl EngramNodeV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        node_id: NodeIdV1,
        population: EngramPopulationV1,
        modality_mask: BTreeSet<ModalityKindV1>,
        semantic_keys: BTreeSet<String>,
        support_event_ids: BTreeSet<EventIdV1>,
        support_manifest_sha256: CanonicalDigestV1,
        threshold_q16: i32,
        target_activity_ppm: u32,
        confidence_ppm: u32,
        valid_interval: TimeIntervalV1,
        snapshot_generation: u64,
        retired: bool,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            node_id,
            population,
            modality_mask,
            semantic_keys,
            support_event_ids,
            support_manifest_sha256,
            threshold_q16,
            target_activity_ppm,
            confidence_ppm,
            valid_interval,
            snapshot_generation,
            retired,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.node_id, "node id must be non-zero")?;
        validate_nonzero(self.snapshot_generation, "snapshot generation must be non-zero")?;
        if self.modality_mask.is_empty() || self.modality_mask.len() > ModalityKindV1::ALL.len() {
            return Err(ContractErrorV1::BoundExceeded("node modality mask"));
        }
        validate_semantic_keys(&self.semantic_keys)?;
        if self.support_event_ids.len() > MAX_SUPPORT_EVENTS
            || (!self.retired && self.support_event_ids.is_empty())
            || self.support_event_ids.contains(&0)
        {
            return Err(ContractErrorV1::BoundExceeded("node support events"));
        }
        validate_signed_ppm(self.threshold_q16, "node threshold")?;
        validate_ppm(self.target_activity_ppm, "node target activity")?;
        validate_ppm(self.confidence_ppm, "node confidence")?;
        self.valid_interval.validate()
    }

    #[must_use]
    pub const fn node_id(&self) -> NodeIdV1 {
        self.node_id
    }

    #[must_use]
    pub const fn population(&self) -> EngramPopulationV1 {
        self.population
    }

    #[must_use]
    pub fn support_event_ids(&self) -> &BTreeSet<EventIdV1> {
        &self.support_event_ids
    }

    #[must_use]
    pub const fn snapshot_generation(&self) -> u64 {
        self.snapshot_generation
    }
}

impl CanonicalContractV1 for EngramNodeV1 {
    const SCHEMA_ID: &'static str = "EngramNodeV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SynapseV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
    weight_q16: i32,
    delay_steps: u8,
    plasticity_class: PlasticityClassV1,
    eligibility_q16: i32,
    support_event_ids: BTreeSet<EventIdV1>,
    support_manifest_sha256: CanonicalDigestV1,
    snapshot_generation: u64,
    retired: bool,
}

impl SynapseV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
        weight_q16: i32,
        delay_steps: u8,
        plasticity_class: PlasticityClassV1,
        eligibility_q16: i32,
        support_event_ids: BTreeSet<EventIdV1>,
        support_manifest_sha256: CanonicalDigestV1,
        snapshot_generation: u64,
        retired: bool,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
            weight_q16,
            delay_steps,
            plasticity_class,
            eligibility_q16,
            support_event_ids,
            support_manifest_sha256,
            snapshot_generation,
            retired,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.source_node_id, "synapse source must be non-zero")?;
        validate_nonzero(self.target_node_id, "synapse target must be non-zero")?;
        if self.source_node_id == self.target_node_id {
            return Err(ContractErrorV1::Invalid("synapse endpoints must be distinct"));
        }
        if self.delay_steps > 32 {
            return Err(ContractErrorV1::BoundExceeded("synapse delay steps"));
        }
        validate_signed_ppm(self.weight_q16, "synapse weight")?;
        validate_signed_ppm(self.eligibility_q16, "synapse eligibility")?;
        if self.support_event_ids.len() > MAX_SUPPORT_EVENTS
            || (!self.retired && self.support_event_ids.is_empty())
            || self.support_event_ids.contains(&0)
        {
            return Err(ContractErrorV1::BoundExceeded("synapse support events"));
        }
        validate_nonzero(self.snapshot_generation, "snapshot generation must be non-zero")
    }
}

impl CanonicalContractV1 for SynapseV1 {
    const SCHEMA_ID: &'static str = "SynapseV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}
