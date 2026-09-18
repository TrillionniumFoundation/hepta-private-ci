use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::HnmfContractError;
use super::MAX_SEMANTIC_KEYS;
use super::ModalityKindV1;
use super::NodeIdV1;
use super::TimeIntervalV1;
use super::ValidateHnmfV1;
use super::ppm;
use super::q16_unit;
use super::signed_ppm;
use super::validate_keys;

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

impl EngramPopulationV1 {
    pub const ALL: [Self; 7] = [
        Self::SensoryTrace,
        Self::EpisodicBinding,
        Self::SemanticConcept,
        Self::ProceduralSkill,
        Self::PredictiveWorld,
        Self::UtilitySalience,
        Self::MetaMemory,
    ];
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EngramNodeV1 {
    node_id: NodeIdV1,
    population: EngramPopulationV1,
    modality_mask: BTreeSet<ModalityKindV1>,
    semantic_cue_keys: BTreeSet<String>,
    #[serde(with = "super::wire::digest")]
    support_manifest_sha256: Digest32,
    threshold_q16: i32,
    target_activity_ppm: u32,
    confidence_ppm: u32,
    validity_interval: TimeIntervalV1,
    snapshot_generation: u64,
}

impl EngramNodeV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        node_id: NodeIdV1,
        population: EngramPopulationV1,
        modality_mask: BTreeSet<ModalityKindV1>,
        semantic_cue_keys: BTreeSet<String>,
        support_manifest_sha256: Digest32,
        threshold_q16: i32,
        target_activity_ppm: u32,
        confidence_ppm: u32,
        validity_interval: TimeIntervalV1,
        snapshot_generation: u64,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            node_id,
            population,
            modality_mask,
            semantic_cue_keys,
            support_manifest_sha256,
            threshold_q16,
            target_activity_ppm,
            confidence_ppm,
            validity_interval,
            snapshot_generation,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn node_id(&self) -> NodeIdV1 {
        self.node_id
    }

    pub const fn population(&self) -> EngramPopulationV1 {
        self.population
    }
}

impl ValidateHnmfV1 for EngramNodeV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.node_id == 0 || self.snapshot_generation == 0 {
            return Err(HnmfContractError::Invalid(
                "engram node id and generation must be non-zero",
            ));
        }
        if self.modality_mask.is_empty() || self.modality_mask.len() > ModalityKindV1::ALL.len() {
            return Err(HnmfContractError::BoundExceeded("engram modality mask"));
        }
        validate_keys(
            &self.semantic_cue_keys,
            MAX_SEMANTIC_KEYS,
            "engram semantic cue keys",
        )?;
        if self.support_manifest_sha256.is_zero() {
            return Err(HnmfContractError::Invalid(
                "engram support manifest must be non-zero",
            ));
        }
        q16_unit(self.threshold_q16, "engram threshold")?;
        ppm(self.target_activity_ppm, "engram target activity")?;
        ppm(self.confidence_ppm, "engram confidence")?;
        self.validity_interval.validate()
    }
}

impl CanonicalJsonV1 for EngramNodeV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.engram-node.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
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

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlasticityClassV1 {
    Static,
    EligibilityModulated,
    HomeostaticCandidate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
    weight_q16: i32,
    delay_steps: u8,
    plasticity_class: PlasticityClassV1,
    eligibility_ppm: i32,
    #[serde(with = "super::wire::digest")]
    support_manifest_sha256: Digest32,
    snapshot_generation: u64,
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
        eligibility_ppm: i32,
        support_manifest_sha256: Digest32,
        snapshot_generation: u64,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
            weight_q16,
            delay_steps,
            plasticity_class,
            eligibility_ppm,
            support_manifest_sha256,
            snapshot_generation,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn source_node_id(&self) -> NodeIdV1 {
        self.source_node_id
    }

    pub const fn target_node_id(&self) -> NodeIdV1 {
        self.target_node_id
    }

    pub const fn relation(&self) -> SynapseRelationV1 {
        self.relation
    }
}

impl ValidateHnmfV1 for SynapseV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == 0
            || self.target_node_id == 0
            || self.source_node_id == self.target_node_id
            || self.snapshot_generation == 0
        {
            return Err(HnmfContractError::Invalid(
                "synapse endpoints must be distinct non-zero ids and generation non-zero",
            ));
        }
        if self.delay_steps > 4 {
            return Err(HnmfContractError::BoundExceeded("synapse delay"));
        }
        q16_unit(self.weight_q16, "synapse weight")?;
        signed_ppm(self.eligibility_ppm, "synapse eligibility")?;
        if self.support_manifest_sha256.is_zero() {
            return Err(HnmfContractError::Invalid(
                "synapse support manifest must be non-zero",
            ));
        }
        Ok(())
    }
}

impl CanonicalJsonV1 for SynapseV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.synapse.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}
